"""MCP server for demo-crm: six narrow tools, no free queries.

It holds no credentials of its own. Each tool passes on the bearer that LiteLLM forwards
(oauth_delegate), so demo-crm sees the person and the agent and applies its own roles.
"""
import os

import httpx
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings

API = os.environ.get("DEMO_CRM_API", "http://demo-crm-api:8080")

mcp = FastMCP(
    "demo-crm",
    host="0.0.0.0",
    port=8000,
    stateless_http=True,
    transport_security=TransportSecuritySettings(allowed_hosts=["demo-crm-mcp:8000", "localhost:8000"]),
)


def _headers(ctx: Context) -> dict:
    req = ctx.request_context.request                     # the HTTP request from LiteLLM
    auth = req.headers.get("authorization")
    if not auth:
        raise ValueError("no bearer forwarded by the gateway")
    headers = {"authorization": auth}
    if cid := req.headers.get("x-correlation-id"):
        headers["x-correlation-id"] = cid
    return headers


async def _call(ctx: Context, method: str, path: str, **kw) -> dict:
    async with httpx.AsyncClient(base_url=API, timeout=20) as client:
        r = await client.request(method, path, headers=_headers(ctx), **kw)
    if r.status_code >= 400:
        # demo-crm's own refusal goes back to the agent unchanged: it is part of the demo
        return {"error": r.status_code, "detail": r.json().get("detail", r.text)}
    data = r.json()
    return {"items": data} if isinstance(data, list) else data    # one JSON object per tool result


# --- tools for the delegated assistant (acts for a sales rep) --------------------------------
@mcp.tool()
async def search_accounts(query: str = "", ctx: Context = None) -> dict:
    """Search accounts (doctors) in the caller's territory by name or city."""
    return await _call(ctx, "GET", "/accounts", params={"q": query, "limit": 10})


@mcp.tool()
async def get_account_summary(account_id: str, ctx: Context = None) -> dict:
    """Account details and its ten most recent visits."""
    return await _call(ctx, "GET", f"/accounts/{account_id}")


@mcp.tool()
async def list_visits(account_id: str, ctx: Context = None) -> dict:
    """Recent visits to one account."""
    acc = await _call(ctx, "GET", f"/accounts/{account_id}")
    return {"account_id": account_id, "visits": acc.get("visits", [])} if "error" not in acc else acc


@mcp.tool()
async def draft_visit_note(account_id: str, text: str, status: str = "draft", ctx: Context = None) -> dict:
    """Save a visit note as a draft; the rep confirms it in the demo-crm UI."""
    return await _call(ctx, "POST", "/notes", json={"account_id": account_id, "text": text, "status": status})


@mcp.tool()
async def get_team_report(ctx: Context = None) -> dict:
    """Visits per rep across the area. demo-crm allows it to area managers only."""
    return await _call(ctx, "GET", "/reports/team")


# --- tools for the autonomous data-quality agent --------------------------------------------
@mcp.tool()
async def list_incomplete_visits(limit: int = 20, ctx: Context = None) -> dict:
    """Visits with a missing outcome or next step."""
    return await _call(ctx, "GET", "/dq/incomplete-visits", params={"limit": limit})


@mcp.tool()
async def create_reminder(visit_id: str, text: str, ctx: Context = None) -> dict:
    """Ask the visit's rep to complete it. The reminder shows in the rep's UI."""
    return await _call(ctx, "POST", "/reminders", json={"visit_id": visit_id, "text": text})


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
