"""Step 1 checks: Keycloak tokens accepted by demo-crm and by the gateway, wrong ones refused.

Runs inside the compose network: docker compose --profile check run --rm check
Standard library only, so it needs no image build.
"""
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

KC = "http://sso.demo.local:8080/realms/ai-demo/protocol/openid-connect/token"
CRM = "http://demo-crm-api:8080"
GATEWAY = "http://litellm:4000"
MASTER_KEY = os.environ["LITELLM_MASTER_KEY"]

results: list[tuple[bool, str]] = []


def http(method, url, token=None, body=None, headers=None, form=None):
    hdrs = dict(headers or {})
    data = None
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    if body is not None:
        data = json.dumps(body).encode()
        hdrs["Content-Type"] = "application/json"
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        hdrs["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw.decode(errors="replace")


def token(client_id, username):
    status, body = http("POST", KC, form={
        "grant_type": "password", "client_id": client_id,
        "username": username, "password": username, "scope": "openid",
    })
    assert status == 200, f"token for {username} via {client_id}: {status} {body}"
    return body["access_token"]


def claims(tok):
    payload = tok.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


def check(name, ok, detail=""):
    results.append((bool(ok), name))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))


def main():
    print("Waiting for demo-crm and the gateway...")
    for _ in range(60):
        try:
            if http("GET", f"{CRM}/health")[0] == 200 and http("GET", f"{GATEWAY}/v1/models")[0] == 401:
                break
        except OSError:
            pass
        time.sleep(2)
    else:
        sys.exit("demo-crm or the gateway is not reachable: check `docker compose ps`")

    luca = token("demo-cli", "luca")
    c = claims(luca)
    other = token("other-app", "luca")
    print(f"\nToken for luca: sub={c['sub']} aud={c.get('aud')} territory={c.get('territory')} "
          f"roles={c.get('resource_access', {}).get('demo-crm', {}).get('roles')}")

    print("\nKeycloak")
    aud = c.get("aud") if isinstance(c.get("aud"), list) else [c.get("aud")]
    check("token audience includes demo-crm and litellm-proxy", {"demo-crm", "litellm-proxy"} <= set(aud), aud)
    check("token carries territory NORTH", c.get("territory") == "NORTH", c.get("territory"))
    check("token carries demo-crm roles rep and area-manager",
          {"rep", "area-manager"} <= set(c.get("resource_access", {}).get("demo-crm", {}).get("roles", [])))

    print("\ndemo-crm API")
    s, b = http("GET", f"{CRM}/me", luca)
    check("valid token accepted, caller is luca", s == 200 and b["user"] == "luca", (s, b))
    s, b = http("GET", f"{CRM}/accounts", luca)
    terr = {a["territory"] for a in b["accounts"]} if s == 200 else None
    check("accounts limited to luca's territory", s == 200 and terr == {"NORTH"}, (s, terr))
    s, b = http("GET", f"{CRM}/accounts/ACC-00001", luca)
    check("account from another territory is hidden", s == 404, s)
    s, b = http("GET", f"{CRM}/me", other)
    check("token for another app refused (401)", s == 401, (s, b))
    s, b = http("GET", f"{CRM}/me")
    check("no token refused (401)", s == 401, s)
    head, payload, sig = luca.split(".")
    forged = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    forged["territory"] = "SOUTH"
    forged_payload = base64.urlsafe_b64encode(json.dumps(forged).encode()).decode().rstrip("=")
    s, b = http("GET", f"{CRM}/me", f"{head}.{forged_payload}.{sig}")
    check("tampered token refused (401)", s == 401, s)
    s, b = http("POST", f"{CRM}/notes", luca, {"account_id": "ACC-00000", "text": "Step 1 check", "status": "final"})
    check("person writes a final note, recorded with created_by and no agent",
          s == 201 and b["status"] == "final" and b["created_by"] == "luca" and b["via_agent"] is None, (s, b))

    print("\nGateway (LiteLLM verifies the Keycloak token)")
    s, b = http("GET", f"{GATEWAY}/v1/models", luca)
    check("valid token accepted by the gateway", s == 200, (s, b))
    s, b = http("GET", f"{GATEWAY}/v1/models", other)
    check("token with wrong audience refused (401/403)", s in (401, 403), s)
    s, b = http("GET", f"{GATEWAY}/v1/models")
    check("no token refused (401)", s == 401, s)
    s, b = http("GET", f"{GATEWAY}/v1/models", f"{head}.{forged_payload}.{sig}")
    check("tampered token refused", s in (401, 403), s)
    s, b = http("GET", f"{GATEWAY}/v1/models", token("other-app", "giulia"))
    check("valid token from a client without a LiteLLM team refused", s in (401, 403, 404), s)

    marker = f"step1-{uuid.uuid4()}"
    s, b = http("POST", f"{GATEWAY}/v1/chat/completions", luca,
                {"model": "demo-mock", "messages": [{"role": "user", "content": marker}]})
    check("chat completion through the gateway (demo-mock model, no provider call)", s == 200, (s, b))
    found = None
    for _ in range(15):
        time.sleep(2)
        s2, logs = http("GET", f"{GATEWAY}/spend/logs?user_id={c['sub']}",
                        headers={"Authorization": f"Bearer {MASTER_KEY}"})
        if s2 == 200 and isinstance(logs, list):
            found = next((l for l in logs if l.get("model_group") == "demo-mock" or "demo-mock" in str(l.get("model"))), None)
            if found:
                break
    check("LiteLLM log records the call under luca's sub and his client's team",
          found is not None and found.get("user") == c["sub"] and found.get("team_id") == "demo-cli",
          (found or {}).get("user") if found else "no log entry")
    if found:
        print(f"        log entry: user={found.get('user')} team_id={found.get('team_id')} model={found.get('model')}")

    failed = [n for ok, n in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
