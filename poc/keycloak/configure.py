"""Keycloak settings the realm import can't hold. Idempotent: runs on every `docker compose up`.

- scope crm:ai: what an agent may carry towards demo-crm (two audiences, rep role only, territory)
- agent clients: no secrets; each agent signs its own client assertion and Keycloak reads its
  public key from the agent's JWKS URL (private_key_jwt)
- delegation (Keycloak 26.8 preview): agent-crm-assistant may act for users who consent to it
Standard library only.
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

KC = "http://sso.demo.local:8080"
REALM = "ai-demo"
A = f"{KC}/admin/realms/{REALM}"


def _token() -> str:
    data = urllib.parse.urlencode({"grant_type": "password", "client_id": "admin-cli", "username": "admin",
                                   "password": os.environ["KC_ADMIN_PASSWORD"]}).encode()
    with urllib.request.urlopen(f"{KC}/realms/master/protocol/openid-connect/token", data) as r:
        return json.load(r)["access_token"]


TOKEN = _token()


def api(method: str, path: str, body=None, ok=(200, 201, 204)):
    req = urllib.request.Request(A + path, method=method, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        if e.code in ok or e.code == 409:          # 409: already there
            return None
        raise SystemExit(f"{method} {path}: {e.code} {e.read().decode()[:300]}")


def client_id(client: str) -> str | None:
    found = api("GET", f"/clients?clientId={urllib.parse.quote(client)}")
    return found[0]["id"] if found else None


def scope_id(name: str) -> str | None:
    return next((s["id"] for s in api("GET", "/client-scopes") if s["name"] == name), None)


def audience(name: str, client: str) -> dict:
    return {"name": name, "protocol": "openid-connect", "protocolMapper": "oidc-audience-mapper",
            "config": {"included.client.audience": client, "access.token.claim": "true",
                       "id.token.claim": "false", "introspection.token.claim": "true"}}


TERRITORY = {"name": "territory", "protocol": "openid-connect", "protocolMapper": "oidc-usermodel-attribute-mapper",
             "config": {"user.attribute": "territory", "claim.name": "territory", "jsonType.label": "String",
                        "access.token.claim": "true", "id.token.claim": "false", "introspection.token.claim": "true"}}

# --- agent scopes ----------------------------------------------------------------------------
# A scope with a role scope mapping is put in a token only if the subject holds one of its roles.
# So each kind of agent gets its own scope: crm:ai for the delegated rep role, crm:dq for the
# autonomous agent's role.
CRM = client_id("demo-crm")


def agent_scope(name: str, role: str, description: str, mappers: list) -> str:
    if not scope_id(name):
        api("POST", "/client-scopes", {
            "name": name, "protocol": "openid-connect", "description": description,
            "attributes": {"include.in.token.scope": "true", "display.on.consent.screen": "false"},
            "protocolMappers": [audience("aud-demo-crm", "demo-crm"),
                                audience("aud-litellm-proxy", "litellm-proxy"), *mappers]})
        print(f"created client scope {name}")
    sid = scope_id(name)
    api("POST", f"/client-scopes/{sid}/scope-mappings/clients/{CRM}", [api("GET", f"/clients/{CRM}/roles/{role}")])
    print(f"{name} -> demo-crm role {role} only")
    return sid


DQ_ROLE = "dq-agent"
api("POST", f"/clients/{CRM}/roles", {"name": DQ_ROLE, "description": "Autonomous data-quality agent: reminders only"})
# Every agent's own token must be admitted by the gateway, whatever roles it holds.
if not scope_id("gateway"):
    api("POST", "/client-scopes", {
        "name": "gateway", "protocol": "openid-connect", "description": "Audience litellm-proxy: admission at the gateway",
        "attributes": {"include.in.token.scope": "false", "display.on.consent.screen": "false"},
        "protocolMappers": [audience("aud-litellm-proxy", "litellm-proxy")]})
    print("created client scope gateway")

SCOPES = {
    "gateway": scope_id("gateway"),
    "crm:ai": agent_scope("crm:ai", "rep", "What an AI agent may use on demo-crm for a rep: rep role only",
                          [TERRITORY]),
    "crm:dq": agent_scope("crm:dq", DQ_ROLE, "What the autonomous data-quality agent may use on demo-crm", []),
}

# --- agent clients -------------------------------------------------------------------------
AGENTS = {
    # delegated: acts for a person, only after the person consents
    "agent-crm-assistant": {"jwks": "http://crm-assistant:8000/jwks", "exchange": True,
                            "scope": "crm:ai", "role": "rep"},
    # autonomous: its own identity, its own role
    "agent-dq": {"jwks": "http://agent-dq:8000/jwks", "exchange": False, "scope": "crm:dq", "role": DQ_ROLE},
}

for name, a in AGENTS.items():
    if not client_id(name):
        api("POST", "/clients", {
            "clientId": name, "publicClient": False, "serviceAccountsEnabled": True,
            "standardFlowEnabled": False, "directAccessGrantsEnabled": False, "fullScopeAllowed": False,
            "clientAuthenticatorType": "client-jwt",           # private_key_jwt: no shared secret
            "attributes": {"use.jwks.url": "true", "jwks.url": a["jwks"],
                           "token.endpoint.auth.signing.alg": "RS256",
                           "standard.token.exchange.enabled": str(a["exchange"]).lower()}})
        print(f"created client {name}")
    cid = client_id(name)
    api("PUT", f"/clients/{cid}/default-client-scopes/{SCOPES[a['scope']]}")
    api("PUT", f"/clients/{cid}/default-client-scopes/{SCOPES['gateway']}")
    role = api("GET", f"/clients/{CRM}/roles/{a['role']}")
    api("POST", f"/clients/{cid}/scope-mappings/clients/{CRM}", [role])
    if not a["exchange"]:                                  # the autonomous agent holds its role itself
        sa = api("GET", f"/clients/{cid}/service-account-user")
        api("POST", f"/users/{sa['id']}/role-mappings/clients/{CRM}", [role])

# --- delegation (Keycloak 26.8 preview) ----------------------------------------------------
realm = api("GET", "")
if not realm.get("adminPermissionsEnabled"):
    realm["adminPermissionsEnabled"] = True                 # fine-grained admin permissions v2
    api("PUT", "", realm)
crm = api("GET", f"/clients/{CRM}")
if not crm.get("consentRequired"):
    crm["consentRequired"] = True                           # the person approves each delegation
    api("PUT", f"/clients/{CRM}", crm)
api("PUT", f"/clients/{CRM}/optional-client-scopes/{scope_id('delegation:client')}")

RS = f"/clients/{client_id('admin-permissions')}/authz/resource-server"
assistant = client_id("agent-crm-assistant")
if not api("GET", f"{RS}/policy?name=is-agent-crm-assistant"):
    api("POST", f"{RS}/policy/client", {"name": "is-agent-crm-assistant", "clients": [assistant], "logic": "POSITIVE"})
policy = api("GET", f"{RS}/policy?name=is-agent-crm-assistant")[0]["id"]
if not api("GET", f"{RS}/permission?name=agent-crm-assistant-may-delegate"):
    api("POST", f"{RS}/permission/scope", {
        "name": "agent-crm-assistant-may-delegate", "resourceType": "Users", "scopes": ["delegate"],
        "policies": [policy], "decisionStrategy": "UNANIMOUS"})
print("agent-crm-assistant may act for users who consent")
print("keycloak configured")
