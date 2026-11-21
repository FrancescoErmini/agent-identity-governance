"""What every agent shares: its own key pair, its Keycloak identity, and the gateway.

No secret is stored or committed. The agent creates an RSA key pair when it starts, publishes
the public half on /jwks, and proves who it is to Keycloak with a signed client assertion
(private_key_jwt). A restart rotates the key.
"""
import asyncio
import json
import os
import time
import uuid
from contextlib import asynccontextmanager

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

ISSUER = os.environ.get("OIDC_ISSUER", "http://sso.demo.local:8080/realms/ai-demo")
TOKEN_URL = f"{ISSUER}/protocol/openid-connect/token"
GATEWAY = os.environ.get("LITELLM_URL", "http://litellm:4000")
MCP_URL = f"{GATEWAY}/demo_crm/mcp"
TOKEN_EXCHANGE = "urn:ietf:params:oauth:grant-type:token-exchange"
ACCESS_TOKEN = "urn:ietf:params:oauth:token-type:access_token"


class AgentIdentity:
    def __init__(self, client_id: str):
        self.client_id = client_id
        self._key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.kid = str(uuid.uuid4())

    def jwks(self) -> dict:
        public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self._key.public_key()))
        return {"keys": [{**public, "kid": self.kid, "use": "sig", "alg": "RS256"}]}

    def _assertion(self) -> dict:
        now = int(time.time())
        signed = jwt.encode({"iss": self.client_id, "sub": self.client_id, "aud": ISSUER,
                             "jti": str(uuid.uuid4()), "iat": now, "exp": now + 60},
                            self._key, algorithm="RS256", headers={"kid": self.kid})
        return {"client_id": self.client_id, "client_assertion": signed,
                "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"}

    async def _token(self, form: dict) -> str:
        for attempt in range(5):          # after an agent restart Keycloak may still hold its old address
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post(TOKEN_URL, data={**form, **self._assertion()})
            if r.status_code == 200 or "invalid_client" not in r.text or attempt == 4:
                break
            await asyncio.sleep(3)
        if r.status_code != 200:
            raise PermissionError(f"Keycloak refused ({r.status_code}): {r.text[:300]}")
        return r.json()["access_token"]

    async def own_token(self) -> str:
        """The agent's own token (client credentials): autonomous work, and the actor in delegation."""
        return await self._token({"grant_type": "client_credentials"})

    async def delegated_token(self, user_token: str) -> str:
        """Exchange the person's token for one where sub = the person and act = this agent."""
        return await self._token({
            "grant_type": TOKEN_EXCHANGE,
            "subject_token": user_token, "subject_token_type": ACCESS_TOKEN,
            "actor_token": await self.own_token(), "actor_token_type": ACCESS_TOKEN,
        })


def claims(token: str) -> dict:
    """Readable claims for display only. Verification is the job of LiteLLM and demo-crm."""
    return jwt.decode(token, options={"verify_signature": False})


@asynccontextmanager
async def tools_session(admission_token: str, upstream_token: str, correlation_id: str):
    """MCP session through the gateway, with two Keycloak tokens.

    admission_token (x-litellm-api-key): the agent's own token; LiteLLM admits the agent with it.
    upstream_token (Authorization): what demo-crm receives through the MCP server. For a
    delegated agent, sub = the person and act = the agent. LiteLLM forwards it only if it
    differs from the admission token, so an autonomous agent uses a second token of its own.
    """
    headers = {"x-litellm-api-key": admission_token, "Authorization": f"Bearer {upstream_token}",
               "x-correlation-id": correlation_id}
    async with streamablehttp_client(MCP_URL, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


async def call_tool(session: ClientSession, name: str, args: dict) -> dict:
    """Call one tool and return a plain result, including the gateway's refusals."""
    try:
        result = await session.call_tool(name, args)
    except Exception as exc:                                   # noqa: BLE001  refusal is a demo outcome
        return {"tool": name, "args": args, "refused_by": "gateway", "error": str(exc)}
    text = "".join(getattr(c, "text", "") for c in result.content)
    try:
        payload = json.loads(text)
    except ValueError:
        payload = text
    if result.isError:
        return {"tool": name, "args": args, "refused_by": "gateway", "error": payload}
    if isinstance(payload, dict) and "error" in payload and "detail" in payload:
        return {"tool": name, "args": args, "refused_by": "demo-crm", "error": payload}
    return {"tool": name, "args": args, "result": payload}


async def chat(token: str, correlation_id: str, model: str, messages: list, tools: list | None = None) -> dict:
    """Model call through the gateway with the same token."""
    body = {"model": model, "messages": messages, "max_tokens": 800}
    if tools:
        body["tools"] = tools
    async with httpx.AsyncClient(timeout=90) as client:
        r = await client.post(f"{GATEWAY}/v1/chat/completions", json=body,
                              headers={"Authorization": f"Bearer {token}", "x-correlation-id": correlation_id})
    if r.status_code != 200:
        raise RuntimeError(f"model call refused or failed at the gateway ({r.status_code}): {r.text[:300]}")
    return r.json()["choices"][0]["message"]
