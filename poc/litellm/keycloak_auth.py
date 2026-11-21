"""Gateway admission with Keycloak tokens on LiteLLM open source.

LiteLLM's built-in JWT auth is an Enterprise feature. This custom_auth hook (open source)
does the same check: it verifies issuer, audience and signature of the Keycloak token,
then hands LiteLLM the person (`sub`) and the client (`azp`, one LiteLLM team per agent).
LiteLLM's own checks still run afterwards (custom_auth_run_common_checks), so a client
without a team, or a blocked team, is refused.

MCP calls carry two Keycloak tokens: the agent's own token in x-litellm-api-key (admission),
and in Authorization the token the MCP server passes on to the app (for a delegated agent, the
token with sub = person and act = agent). LiteLLM forwards Authorization upstream only when it
differs from the admission key (oauth_delegate). This hook verifies both, checks that the
upstream token belongs to the admitted agent, and logs the person.

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

    claims = _verify(api_key)
    agent = claims["azp"]

    # MCP: a second token in Authorization travels upstream. It must belong to the same agent.
    upstream = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if request.headers.get("x-litellm-api-key") and upstream and upstream != api_key:
        up = _verify(upstream)
        up_agent = (up.get("act") or {}).get("client_id") or up["azp"]
        if up_agent != agent:
            raise Exception(f"upstream token belongs to {up_agent}, not to the admitted agent {agent}")
        claims = up                                # log the person the agent acts for

    act = claims.get("act") or {}
    return UserAPIKeyAuth(
        api_key=f"kc:{agent}",                   # never the raw token: it would land in the logs
        token=f"kc:{agent}",
        user_id=claims["sub"],                   # the person (delegated) or the service account (autonomous)
        team_id=agent,                           # one LiteLLM team per Keycloak client
        user_role=LitellmUserRoles.INTERNAL_USER,
        metadata={
            "username": claims.get("preferred_username"),
            "agent": act.get("client_id") or act.get("sub") or claims["azp"],
        },
    )


def _verify(token: str) -> dict:
    if not token or token.count(".") != 2:
        raise Exception("a Keycloak access token is required")
    try:
        key = _jwks.get_signing_key_from_jwt(token).key
        return jwt.decode(token, key, algorithms=["RS256"], audience=AUDIENCE, issuer=ISSUER)
    except jwt.PyJWTError as exc:
        raise Exception(f"invalid token: {exc}") from exc
