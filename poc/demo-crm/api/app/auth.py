"""demo-crm trusts only Keycloak: issuer, audience and signature, then its own roles."""
import os

import jwt  # PyJWT
from fastapi import HTTPException, Request

ISSUER = os.environ.get("OIDC_ISSUER", "http://sso.demo.local:8080/realms/ai-demo")
AUDIENCE = os.environ.get("OIDC_AUDIENCE", "demo-crm")
CLIENT_ID = "demo-crm"

_jwks = jwt.PyJWKClient(f"{ISSUER}/protocol/openid-connect/certs", cache_keys=True)


def caller(request: Request) -> dict:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(401, "missing bearer token")
    token = header[7:]
    try:
        key = _jwks.get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=["RS256"], audience=AUDIENCE, issuer=ISSUER)
    except jwt.PyJWTError as exc:
        raise HTTPException(401, f"invalid token: {exc}") from exc

    act = claims.get("act") or {}
    azp = claims.get("azp", "")
    return {
        "sub": claims["sub"],
        "user": claims.get("preferred_username", claims["sub"]),
        "roles": claims.get("resource_access", {}).get(CLIENT_ID, {}).get("roles", []),
        "territory": claims.get("territory"),
        # Delegated call: act.client_id names the agent. Autonomous call: the agent is the azp.
        "agent": act.get("client_id") or act.get("sub") or (azp if azp.startswith("agent-") else None),
        "correlation_id": request.headers.get("x-correlation-id"),
    }


def require_role(who: dict, role: str) -> None:
    if role not in who["roles"]:
        raise HTTPException(403, f"role {role} required")
