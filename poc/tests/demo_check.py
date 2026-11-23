"""The seven acts of the Wave 0 demo, in order, as the audience sees them.

Runs inside the compose network: docker compose --profile check run --rm check
Each act prints what it proves. Acts 3, 5, 6 and 7 are the negative ones: something must be refused.

With EVIDENCE_DIR set (docker compose --profile check run --rm evidence) it also keeps the evidence
of the run: what each act returned, the token claims, the LiteLLM log rows and the demo-crm records.
"""
import json
import os
import sys
import time
import urllib.parse
from datetime import datetime, timezone

sys.path.insert(0, "/tests")
import step2_check as t  # noqa: E402  shared helpers: browser login, http, claims

UI = "http://demo-crm-ui:3000"
results: list[tuple[bool, str]] = []
evidence: dict = {"acts": {}}
_act = None


def act(title: str):
    global _act
    _act = title
    evidence["acts"][title] = {"checks": [], "responses": []}
    print(f"\n{title}")


def keep(label: str, payload):
    if _act:
        evidence["acts"][_act]["responses"].append({"what": label, "payload": payload})


def check(name, ok, detail=""):
    results.append((bool(ok), name))
    if _act:
        evidence["acts"][_act]["checks"].append({"check": name, "passed": bool(ok)})
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({str(detail)[:300]})" if detail and not ok else ""))


def assist(token, task, account=None):
    status, _, raw = t.http("POST", f"{t.ASSISTANT}/assist", token, {"task": task, "account_id": account})
    keep(f"crm-assistant /assist task={task} -> HTTP {status}", t.j(raw))
    return status, t.j(raw)


def audit(token, **query) -> list:
    status, _, raw = t.http("GET", f"{t.CRM}/audit?{urllib.parse.urlencode(query)}", token)
    return t.j(raw) if status == 200 else []


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

    act("Act 1 · Luca signs in to the AI assistant app: Keycloak asks his consent; he sees only his territory")
    luca = t.browser_login("luca", "openid delegation:client:agent-crm-assistant")
    c = t.claims(luca)
    keep("luca's access token after login with consent (claims)",
         {k: c.get(k) for k in ("iss", "sub", "azp", "aud", "scope", "may_act", "resource_access", "territory",
                                "preferred_username")})
    status, _, raw = t.http("GET", f"{t.CRM}/accounts", luca)
    accounts = t.j(raw).get("accounts", []) if status == 200 else []
    account = accounts[0]["id"] if accounts else None
    check("roles and territory in the JWT drive the app (NORTH only)",
          accounts and {a["territory"] for a in accounts} == {"NORTH"}, status)
    check("Luca consented: may_act names agent-crm-assistant", (c.get("may_act") or {}).get("client_id") == "agent-crm-assistant")

    act("AS-IS · Luca writes a visit note by hand; the audit names Luca, no agent")
    luca_crm = t.browser_login("luca", "openid", client="crm-web")       # the CRM: plain login, no AI consent
    check("the CRM login asks no consent and grants no delegation (no may_act), roles from the token",
          "may_act" not in t.claims(luca_crm) and t.claims(luca_crm).get("azp") == "crm-web", t.claims(luca_crm))
    status, _, raw = t.http("POST", f"{UI}/api/notes", luca_crm,
                            {"account_id": account, "text": "Met the doctor, follow up in two weeks", "status": "final"})
    manual = t.j(raw)
    keep(f"POST /notes by hand through the UI -> HTTP {status}", manual)
    check("the note is final at once, created_by luca, no agent",
          status == 201 and manual.get("status") == "final" and manual.get("via_agent") is None, (status, manual))
    rows = audit(luca, writes_only="true", person="luca")
    row = next((r for r in rows if r.get("object") == f"note:{manual.get('id')} (final)"), {})
    keep("audit row for the manual note", row)
    check("audit: luca by hand, from the demo-crm UI; JWT verified, azp crm-web, no act",
          row.get("actor_type") == "person" and row.get("source") == "demo-crm UI" and row.get("token_verified")
          and (row.get("token_claims") or {}).get("azp") == "crm-web" and "act" not in (row.get("token_claims") or {}), row)

    act("Act 2 · The assistant drafts a visit note for Luca; it waits for his confirmation")
    status, out = assist(luca, "summary", account)
    note = next((s["result"] for s in out.get("steps", []) if s.get("tool") == "draft_visit_note" and "result" in s), {}) \
        if status == 200 else {}
    check("note stored as draft, created_by luca, via_agent agent-crm-assistant",
          note.get("status") == "draft" and note.get("created_by") == "luca" and note.get("via_agent") == "agent-crm-assistant",
          (status, out))
    status, _, raw = t.http("POST", f"{t.CRM}/notes/{note.get('id')}/confirm", luca)
    check("Luca confirms it himself: the note becomes final", status == 200 and t.j(raw).get("status") == "final", status)

    act("Act 3 · Luca, also area manager, asks for the team report; the app refuses the assistant")
    status, out = assist(luca, "team_report")
    step = (out.get("steps") or [{}])[0] if status == 200 else {}
    check("demo-crm refuses: the delegated token carries only rep",
          step.get("refused_by") == "demo-crm" and (step.get("error") or {}).get("error") == 403, (status, step))

    act("Act 4 · The scheduler starts agent-dq; reminders appear tagged as autonomous")
    status, _, raw = t.http("POST", f"{t.DQ}/run?limit=2")
    keep(f"agent-dq /run -> HTTP {status}", t.j(raw))
    made = [s["result"] for s in t.j(raw).get("steps", []) if s.get("tool") == "create_reminder" and "result" in s] \
        if status == 200 else []
    check("reminders created by agent-dq with its own identity",
          made and all(r["via_agent"] == "agent-dq" and r["created_by"] == "service-account-agent-dq" for r in made), made)

    act("Act 5 · The assistant tries a tool outside its list, then a final note; LiteLLM refuses both")
    status, out = assist(luca, "forbidden_tool")
    step = (out.get("steps") or [{}])[0] if status == 200 else {}
    check("create_reminder refused by the gateway (not on the assistant's list)",
          step.get("refused_by") == "gateway" and "not allowed" in str(step.get("error")), step)
    status, out = assist(luca, "final_note", account)
    step = (out.get("steps") or [{}])[0] if status == 200 else {}
    check("draft_visit_note with status final refused by the gateway guardrail",
          step.get("refused_by") == "gateway" and "guardrail" in str(step.get("error")).lower(), step)

    act("Act 6 · The same final note sent straight to the API, bypassing the gateway")
    status, out = assist(luca, "bypass_gateway", account)
    step = (out.get("steps") or [{}])[0] if status == 200 else {}
    result = step.get("result") or {}
    check("demo-crm stores it only as a draft: two independent layers",
          result.get("status") == "draft" and result.get("via_agent") == "agent-crm-assistant", (status, step))

    act("Act 7 · The assistant is blocked in LiteLLM; its next call fails. The log shows sub and agent")
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
    if os.environ.get("EVIDENCE_DIR"):
        write_evidence(luca, c, made, len(results) - len(failed), len(results))
    sys.exit(1 if failed else 0)


def write_evidence(luca: str, luca_claims: dict, reminders: list, passed: int, total: int) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = os.path.join(os.environ["EVIDENCE_DIR"], f"run-{stamp}")
    os.makedirs(out, exist_ok=True)
    fields = ("startTime", "call_type", "user", "team_id", "model", "mcp_namespaced_tool_name", "status")
    dq_sub = next((r for r in reminders), {}).get("created_by")
    time.sleep(5)                                       # let LiteLLM flush its log batch
    _, _, raw = t.http("GET", f"{t.GATEWAY}/spend/logs?user_id={luca_claims['sub']}", t.MASTER_KEY)
    luca_logs = [{k: row.get(k) for k in fields} for row in (t.j(raw) if isinstance(t.j(raw), list) else [])]
    _, _, raw = t.http("GET", f"{t.CRM}/notes", luca)
    notes = t.j(raw)
    trail = audit(luca, writes_only="true", limit=500)[::-1]
    _, _, raw = t.http("GET", f"{t.CRM}/audit/gateway?limit=500", luca)
    gateway_jwts = t.j(raw)
    files = {
        "acts.json": evidence["acts"],
        "litellm-log-luca.json": luca_logs,
        "demo-crm-notes-luca.json": notes,
        "audit-demo-crm.json": trail,
        "audit-gateway-jwts.json": gateway_jwts,
        "demo-crm-reminders-by-agent-dq.json": reminders,
    }
    for name, payload in files.items():
        with open(os.path.join(out, name), "w") as f:
            json.dump(payload, f, indent=2, default=str)
    with open(os.path.join(out, "SUMMARY.md"), "w") as f:
        f.write(f"# Wave 0 demo run {stamp}\n\n**{passed}/{total} checks passed.** "
                f"Luca's sub: `{luca_claims['sub']}`; agent-dq acts as `{dq_sub}`.\n\n")
        for title, data in evidence["acts"].items():
            f.write(f"## {title}\n\n")
            for chk in data["checks"]:
                f.write(f"- {'✅' if chk['passed'] else '❌'} {chk['check']}\n")
            f.write("\n")
        f.write("## Audit trail in demo-crm (changes and refusals)\n\nOne row per call, with the JWT that reached "
                "the API. Full rows, with every claim, in `audit-demo-crm.json`; the JWTs LiteLLM checked are in "
                "`audit-gateway-jwts.json`.\n\n| time | who | action | record | outcome | from | JWT sub · azp · act |\n"
                "| --- | --- | --- | --- | --- | --- | --- |\n")
        for r in trail:
            who = {"person": f"{r['person']} (by hand)", "person via agent": f"{r['person']} through {r['agent']}",
                   "autonomous agent": f"{r['agent']} (autonomous)"}.get(r["actor_type"], "unknown")
            tc = r.get("token_claims") or {}
            jwt_s = f"{tc.get('preferred_username')} · {tc.get('azp')} · {(tc.get('act') or {}).get('client_id', '-')}"
            f.write(f"| {str(r['at'])[11:19]} | {who} | {r['method']} {r['path']} | {r.get('object') or ''} | "
                    f"{r['outcome']} | {r['source']} | {jwt_s} |\n")
        f.write("\n")
        f.write("## LiteLLM log for Luca's sub\n\nEvery row: the person (`user` = Luca's sub) and the agent "
                "(`team_id`). Calls refused before admission (the kill switch) leave no row here.\n\n"
                "| time | call | team (agent) | tool or model | status |\n| --- | --- | --- | --- | --- |\n")
        for row in luca_logs:
            f.write(f"| {row['startTime']} | {row['call_type']} | {row['team_id']} | "
                    f"{row.get('mcp_namespaced_tool_name') or row['model']} | {row.get('status')} |\n")
        f.write("\nFiles: " + ", ".join(f"`{n}`" for n in files) + ".\n")
    print(f"Evidence written to {out}")


if __name__ == "__main__":
    main()
