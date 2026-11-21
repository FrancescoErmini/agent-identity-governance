"""Gateway admission with Keycloak tokens on LiteLLM open source.

LiteLLM's built-in JWT auth is an Enterprise feature. This custom_auth hook (open source)
does the same check: it verifies issuer, audience and signature of the Keycloak token,
then hands LiteLLM the person (`sub`) and the client (`azp`, one LiteLLM team per agent).
LiteLLM's own checks still run afterwards (custom_auth_run_common_checks), so a client
without a team, or a blocked team, is refused.

With the Enterprise licence, remove `custom_auth` from config.yaml and use enable_jwt_auth.
"""
import os

import jwt  # PyJWT, shipped with LiteLLM
from fastapi import Request
from litellm.proxy._types import LitellmUserRoles, UserAPIKeyAuth

ISSUER = os.environ.get("OIDC_ISSUER", "http://sso.demo.local:8080/realms/ai-demo")
AUDIENCE = os.environ.get("OIDC_AUDIENCE", "litellm-proxy")
MASTER_KEY = os.environ["LITELLM_MASTER_KEY"]

_jwks = jwt.PyJWKClient(f"{ISSUER}/protocol/openid-connect/certs", cache_keys=True, lifespan=300)


async def user_api_key_auth(request: Request, api_key: str) -> UserAPIKeyAuth:
    # Operators only (team setup, kill switch). Agents and people never hold it.
    if api_key == MASTER_KEY:
        return UserAPIKeyAuth(api_key=api_key, user_id="litellm-admin", user_role=LitellmUserRoles.PROXY_ADMIN)

    if not api_key or api_key.count(".") != 2:
        raise Exception("a Keycloak access token is required")
    try:
        key = _jwks.get_signing_key_from_jwt(api_key).key
        claims = jwt.decode(api_key, key, algorithms=["RS256"], audience=AUDIENCE, issuer=ISSUER)
    except jwt.PyJWTError as exc:
        raise Exception(f"invalid token: {exc}") from exc

    act = claims.get("act") or {}
    return UserAPIKeyAuth(
        api_key=f"kc:{claims['azp']}",            # never the raw token: it would land in the logs
        token=f"kc:{claims['azp']}",
        user_id=claims["sub"],                   # the person (delegated) or the service account (autonomous)
        team_id=claims["azp"],                   # one LiteLLM team per Keycloak client
        user_role=LitellmUserRoles.INTERNAL_USER,
        metadata={
            "username": claims.get("preferred_username"),
            "agent": act.get("client_id") or act.get("sub") or claims["azp"],
        },
    )
