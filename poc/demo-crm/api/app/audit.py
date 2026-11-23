"""Audit trail: one append-only row per API call, with the JWT that came in.

For every call except /health and the audit reads themselves, demo-crm records who called (person, agent, or
both), from where, what was done and with what outcome, plus the token's header and decoded claims and whether
the signature check passed. The raw token is never stored: it would still be a valid credential until it expires.
"""
import json
import socket
from functools import lru_cache

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from .auth import inspect_token
from .db import conn

SKIP = ("/health", "/audit", "/docs", "/openapi.json")

# Where the call came from, from the network (Docker DNS), not from anything the caller says.
SOURCES = {
    "demo-crm-ui": "demo-crm UI",
    "demo-crm-mcp": "MCP server, via LiteLLM",
    "crm-assistant": "crm-assistant, direct",
    "agent-dq": "agent-dq, direct",
    "check-run": "test script",
}


@lru_cache(maxsize=64)
def _source(ip: str) -> str:
    try:
        host = socket.gethostbyaddr(ip)[0]
    except OSError:
        return f"other ({ip})"
    for service, label in SOURCES.items():
        if f"-{service}-" in host or host.startswith(service):
            return label
    return f"other ({host.split('.')[0]})"


def actor(claims: dict | None) -> dict:
    """Person, agent, or person through an agent, read from the token."""
    if not claims:
        return {"actor_type": "unknown", "person": None, "person_sub": None, "agent": None}
    act = claims.get("act") or {}
    azp = claims.get("azp", "")
    if act:
        return {"actor_type": "person via agent", "person": claims.get("preferred_username"),
                "person_sub": claims.get("sub"), "agent": act.get("client_id") or act.get("sub")}
    if azp.startswith("agent-"):
        return {"actor_type": "autonomous agent", "person": None, "person_sub": None, "agent": azp}
    return {"actor_type": "person", "person": claims.get("preferred_username"),
            "person_sub": claims.get("sub"), "agent": None}


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith(SKIP):
            return await call_next(request)
        request.scope["audit"] = {}          # handlers add the object they touched
        response = await call_next(request)
        detail = None
        if response.status_code >= 400:      # keep the refusal reason, then hand the body back unchanged
            body = b"".join([chunk async for chunk in response.body_iterator])
            try:
                detail = json.loads(body).get("detail")
            except (ValueError, AttributeError):
                detail = body[:300].decode(errors="replace")
            response = Response(body, status_code=response.status_code, headers=dict(response.headers))
        try:
            _record(request, response.status_code, detail)
        except Exception as exc:  # the audit must never break the call it describes
            print(f"audit write failed: {exc}", flush=True)
        return response


def _record(request: Request, status: int, detail) -> None:
    auth = request.headers.get("authorization", "")
    token = auth[7:] if auth.lower().startswith("bearer ") else None
    tok = inspect_token(token) if token else {"header": None, "claims": None, "verified": False,
                                              "error": "no bearer token"}
    who = actor(tok["claims"])
    outcome = "allowed" if status < 400 else "refused" if status in (401, 403, 404) else "error"
    if isinstance(detail, (dict, list)):
        detail = json.dumps(detail)
    with conn() as c:
        c.execute(
            "INSERT INTO audit_events (method, path, status, outcome, detail, actor_type, person, person_sub, agent,"
            " source, correlation_id, object, token_header, token_claims, token_verified, token_error)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (request.method, request.url.path, status, outcome, detail, who["actor_type"], who["person"],
             who["person_sub"], who["agent"], _source(request.client.host if request.client else ""),
             request.headers.get("x-correlation-id"), request.scope.get("audit", {}).get("object"),
             json.dumps(tok["header"]) if tok["header"] else None,
             json.dumps(tok["claims"]) if tok["claims"] else None, tok["verified"], tok["error"]),
        )


def mark(request: Request, obj: str) -> None:
    """Name the record a call created or changed, e.g. note:42."""
    request.scope.setdefault("audit", {})["object"] = obj
