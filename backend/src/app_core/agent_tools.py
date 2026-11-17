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
    "search_tasks",
    "get_task",
)


def domain_tool(store, principal, name, arguments):
    """Allowlisted evidence only, through caller-scoped RLS connections."""
    from uuid import UUID

    if name not in DOMAIN_TOOLS or not isinstance(arguments, dict):
        return {"error": "Tool not available."}
    query = arguments.get("query", "")
    if not isinstance(query, str) or len(query) > 120:
        return {"error": "Search must be at most 120 characters."}
    if name == "search_tasks":
        with store.connection(principal) as db:
            rows = db.execute(
                """SELECT id,title,description,status,opportunity_id FROM tasks
                WHERE workspace_id=%s AND strpos(lower(title || ' ' || description),lower(%s))>0
                ORDER BY created_at DESC,id LIMIT 11""",
                (principal.tenant_id, query),
            ).fetchall()
        return {
            "items": [task_evidence(row) for row in rows[:10]],
            "has_more": len(rows) > 10,
        }
    if name.startswith("get_"):
        try:
            identifier = UUID(arguments.get("id", ""))
        except (ValueError, TypeError, AttributeError):
            return {"error": "A valid record UUID is required."}
        if name == "get_task":
            from fastapi import HTTPException

            try:
                row = store.task(principal, identifier)
            except HTTPException:
                return {"error": "Task not found in this workspace."}
            result = task_evidence(row)
            result["comments"] = comment_evidence(
                store.task_comments(principal, identifier)["items"]
            )
            return result
        if name == "get_feedback":
            with store.connection(principal) as db:
                row = db.execute(
                    """SELECT f.id,f.title,f.description,f.status,f.priority,
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
            result = feedback_evidence(row)
            state = store.triage_state(principal, identifier)
            result["opportunities"] = [
                {
                    "id": str(item["id"]),
                    "name": item["name"],
                    "source": "#opportunities?id=" + str(item["id"]),
                }
                for item in state["linked_opportunities"]
            ]
            if principal.role in {"admin", "editor"}:
                result["comments"] = comment_evidence(
                    store.feedback_comments(principal, identifier)["items"]
                )
            result["updates"] = [
                {"body": item["body"][:4000], "reply": item.get("reply")}
                for item in store.submitter_messages(principal, identifier)["items"][
                    :20
                ]
            ]
            return result
        feedback = row.get("feedback", [])
        return {
            "id": str(row["id"]),
            "name": row["name"],
            "problem": row["problem"],
            "description": row.get("description_markdown"),
            "status": row["status"],
            "priority": row["priority"],
            "tasks": [
                task_evidence(task)
                for task in store.list_tasks(principal, identifier, 20, 0)["items"]
            ],
            "comments": comment_evidence(
                store.opportunity_comments(principal, identifier)["items"]
            ),
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
        "status": row.get("status"),
        "priority": row.get("priority"),
        "support_count": row.get("support_count"),
        "source": "#inbox?" + urlencode({"id": str(row["id"]), "search": row["title"]}),
    }


def task_evidence(row):
    return {
        "id": str(row["id"]),
        "title": row["title"],
        "description": row["description"],
        "status": row["status"],
        "opportunity_id": str(row["opportunity_id"]),
        "source": "#tasks?id=" + str(row["id"]),
    }


def navigation_target(store, principal, arguments):
    from uuid import UUID

    pages = {
        "inbox",
        "opportunities",
        "tasks",
        "updates",
        "feedback",
        "settings",
        "home",
    }
    if not isinstance(arguments, dict):
        return {"error": "Invalid navigation arguments."}
    page = arguments.get("page")
    if page not in pages:
        return {"error": "Unknown application page."}
    identifier = arguments.get("id", "")
    if identifier:
        kinds = {"inbox": "feedback", "opportunities": "opportunity", "tasks": "task"}
        if page not in kinds:
            return {"error": "This page has no record details."}
        try:
            identifier = str(UUID(identifier))
        except (ValueError, TypeError):
            return {"error": "Invalid record ID."}
        result = domain_tool(store, principal, "get_" + kinds[page], {"id": identifier})
        if "error" in result:
            return result
    return {"href": "#" + page + ("?id=" + identifier if identifier else "")}


def comment_evidence(rows):
    return [
        {"body": row["body"][:4000], "created_at": row["created_at"].isoformat()}
        for row in rows[-20:]
    ]
