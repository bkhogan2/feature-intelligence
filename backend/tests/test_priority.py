"""Priority confirmation, tenant boundaries and source validation on real PostgreSQL."""

from uuid import uuid4
import pytest
from app_core.priority_models import validate_suggestion
from test_triage import principal, seed_opportunity
from test_feedback import feedback_setup as shared_feedback_setup


@pytest.fixture
def setup(pg_store):
    return shared_feedback_setup.__wrapped__(pg_store)


def suggestion(evidence=None):
    return dict(
        impact="high",
        confidence="low",
        priority="high",
        goals_alignment="Aligned with reducing manual PM triage work at the dogfood stage; effort remains unknown.",
        rationale="Potential workflow value merits attention despite limited evidence; investigate effort before committing.",
        workflow_impact="Reduces manual PM review if validated.",
        evidence_strength="Limited linked evidence.",
        dependencies="Unknown.",
        missing_information=["PM effort estimate"],
        evidence=evidence or [],
    )


def test_confirm_priority_separate_from_lifecycle_and_analysis(setup):
    store, ids, client, _ = setup
    p = principal(store, ids)
    oid = seed_opportunity(store, p)
    path = f"/api/v1/opportunities/{oid}"
    data = dict(
        priority="medium",
        rationale="Investigate PM workflow impact.",
        expected_revision=0,
    )
    assert client("viewer").put(path + "/priority", json=data).status_code == 403
    assert client("admin", "beta").put(path + "/priority", json=data).status_code == 404
    result = client("editor").put(path + "/priority", json=data)
    assert result.status_code == 200, result.text
    assert result.json()["priority"] == "medium"
    assert result.json()["status"] == "considering"
    assert result.json()["effort"] == ""
    assert result.json()["priority_analysis"] is None
    assert result.json()["priority_updated_by"] == ids["editor@example.com"]
    assert client("editor").put(path + "/priority", json=data).status_code == 409
    for bad in [
        dict(data, priority="urgent"),
        dict(data, rationale="  "),
        dict(data, priority_updated_by="forged"),
    ]:
        assert client("editor").put(path + "/priority", json=bad).status_code == 422
    run, created = store.start_priority(p, oid, "test", 120)
    assert created
    assert not store.start_priority(p, oid, "test", 120)[1]
    store.finish_priority(p, oid, run, suggestion())
    state = client("viewer").get(path).json()
    assert (
        state["priority"] == "medium"
        and state["priority_analysis"]["result"]["priority"] == "high"
    )
    assert client("viewer").post(path + "/priority/assess").status_code == 403
    accept = dict(
        priority="high",
        rationale=suggestion()["rationale"],
        expected_revision=1,
        accepted_analysis_id=run["id"],
    )
    assert (
        client("editor")
        .put(path + "/priority", json=dict(accept, accepted_analysis_id=str(uuid4())))
        .status_code
        == 409
    )
    assert (
        client("editor")
        .put(path + "/priority", json=dict(accept, priority="low"))
        .status_code
        == 409
    )
    saved = client("editor").put(path + "/priority", json=accept)
    assert saved.status_code == 200, saved.text
    assert (
        saved.json()["priority"] == "high" and saved.json()["status"] == "considering"
    )
    assert saved.json()["priority_analysis"]["id"] == run["id"]
    with store.connection(principal(store, ids, "viewer")) as db:
        assert (
            db.execute(
                "UPDATE opportunities SET priority='low' WHERE id=%s RETURNING id",
                (oid,),
            ).fetchall()
            == []
        )
    with store.connection(principal(store, ids, "admin", "beta")) as db:
        assert (
            db.execute(
                "SELECT priority_analysis FROM opportunities WHERE id=%s", (oid,)
            ).fetchall()
            == []
        )


def test_exact_source_grounding():
    fid = str(uuid4())
    feedback = [dict(id=fid, description="We manually compare requests.")]
    valid = suggestion([dict(feedback_id=fid, quote="manually compare requests")])
    assert validate_suggestion(valid, feedback)["priority"] == "high"
    for evidence in [
        [],
        [dict(feedback_id=fid, quote="Thousands of customers")],
        [dict(feedback_id=str(uuid4()), quote="manually compare requests")],
    ]:
        with pytest.raises(ValueError):
            validate_suggestion(suggestion(evidence), feedback)
    assert validate_suggestion(suggestion(), [])["evidence"] == []


@pytest.mark.parametrize("bad", [False, True])
def test_isolated_assessment_has_no_mutation_tools_and_preserves_priority(
    setup, monkeypatch, bad
):
    import time
    from test_triage import fake_worker

    store, ids, client, _ = setup
    oid = seed_opportunity(store, principal(store, ids))
    event = (
        {"type": "tool", "name": "shell", "arguments": {}}
        if bad
        else {"type": "done", "error": False, "result": suggestion(), "cost_usd": 0.002}
    )
    monkeypatch.setenv(
        "PRIORITY_PRODUCT_GOALS",
        "Reduce manual reviewing while preserving explicit PM decisions.",
    )
    monkeypatch.setenv(
        "PRIORITY_PRODUCT_STAGE", "Internal dogfood; impact remains unmeasured."
    )
    other = seed_opportunity(store, principal(store, ids), name="Alternative workflow")
    seed_opportunity(
        store, principal(store, ids, "admin", "beta"), name="Other tenant secret"
    )
    captured, writes = fake_worker(monkeypatch, None, events=[event])
    with client("admin") as c:
        path = f"/api/v1/opportunities/{oid}"
        response = c.post(path + "/priority/assess")
        assert response.status_code == 202, response.text
        for _ in range(100):
            detail = c.get(path).json()
            if detail["priority_analysis"]["status"] != "running":
                break
            time.sleep(0.02)
        assert detail["priority_analysis"]["status"] == (
            "failed" if bad else "complete"
        )
        assert detail["priority"] is None and detail["status"] == "considering"
        assert detail["effort"] == ""
        assert writes[0]["task"] == "priority"
        context = writes[0]["context"]
        assert context["product_context"] == detail["priority_context"]
        assert (
            context["product_context"]["goals"]
            == "Reduce manual reviewing while preserving explicit PM decisions."
        )
        assert (
            context["product_context"]["stage"]
            == "Internal dogfood; impact remains unmeasured."
        )
        assert [item["id"] for item in context["alternatives"]["items"]] == [other]
        assert (
            detail["priority_analysis"]["product_context"] == context["product_context"]
        )
        if not bad:
            assert detail["priority_analysis"]["cost_usd"] == 0.002
            assert detail["priority_analysis"]["result"]["impact"] == "high"
            assert detail["priority_analysis"]["result"]["confidence"] == "low"
            assert detail["priority_analysis"]["result"]["priority"] == "high"
        assert "DATABASE_URL" not in captured["env"]
        assert len(writes) == 1


@pytest.mark.parametrize("priority", ["high", "medium", "low"])
def test_sparse_evidence_does_not_mandate_priority(priority):
    # The server validates independent judgments, not a vote threshold or a confidence->priority mapping.
    fid = str(uuid4())
    record = {
        "id": fid,
        "description": "A manual step on every submission.",
        "support_count": 0,
    }
    value = suggestion([{"feedback_id": fid, "quote": record["description"]}])
    value["priority"] = priority
    result = validate_suggestion(value, [record])
    assert result["impact"] == "high" and result["confidence"] == "low"
    assert result["priority"] == priority
    for missing in ["impact", "confidence", "goals_alignment"]:
        with pytest.raises(ValueError):
            validate_suggestion(
                {key: item for key, item in value.items() if key != missing}, [record]
            )


def test_legacy_assessment_readable_but_requires_reassessment_to_accept(setup):
    store, ids, client, _ = setup
    p = principal(store, ids)
    oid = seed_opportunity(store, p)
    run, _ = store.start_priority(p, oid, "test", 120)
    run["prompt_version"] = "priority-v1"
    old = {
        key: value
        for key, value in suggestion().items()
        if key not in {"impact", "confidence", "goals_alignment"}
    }
    store.finish_priority(p, oid, run, old)
    path = f"/api/v1/opportunities/{oid}"
    c = client("admin")
    assert c.get(path).json()["priority_analysis"]["result"] == old
    assert (
        c.put(
            path + "/priority",
            json={
                "priority": old["priority"],
                "rationale": old["rationale"],
                "expected_revision": 0,
                "accepted_analysis_id": run["id"],
            },
        ).status_code
        == 409
    )
