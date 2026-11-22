"""crm-assistant: the delegated agent. It acts for the signed-in rep, never as itself.

For each request it exchanges the rep's token for a delegated one (sub = rep, act = this agent)
and uses only that token: model and tools go through LiteLLM, data comes from demo-crm.
Without LLM_MODEL it runs a fixed plan instead of the model, so every flow still works.
"""
import json
import os
import uuid
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

import httpx

from agentkit import AgentIdentity, call_tool, chat, claims, tools_session

app = FastAPI(title="crm-assistant")
me = AgentIdentity("agent-crm-assistant")
MODEL = os.environ.get("LLM_MODEL", "").strip()          # a LiteLLM model name: gpt, claude-sonnet
USE_MODEL = bool(MODEL)


@app.get("/jwks")
def jwks():
    return me.jwks()


@app.get("/health")
def health():
    return {"status": "ok", "mode": "model" if USE_MODEL else "scripted"}


class Ask(BaseModel):
    task: Literal["summary", "team_report", "forbidden_tool", "final_note", "bypass_gateway", "chat"]
    account_id: str | None = None
    message: str | None = None


@app.post("/assist")
async def assist(ask: Ask, authorization: str = Header(...)):
    user_token = authorization.removeprefix("Bearer ").strip()
    correlation_id = f"corr-{uuid.uuid4().hex[:12]}"
    try:
        token = await me.delegated_token(user_token)
    except PermissionError as exc:
        raise HTTPException(403, f"delegation refused: {exc}") from exc
    c = claims(token)

    steps: list[dict] = []
    answer = ""
    try:
        if ask.task == "bypass_gateway":               # act 6: no gateway, no MCP session
            steps.append(await _direct_call(token, correlation_id, ask.account_id))
        else:
            async with tools_session(await me.own_token(), token, correlation_id) as session:
                steps, answer = await _run(ask, session, token, correlation_id)
    except BaseException as exc:                       # noqa: BLE001  the MCP client wraps errors in (base) groups
        if (refused := _find(exc, httpx.HTTPStatusError)) is not None:
            # the gateway turned the agent away before any tool ran (e.g. the kill switch)
            raise HTTPException(403, f"gateway refused agent-crm-assistant ({refused.response.status_code}): "
                                     "the agent is blocked or not admitted at LiteLLM") from None
        if (model_error := _find(exc, RuntimeError)) is not None:
            raise HTTPException(502, str(model_error)) from None
        raise
    return {
        "correlation_id": correlation_id,
        "acting_for": c.get("preferred_username"), "sub": c.get("sub"), "act": c.get("act"),
        "roles_in_delegated_token": c.get("resource_access", {}).get("demo-crm", {}).get("roles", []),
        "mode": f"model {MODEL}" if USE_MODEL else "scripted",
        "steps": steps, "answer": answer,
    }


async def _run(ask: "Ask", session, token: str, correlation_id: str) -> tuple[list, str]:
    steps: list[dict] = []
    answer = ""
    if ask.task == "summary":
        acc = await call_tool(session, "get_account_summary", {"account_id": ask.account_id})
        steps.append(acc)
        if "result" in acc:
            summary = await _summarise(token, correlation_id, acc["result"])
            note = await call_tool(session, "draft_visit_note",
                                   {"account_id": ask.account_id, "text": summary})
            steps.append(note)
            answer = summary
    elif ask.task == "team_report":            # act 3: the rep is also area manager, the agent is not
        steps.append(await call_tool(session, "get_team_report", {}))
    elif ask.task == "forbidden_tool":         # act 5: a tool that is not on this agent's list
        steps.append(await call_tool(session, "create_reminder",
                                     {"visit_id": "VIS-00000", "text": "sent by the assistant"}))
    elif ask.task == "final_note":             # act 5: a note marked final
        steps.append(await call_tool(session, "draft_visit_note",
                                     {"account_id": ask.account_id, "text": "Final note written by the assistant",
                                      "status": "final"}))
    elif ask.task == "chat":
        if not USE_MODEL:
            raise HTTPException(400, "free chat needs LLM_MODEL (see .env.example)")
        answer = await _agent_loop(session, token, correlation_id, ask.message or "", steps)
    return steps, answer


async def _summarise(token: str, correlation_id: str, account: dict) -> str:
    visits = account.get("visits", [])
    if not USE_MODEL:
        last = visits[0] if visits else {}
        return (f"Visit summary for {account['name']} ({account['specialty']}, {account['city']}): "
                f"{len(visits)} recent visits. Last on {last.get('visit_date', 'n/a')}, outcome "
                f"'{last.get('outcome') or 'missing'}', products {last.get('products', 'n/a')}. "
                f"Suggested next step: {last.get('next_step') or 'complete the last visit report'}.")
    msg = await chat(token, correlation_id, MODEL, [
        {"role": "system", "content": "You are a pharma sales assistant. Write a short visit-preparation "
                                      "note (max 80 words) from the account data. Plain text."},
        {"role": "user", "content": json.dumps(account, default=str)}])
    return msg["content"]


async def _agent_loop(session, token: str, correlation_id: str, message: str, steps: list) -> str:
    listed = await session.list_tools()
    tools = [{"type": "function", "function": {"name": t.name, "description": t.description or "",
                                               "parameters": t.inputSchema}} for t in listed.tools]
    messages = [{"role": "system", "content": (
        "You help a sales rep with demo-crm. Use the tools. Notes are always saved as drafts for the rep "
        "to confirm. You act with a delegated token that carries only the sales-rep role, even when the "
        "rep has more roles. If a tool is refused (403 from demo-crm, or not allowed by the gateway), "
        "say that you, the assistant, are not allowed to do it on their behalf, and that they can do it "
        "themselves in demo-crm if their own role allows it. Never tell them they lack the permission. "
        "Answer in the user's language.")},
                {"role": "user", "content": message}]
    for _ in range(6):
        reply = await chat(token, correlation_id, MODEL, messages, tools)
        messages.append(reply)
        if not reply.get("tool_calls"):
            return reply.get("content") or ""
        for call in reply["tool_calls"]:
            args = json.loads(call["function"]["arguments"] or "{}")
            outcome = await call_tool(session, call["function"]["name"], args)
            steps.append(outcome)
            messages.append({"role": "tool", "tool_call_id": call["id"],
                             "content": json.dumps(outcome, default=str)[:4000]})
    return "Stopped after six steps."


def _find(exc: BaseException, kind: type) -> BaseException | None:
    if isinstance(exc, kind):
        return exc
    for inner in getattr(exc, "exceptions", ()):
        if found := _find(inner, kind):
            return found
    return None


async def _direct_call(token: str, correlation_id: str, account_id: str | None) -> dict:
    """What a misbehaving agent could try: call demo-crm itself with its delegated token. No gateway
    rule applies here, so only demo-crm's own rule stands: notes from an agent are stored as drafts."""
    args = {"account_id": account_id, "text": "Final note sent straight to the API", "status": "final"}
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(f"{os.environ.get('DEMO_CRM_API', 'http://demo-crm-api:8080')}/notes", json=args,
                              headers={"Authorization": f"Bearer {token}", "x-correlation-id": correlation_id})
    if r.status_code >= 400:
        return {"tool": "POST /notes (direct)", "args": args, "refused_by": "demo-crm", "error": r.json()}
    return {"tool": "POST /notes (direct)", "args": args, "result": r.json()}
