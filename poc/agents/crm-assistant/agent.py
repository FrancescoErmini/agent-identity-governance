"""crm-assistant: the delegated agent. It acts for the signed-in rep, never as itself.

For each request it exchanges the rep's token for a delegated one (sub = rep, act = this agent)
and uses only that token: model and tools go through LiteLLM, data comes from demo-crm.
Without ANTHROPIC_API_KEY it runs a fixed plan instead of the model, so every flow still works.
"""
import json
import os
import uuid
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from agentkit import AgentIdentity, call_tool, chat, claims, tools_session

app = FastAPI(title="crm-assistant")
me = AgentIdentity("agent-crm-assistant")
USE_MODEL = bool(os.environ.get("ANTHROPIC_API_KEY", "").startswith("sk-"))


@app.get("/jwks")
def jwks():
    return me.jwks()


@app.get("/health")
def health():
    return {"status": "ok", "mode": "model" if USE_MODEL else "scripted"}


class Ask(BaseModel):
    task: Literal["summary", "team_report", "forbidden_tool", "final_note", "chat"]
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

    async with tools_session(await me.own_token(), token, correlation_id) as session:
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
                raise HTTPException(400, "free chat needs ANTHROPIC_API_KEY")
            answer = await _agent_loop(session, token, correlation_id, ask.message or "", steps)

    return {
        "correlation_id": correlation_id,
        "acting_for": c.get("preferred_username"), "sub": c.get("sub"), "act": c.get("act"),
        "roles_in_delegated_token": c.get("resource_access", {}).get("demo-crm", {}).get("roles", []),
        "mode": "model" if USE_MODEL else "scripted",
        "steps": steps, "answer": answer,
    }


async def _summarise(token: str, correlation_id: str, account: dict) -> str:
    visits = account.get("visits", [])
    if not USE_MODEL:
        last = visits[0] if visits else {}
        return (f"Visit summary for {account['name']} ({account['specialty']}, {account['city']}): "
                f"{len(visits)} recent visits. Last on {last.get('visit_date', 'n/a')}, outcome "
                f"'{last.get('outcome') or 'missing'}', products {last.get('products', 'n/a')}. "
                f"Suggested next step: {last.get('next_step') or 'complete the last visit report'}.")
    msg = await chat(token, correlation_id, [
        {"role": "system", "content": "You are a pharma sales assistant. Write a short visit-preparation "
                                      "note (max 80 words) from the account data. Plain text."},
        {"role": "user", "content": json.dumps(account, default=str)}])
    return msg["content"]


async def _agent_loop(session, token: str, correlation_id: str, message: str, steps: list) -> str:
    listed = await session.list_tools()
    tools = [{"type": "function", "function": {"name": t.name, "description": t.description or "",
                                               "parameters": t.inputSchema}} for t in listed.tools]
    messages = [{"role": "system", "content": "You help a sales rep with demo-crm. Use the tools. "
                                              "Notes are always saved as drafts for the rep to confirm."},
                {"role": "user", "content": message}]
    for _ in range(6):
        reply = await chat(token, correlation_id, messages, tools)
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
