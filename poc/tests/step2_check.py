"""Step 2 checks: demo acts 1, 2, 3 and 4 end to end, plus delegation without consent.

Runs inside the compose network: docker compose --profile check run --rm check
Standard library only. The browser login (with the consent screen) is scripted over HTTP.
"""
import base64
import hashlib
import html
from http.cookiejar import CookieJar
import json
import os
import re
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

KC = "http://sso.demo.local:8080/realms/ai-demo/protocol/openid-connect"
CRM = "http://demo-crm-api:8080"
ASSISTANT = "http://crm-assistant:8000"
DQ = "http://agent-dq:8000"
GATEWAY = "http://litellm:4000"
MASTER_KEY = os.environ["LITELLM_MASTER_KEY"]
REDIRECT = "http://localhost:3000/"

results: list[tuple[bool, str]] = []


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def http(method, url, token=None, body=None, form=None, opener=None):
    headers, data = {}, None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        data, headers["Content-Type"] = json.dumps(body).encode(), "application/json"
    if form is not None:
        data, headers["Content-Type"] = urllib.parse.urlencode(form).encode(), "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with (opener or urllib.request.build_opener()).open(req, timeout=60) as r:
            raw = r.read()
            return r.status, r.headers, raw
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


def j(raw):
    try:
        return json.loads(raw)
    except ValueError:
        return raw.decode(errors="replace")


def browser_login(username: str, scope: str) -> str:
    """Authorization Code + PKCE as the demo-crm UI does it, accepting the consent screen."""
    jar = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), NoRedirect)
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    url = f"{KC}/auth?" + urllib.parse.urlencode({
        "client_id": "demo-crm", "response_type": "code", "redirect_uri": REDIRECT, "scope": scope,
        "code_challenge": challenge, "code_challenge_method": "S256", "state": "check"})
    form_action = lambda page: urllib.parse.urljoin(KC, html.unescape(re.search(r'<form[^>]*action="([^"]+)"', page).group(1)))
    _, _, page = http("GET", url, opener=opener)
    status, headers, page = http("POST", form_action(page.decode()), form={"username": username, "password": username}, opener=opener)
    location = headers.get("Location", "")
    if "required-action" in location or "login-actions" in location:     # the consent screen
        _, _, page = http("GET", location, opener=opener)
        page = page.decode()
        fields = dict(re.findall(r'<input[^>]*name="(code)"[^>]*value="([^"]*)"', page))
        status, headers, _ = http("POST", form_action(page), form={**fields, "accept": "Yes"}, opener=opener)
        location = headers.get("Location", "")
    code = urllib.parse.parse_qs(urllib.parse.urlparse(location).query).get("code", [None])[0]
    assert code, f"login for {username} did not return a code: {status} {location[:200]}"
    _, _, raw = http("POST", f"{KC}/token", form={"grant_type": "authorization_code", "client_id": "demo-crm",
                                                 "code": code, "redirect_uri": REDIRECT, "code_verifier": verifier})
    return json.loads(raw)["access_token"]


def claims(tok):
    p = tok.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))


def check(name, ok, detail=""):
    results.append((bool(ok), name))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({str(detail)[:300]})" if detail and not ok else ""))


def spend_logs(user_id: str) -> list:
    status, _, raw = http("GET", f"{GATEWAY}/spend/logs?user_id={user_id}", token=MASTER_KEY)
    return j(raw) if status == 200 and isinstance(j(raw), list) else []


def main():
    print("Waiting for the agents...")
    for _ in range(60):
        try:
            if all(http("GET", f"{u}/health")[0] == 200 for u in (CRM, ASSISTANT, DQ)) \
                    and http("GET", f"{GATEWAY}/health/liveliness")[0] == 200:
                break
        except OSError:
            pass
        time.sleep(2)
    else:
        sys.exit("services not reachable: check `docker compose ps`")

    print("\nAct 1 · Luca signs in through Keycloak and sees only his territory")
    luca = browser_login("luca", "openid delegation:client:agent-crm-assistant")
    c = claims(luca)
    check("login with consent puts may_act for agent-crm-assistant in luca's token",
          (c.get("may_act") or {}).get("client_id") == "agent-crm-assistant", c.get("may_act"))
    status, _, raw = http("GET", f"{CRM}/accounts", luca)
    accounts = j(raw).get("accounts", []) if status == 200 else []
    check("demo-crm shows only NORTH accounts", accounts and {a["territory"] for a in accounts} == {"NORTH"}, status)
    account = accounts[0]["id"] if accounts else "ACC-00000"

    print("\nAct 2 · The assistant prepares a visit for Luca and drafts a note")
    status, _, raw = http("POST", f"{ASSISTANT}/assist", luca, {"task": "summary", "account_id": account})
    out = j(raw)
    check("assistant answered", status == 200, (status, out))
    out = out if isinstance(out, dict) else {}
    check("delegated token: sub = luca, act = agent-crm-assistant",
          out.get("acting_for") == "luca" and (out.get("act") or {}).get("client_id") == "agent-crm-assistant", out.get("act"))
    check("delegated token carries rep only (area-manager left behind)",
          out.get("roles_in_delegated_token") == ["rep"], out.get("roles_in_delegated_token"))
    steps = out.get("steps", [])
    check("both tools ran through the gateway", [s.get("tool") for s in steps if "result" in s]
          == ["get_account_summary", "draft_visit_note"], steps)
    note = next((s["result"] for s in steps if s.get("tool") == "draft_visit_note" and "result" in s), {})
    check("note recorded as draft, created_by luca, via_agent agent-crm-assistant",
          note.get("status") == "draft" and note.get("created_by") == "luca"
          and note.get("via_agent") == "agent-crm-assistant", note)
    check("note carries the correlation id of the request", note.get("correlation_id") == out.get("correlation_id"),
          (note.get("correlation_id"), out.get("correlation_id")))
    status, _, raw = http("GET", f"{CRM}/notes", luca)
    check("luca sees the draft in his notes", any(n["id"] == note.get("id") for n in j(raw)) if status == 200 else False)
    logs = []
    for _ in range(15):                               # LiteLLM writes its logs in batches
        logs = [l for l in spend_logs(c["sub"]) if l.get("call_type") == "call_mcp_tool"]
        if len(logs) >= 2:
            break
        time.sleep(2)
    check("LiteLLM log: MCP calls recorded under luca's sub and the assistant's team",
          logs and all(l.get("team_id") == "agent-crm-assistant" for l in logs), [(l.get("user"), l.get("team_id")) for l in logs][:3])

    print("\nAct 3 · Luca is also area manager, but the assistant is not")
    status, _, _ = http("GET", f"{CRM}/reports/team", luca)
    check("luca himself gets the team report", status == 200, status)
    status, _, raw = http("POST", f"{ASSISTANT}/assist", luca, {"task": "team_report"})
    step = (j(raw).get("steps") or [{}])[0] if status == 200 else {}
    check("the same request through the assistant is refused by demo-crm (403)",
          step.get("refused_by") == "demo-crm" and (step.get("error") or {}).get("error") == 403, step)

    print("\nAct 4 · The scheduler starts agent-dq; reminders appear tagged as autonomous")
    status, _, raw = http("POST", f"{DQ}/run?limit=3")
    out = j(raw) if status == 200 else {}
    made = [s["result"] for s in out.get("steps", []) if s.get("tool") == "create_reminder" and "result" in s]
    check("agent-dq acts as itself with role dq-agent only",
          out.get("acting_as") == "agent-dq" and out.get("roles") == ["dq-agent"], out.get("roles"))
    check("reminders created, via_agent agent-dq", made and all(r["via_agent"] == "agent-dq" for r in made), made)
    if made:
        rep = made[0]["rep"]
        rep_token = browser_login(rep, "openid")
        status, _, raw = http("GET", f"{CRM}/reminders", rep_token)
        check(f"{rep} sees the reminder in demo-crm", status == 200 and any(r["id"] == made[0]["id"] for r in j(raw)))
    status, _, _ = http("GET", f"{CRM}/accounts", None)

    print("\nDelegation needs the person's consent")
    giulia = browser_login("giulia", "openid")        # signed in without asking for delegation
    status, _, raw = http("POST", f"{ASSISTANT}/assist", giulia, {"task": "summary", "account_id": "ACC-00001"})
    check("without consent (no may_act) Keycloak refuses the exchange", status == 403, (status, j(raw)))

    failed = [n for ok, n in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
