"""Application-owned tool contracts, independent of the agent harness."""

DEMO_RECORDS = (
    {"id": "demo-website", "title": "Demo website redesign", "status": "Planning"},
    {
        "id": "demo-onboarding",
        "title": "Demo onboarding checklist",
        "status": "In progress",
    },
    {"id": "demo-report", "title": "Demo monthly report", "status": "Draft"},
)


def search_demo_records(store, principal, query):
    """The DB checks membership/RLS; only fixed synthetic fixture fields leave it."""
    query = str(query).strip()[:120]
    with store.connection(principal) as db:
        rows = db.execute(
            "SELECT payload->>'agent_demo_id' AS demo_id FROM records "
            "WHERE workspace_id=%s AND payload->>'agent_demo_id' = ANY(%s)",
            (principal.tenant_id, [item["id"] for item in DEMO_RECORDS]),
        ).fetchall()
    existing = {row["demo_id"] for row in rows}
    matches = [
        dict(item)
        for item in DEMO_RECORDS
        if item["id"] in existing and query.casefold() in item["title"].casefold()
    ]
    return {"records": matches, "count": len(matches), "synthetic_only": True}


def seed_demo_records(store, principal):
    """Explicit developer setup, never exposed as an agent tool."""
    existing = search_demo_records(store, principal, "")["records"]
    ids = {item["id"] for item in existing}
    for item in DEMO_RECORDS:
        if item["id"] not in ids:
            store.create_record(
                principal,
                item["title"],
                {"agent_demo_id": item["id"], "synthetic": True},
            )


DOMAIN_TOOLS = (
    "search_feedback",
    "get_feedback",
    "search_opportunities",
    "get_opportunity",
)


def domain_tool(store, principal, name, arguments):
    """Allowlisted evidence only, through caller-scoped RLS connections."""
    from uuid import UUID

    if name not in DOMAIN_TOOLS or not isinstance(arguments, dict):
        return {"error": "Tool not available."}
    query = arguments.get("query", "")
    if not isinstance(query, str) or len(query) > 120:
        return {"error": "Search must be at most 120 characters."}
    if name.startswith("get_"):
        try:
            identifier = UUID(arguments.get("id", ""))
        except (ValueError, TypeError, AttributeError):
            return {"error": "A valid record UUID is required."}
        if name == "get_feedback":
            with store.connection(principal) as db:
                row = db.execute(
                    """SELECT f.id,f.title,f.description,
                    (SELECT count(*) FROM feedback_support s WHERE s.feedback_id=f.id
                     AND s.workspace_id=f.workspace_id) AS support_count
                    FROM feedback f WHERE f.id=%s AND f.workspace_id=%s""",
                    (identifier, principal.tenant_id),
                ).fetchone()
        else:
            row = store.opportunity(principal, identifier)
        if not row:
            return {"error": "Record not found in this workspace."}
        if name == "get_feedback":
            return feedback_evidence(row)
        feedback = row.get("feedback", [])
        return {
            "id": str(row["id"]),
            "name": row["name"],
            "problem": row["problem"],
            "source": "#opportunities?id=" + str(row["id"]),
            "feedback": [feedback_evidence(item) for item in feedback[:20]],
            "feedback_count": len(feedback),
            "has_more": len(feedback) > 20,
        }
    result = (
        store.list_feedback(principal, query, limit=10)
        if name == "search_feedback"
        else store.opportunities(principal, query, limit=10)
    )
    if name == "search_feedback":
        items = [feedback_evidence(row) for row in result["items"]]
    else:
        items = [
            {
                "id": str(row["id"]),
                "name": row["name"],
                "problem": row["problem"],
                "feedback_count": row["feedback_count"],
                "source": "#opportunities?id=" + str(row["id"]),
            }
            for row in result["items"]
        ]
    return {"items": items, "has_more": result["has_more"]}


def feedback_evidence(row):
    from urllib.parse import urlencode

    return {
        "id": str(row["id"]),
        "title": row["title"],
        "description": row["description"],
        "support_count": row.get("support_count"),
        "source": "#inbox?" + urlencode({"id": str(row["id"]), "search": row["title"]}),
    }
