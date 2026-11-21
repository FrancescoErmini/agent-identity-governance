"""demo-crm UI: static page plus a same-origin pass-through, so the browser needs no CORS.

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
app = FastAPI(title="demo-crm UI")


@app.api_route("/{target}/{path:path}", methods=["GET", "POST"])
async def forward(target: str, path: str, request: Request):
    if target not in UPSTREAMS:
        return Response(status_code=404)
    headers = {k: v for k, v in request.headers.items() if k.lower() in ("authorization", "content-type")}
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.request(request.method, f"{UPSTREAMS[target]}/{path}", params=request.query_params,
                                 content=await request.body(), headers=headers)
    return Response(r.content, status_code=r.status_code, media_type=r.headers.get("content-type"))


app.mount("/", StaticFiles(directory="static", html=True), name="static")
