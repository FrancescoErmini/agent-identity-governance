"""The seven acts of the Wave 0 demo, in order, as the audience sees them.

Runs inside the compose network: docker compose --profile check run --rm check
Each act prints what it proves. Acts 3, 5, 6 and 7 are the negative ones: something must be refused.
"""
import json
import sys
import time

sys.path.insert(0, "/tests")
import step2_check as t  # noqa: E402  shared helpers: browser login, http, claims

results: list[tuple[bool, str]] = []


def check(name, ok, detail=""):
    results.append((bool(ok), name))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({str(detail)[:300]})" if detail and not ok else ""))


def assist(token, task, account=None):
    status, _, raw = t.http("POST", f"{t.ASSISTANT}/assist", token, {"task": task, "account_id": account})
    return status, t.j(raw)


def team(action: str, team_id: str):
    status, _, _ = t.http("POST", f"{t.GATEWAY}/team/{action}", t.MASTER_KEY, {"team_id": team_id})
    return status


def main():
    for _ in range(60):
        try:
            if all(t.http("GET", f"{u}/health")[0] == 200 for u in (t.CRM, t.ASSISTANT, t.DQ, f"{t.GATEWAY}/health/liveliness")):
                break
        except OSError:
            pass
        time.sleep(2)
    team("unblock", "agent-crm-assistant")                 # a previous run may have stopped half way

    print("\nAct 1 · Luca logs in to demo-crm through Keycloak and sees only his territory")
    luca = t.browser_login("luca", "openid delegation:client:agent-crm-assistant")
    c = t.claims(luca)
    status, _, raw = t.http("GET", f"{t.CRM}/accounts", luca)
    accounts = t.j(raw).get("accounts", []) if status == 200 else []
    account = accounts[0]["id"] if accounts else None
    check("roles and territory in the JWT drive the app (NORTH only)",
          accounts and {a["territory"] for a in accounts} == {"NORTH"}, status)
    check("Luca consented: may_act names agent-crm-assistant", (c.get("may_act") or {}).get("client_id") == "agent-crm-assistant")

    print("\nAct 2 · The assistant drafts a visit note for Luca; it waits for his confirmation")
    status, out = assist(luca, "summary", account)
    note = next((s["result"] for s in out.get("steps", []) if s.get("tool") == "draft_visit_note" and "result" in s), {}) \
        if status == 200 else {}
    check("note stored as draft, created_by luca, via_agent agent-crm-assistant",
          note.get("status") == "draft" and note.get("created_by") == "luca" and note.get("via_agent") == "agent-crm-assistant",
          (status, out))
    status, _, raw = t.http("POST", f"{t.CRM}/notes/{note.get('id')}/confirm", luca)
    check("Luca confirms it himself: the note becomes final", status == 200 and t.j(raw).get("status") == "final", status)

    print("\nAct 3 · Luca, also area manager, asks for the team report; the app refuses the assistant")
    status, out = assist(luca, "team_report")
    step = (out.get("steps") or [{}])[0] if status == 200 else {}
    check("demo-crm refuses: the delegated token carries only rep",
          step.get("refused_by") == "demo-crm" and (step.get("error") or {}).get("error") == 403, (status, step))

    print("\nAct 4 · The scheduler starts agent-dq; reminders appear tagged as autonomous")
    status, _, raw = t.http("POST", f"{t.DQ}/run?limit=2")
    made = [s["result"] for s in t.j(raw).get("steps", []) if s.get("tool") == "create_reminder" and "result" in s] \
        if status == 200 else []
    check("reminders created by agent-dq with its own identity",
          made and all(r["via_agent"] == "agent-dq" and r["created_by"] == "service-account-agent-dq" for r in made), made)

    print("\nAct 5 · The assistant tries a tool outside its list, then a final note; LiteLLM refuses both")
    status, out = assist(luca, "forbidden_tool")
    step = (out.get("steps") or [{}])[0] if status == 200 else {}
    check("create_reminder refused by the gateway (not on the assistant's list)",
          step.get("refused_by") == "gateway" and "not allowed" in str(step.get("error")), step)
    status, out = assist(luca, "final_note", account)
    step = (out.get("steps") or [{}])[0] if status == 200 else {}
    check("draft_visit_note with status final refused by the gateway guardrail",
          step.get("refused_by") == "gateway" and "guardrail" in str(step.get("error")).lower(), step)

    print("\nAct 6 · The same final note sent straight to the API, bypassing the gateway")
    status, out = assist(luca, "bypass_gateway", account)
    step = (out.get("steps") or [{}])[0] if status == 200 else {}
    result = step.get("result") or {}
    check("demo-crm stores it only as a draft: two independent layers",
          result.get("status") == "draft" and result.get("via_agent") == "agent-crm-assistant", (status, step))

    print("\nAct 7 · The assistant is blocked in LiteLLM; its next call fails. The log shows sub and agent")
    check("kill switch: team agent-crm-assistant blocked", team("block", "agent-crm-assistant") == 200)
    try:
        status, out = assist(luca, "summary", account)
        check("the assistant's next call is refused at the gateway", status == 403 and "gateway" in str(out), (status, out))
    finally:
        team("unblock", "agent-crm-assistant")
    status, out = assist(luca, "summary", account)
    check("after unblocking, it works again", status == 200, status)
    logs = []
    for _ in range(15):
        logs = [l for l in t.spend_logs(c["sub"]) if l.get("call_type") == "call_mcp_tool"]
        if len(logs) >= 4:
            break
        time.sleep(2)
    check("every tool call in the LiteLLM log carries luca's sub and the agent's team",
          logs and all(l.get("user") == c["sub"] and l.get("team_id") == "agent-crm-assistant" for l in logs),
          [(l.get("user"), l.get("team_id")) for l in logs][:3])

    failed = [n for ok, n in results if not ok]
    print(f"\nDemo: {len(results) - len(failed)}/{len(results)} checks passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
