"""Audit trail in demo-crm: who did what, with the JWT that came in.

AS-IS: Luca writes a note by hand in the UI -> the audit names Luca, no agent, token from demo-crm.
TO-BE delegated: the assistant drafts a note for Luca -> the audit names Luca through the agent (act claim).
TO-BE autonomous: agent-dq creates reminders -> the audit names the agent, no person.
"""
import sys
import time
import urllib.parse

sys.path.insert(0, "/tests")
import step2_check as t  # noqa: E402  shared helpers

UI = "http://demo-crm-ui:3000"
results: list[bool] = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({str(detail)[:400]})" if detail and not ok else ""))


def audit(token, **query):
    qs = urllib.parse.urlencode(query)
    status, _, raw = t.http("GET", f"{t.CRM}/audit?{qs}", token)
    return status, t.j(raw)


def main():
    print("Audit trail")
    luca = t.browser_login("luca", "openid delegation:client:agent-crm-assistant")
    sub = t.claims(luca)["sub"]
    _, _, raw = t.http("GET", f"{t.CRM}/accounts", luca)
    account = t.j(raw)["accounts"][0]["id"]

    # AS-IS: by hand, through the UI
    status, _, raw = t.http("POST", f"{UI}/api/notes", luca, {"account_id": account, "text": "Written by hand", "status": "final"})
    manual = t.j(raw)
    check("AS-IS: Luca's own note is final, no agent", status == 201 and manual["status"] == "final"
          and manual["via_agent"] is None, (status, manual))
    _, rows = audit(luca, writes_only="true", person="luca")
    row = next((r for r in rows if r["object"] == f"note:{manual.get('id')} (final)"), {})
    tok = row.get("token_claims") or {}
    check("AS-IS audit: person luca, no agent, from the demo-crm UI",
          row.get("actor_type") == "person" and row.get("agent") is None and row.get("source") == "demo-crm UI", row)
    check("AS-IS audit: the JWT that came in is shown, verified, azp demo-crm, no act",
          row.get("token_verified") and tok.get("sub") == sub and tok.get("azp") == "demo-crm" and "act" not in tok
          and (row.get("token_header") or {}).get("kid"), row)

    # TO-BE delegated: the assistant, through LiteLLM and the MCP server
    status, _, raw = t.http("POST", f"{t.ASSISTANT}/assist", luca, {"task": "summary", "account_id": account})
    out = t.j(raw)
    note = next((s["result"] for s in out.get("steps", []) if s.get("tool") == "draft_visit_note" and "result" in s), {})
    _, rows = audit(luca, writes_only="true", agent="agent-crm-assistant")
    row = next((r for r in rows if r["object"] == f"note:{note.get('id')} (draft)"), {})
    tok = row.get("token_claims") or {}
    check("TO-BE delegated audit: person luca through agent-crm-assistant, via the MCP server and LiteLLM",
          row.get("actor_type") == "person via agent" and row.get("person") == "luca"
          and row.get("source") == "MCP server, via LiteLLM", row)
    check("TO-BE delegated audit: the JWT has sub = luca, act = agent, roles reduced to rep",
          row.get("token_verified") and tok.get("sub") == sub
          and (tok.get("act") or {}).get("client_id") == "agent-crm-assistant"
          and tok.get("resource_access", {}).get("demo-crm", {}).get("roles") == ["rep"], tok)
    check("the correlation id links the audit row to the assistant's run",
          row.get("correlation_id") and row.get("correlation_id") == out.get("correlation_id"), (row.get("correlation_id"), out.get("correlation_id")))

    # The same call, at the gateway: two JWTs, decoded by the LiteLLM auth hook
    corr = out.get("correlation_id")
    status, _, raw = t.http("GET", f"{t.CRM}/audit/gateway?correlation_id={corr}", luca)
    seen = next((g for g in (t.j(raw) or []) if g.get("upstream_token")), {})
    adm = (seen.get("admission_token") or {}).get("claims") or {}
    up = (seen.get("upstream_token") or {}).get("claims") or {}
    check("at LiteLLM: admission JWT is the agent's own (azp agent-crm-assistant, no act), check passed",
          seen.get("token_check") == "passed" and adm.get("azp") == "agent-crm-assistant" and "act" not in adm, seen)
    check("at LiteLLM: the JWT forwarded upstream is the same one demo-crm received (same jti)",
          up.get("jti") and up.get("jti") == tok.get("jti"), (up.get("jti"), tok.get("jti")))

    # Bypassing the gateway: the API sees the delegated JWT, the gateway saw nothing
    status, _, raw = t.http("POST", f"{t.ASSISTANT}/assist", luca, {"task": "bypass_gateway", "account_id": account})
    corr = t.j(raw).get("correlation_id")
    _, rows = audit(luca, correlation_id=corr)
    _, _, raw = t.http("GET", f"{t.CRM}/audit/gateway?correlation_id={corr}", luca)
    check("direct call: audited as luca through the agent, from crm-assistant directly, no JWT at the gateway",
          rows and rows[0].get("source") == "crm-assistant, direct" and rows[0].get("actor_type") == "person via agent"
          and t.j(raw) == [], (rows[:1], t.j(raw)))

    # TO-BE autonomous: agent-dq on its own
    t.http("POST", f"{t.DQ}/run?limit=2")
    _, rows = audit(luca, writes_only="true", actor_type="autonomous agent")
    row = next((r for r in rows if r["path"] == "/reminders" and r["status"] == 201), {})
    tok = row.get("token_claims") or {}
    check("TO-BE autonomous audit: agent-dq, no person, its own token (azp agent-dq, no act)",
          row.get("agent") == "agent-dq" and row.get("person") is None and row.get("token_verified")
          and tok.get("azp") == "agent-dq" and "act" not in tok, row)

    # Refusals are audited too, with the reason
    t.http("POST", f"{t.ASSISTANT}/assist", luca, {"task": "team_report", "account_id": account})
    time.sleep(1)
    _, rows = audit(luca, outcome="refused", agent="agent-crm-assistant")
    refused = [r for r in rows if r["path"] == "/reports/team" and r["outcome"] == "refused"]
    check("a refused call is in the audit, with the reason", refused and "area-manager" in (refused[0].get("detail") or ""),
          rows[:2])

    # The audit itself
    other = t.browser_login("giulia", "openid")
    status, _ = audit(other)
    check("only area managers read the audit (giulia: 403)", status == 403, status)
    status, rows = audit(luca, limit=500)
    check("the raw token is never stored", status == 200 and not any("eyJ" in str(r) for r in rows), status)

    print(f"\nAudit: {sum(results)}/{len(results)} checks passed")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
