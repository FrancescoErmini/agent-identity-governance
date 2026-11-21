"""agent-dq: the autonomous agent. It works as itself, with its own identity and role.

It finds visits with missing fields and asks each rep to complete them. It reads and writes
only through LiteLLM and the MCP server, with a client-credentials token: no person involved.
"""
import asyncio
import os
import uuid

from fastapi import FastAPI

from agentkit import AgentIdentity, call_tool, claims, tools_session

app = FastAPI(title="agent-dq")
me = AgentIdentity("agent-dq")
INTERVAL = int(os.environ.get("DQ_INTERVAL_SECONDS", "0"))   # 0: only when the scheduler calls /run


@app.get("/jwks")
def jwks():
    return me.jwks()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/run")
async def run(limit: int = 5):
    token = await me.own_token()
    correlation_id = f"corr-{uuid.uuid4().hex[:12]}"
    c = claims(token)
    steps = []
    async with tools_session(token, await me.own_token(), correlation_id) as session:
        found = await call_tool(session, "list_incomplete_visits", {"limit": limit})
        steps.append(found)
        for visit in (found.get("result") or {}).get("items", []):
            missing = [f for f in ("outcome", "next_step") if not visit.get(f)]
            steps.append(await call_tool(session, "create_reminder", {
                "visit_id": visit["id"],
                "text": f"Please complete {', '.join(missing)} for your visit to {visit['account_name']} "
                        f"on {visit['visit_date']}."}))
    return {"correlation_id": correlation_id, "acting_as": c.get("azp"), "sub": c.get("sub"),
            "roles": c.get("resource_access", {}).get("demo-crm", {}).get("roles", []), "steps": steps}


@app.on_event("startup")
async def _schedule():
    if INTERVAL > 0:
        async def loop():
            while True:
                await asyncio.sleep(INTERVAL)
                try:
                    await run()
                except Exception as exc:                       # noqa: BLE001
                    print(f"agent-dq run failed: {exc}")
        asyncio.create_task(loop())
