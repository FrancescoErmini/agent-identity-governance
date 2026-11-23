"""The three web apps of the demo, one image: static pages plus a same-origin pass-through (no CORS).

APP picks the app: crm (demo-crm, :3000), assistant (AI assistant, :3001) or audit (audit console, :3002).
It holds no credentials: the browser's own Keycloak token goes through unchanged.
"""
import os

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles

UPSTREAMS = {
    "api": os.environ.get("DEMO_CRM_API", "http://demo-crm-api:8080"),
    "assistant": os.environ.get("CRM_ASSISTANT", "http://crm-assistant:8000"),
    "scheduler": os.environ.get("AGENT_DQ", "http://agent-dq:8000"),    # stands in for the nightly scheduler
}
APP = os.environ.get("APP", "crm")
app = FastAPI(title=f"demo-crm web: {APP}")


async def forward(target: str, path: str, request: Request):
    headers = {k: v for k, v in request.headers.items() if k.lower() in ("authorization", "content-type")}
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.request(request.method, f"{UPSTREAMS[target]}/{path}", params=request.query_params,
                                 content=await request.body(), headers=headers)
    return Response(r.content, status_code=r.status_code, media_type=r.headers.get("content-type"))


def _route_for(target: str):
    async def route(path: str, request: Request):
        return await forward(target, path, request)
    return route


for _target in UPSTREAMS:                       # /api/..., /assistant/..., /scheduler/...
    app.add_api_route(f"/{_target}/{{path:path}}", _route_for(_target), methods=["GET", "POST"])


app.mount("/shared", StaticFiles(directory="static/shared"), name="shared")
app.mount("/", StaticFiles(directory=f"static/{APP}", html=True), name="static")
