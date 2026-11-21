# Wave 0 POC: Foundation MVP

A working version of *Wave 0 — Foundation MVP* from the [architecture report](../docs/architecture-report.md):
people and AI agents reach one custom app (`demo-crm`) through Keycloak and LiteLLM, on synthetic data.

It is built in steps. Each step ends with a check script that passes from a clean `docker compose up`.

| Step | What it adds | Check |
| --- | --- | --- |
| **1 · Stack and identity** ✓ | Keycloak realm, LiteLLM gateway that verifies Keycloak tokens, demo-crm API with synthetic data | `tests/step1_check.py`: 17 checks |
| **2 · Agents** ✓ | MCP server, UI with “via agent” badges, `agent-dq`, `crm-assistant` with token exchange | `tests/step2_check.py`: acts 1–4, 16 checks |
| 3 · Controls | Tool permissions, “draft only” guardrail, direct-call test, kill switch | All seven acts |
| 4 · Demo pack | Demo script, evidence | — |

## Run it

You need Docker Desktop or OrbStack. On a Mac, Apple Silicon is fine: every image is multi-arch.

```bash
cd poc
cp .env.example .env              # then set the passwords and the master key
docker compose up -d --build      # about 1 minute the first time
docker compose --profile check run --rm check
```

The last command should end with `17/17 checks passed` and `16/16 checks passed`.

To use the UI, add this line to `/etc/hosts` once (`sudo nano /etc/hosts` on a Mac). Tokens are
issued for `sso.demo.local`, so the name must match inside and outside Docker:

```
127.0.0.1 sso.demo.local
```

Then open **http://localhost:3000** (use `localhost`: the browser allows the PKCE login only on a
secure origin, and `localhost` counts as one). Sign in as `luca` / `luca`. Keycloak asks
“Allow agent-crm-assistant to act on your behalf?”: that consent is what lets the assistant work for you.

| Service | URL | Login |
| --- | --- | --- |
| **demo-crm UI** | http://localhost:3000 | `luca` / `luca` (or `giulia`, `marco`) |
| Keycloak admin | http://sso.demo.local:8080 | `admin` / `KC_ADMIN_PASSWORD` |
| LiteLLM gateway | http://localhost:4000 | a Keycloak token, or the master key for admin |
| demo-crm API | http://localhost:8081/docs | a Keycloak token |

Without a model the assistant runs a fixed plan (*scripted mode*): every identity and permission
flow is the same, only the note text is a template. To use a model, set in `.env` either
`LLM_MODEL=gpt` and `OPENAI_API_KEY`, or `LLM_MODEL=claude-sonnet` and `ANTHROPIC_API_KEY`, then
`docker compose up -d`. The key stays in LiteLLM; the assistant reaches the model only through the
gateway, with the delegated token. The OpenAI model is set in `litellm/config.yaml` (`gpt-4.1-mini`).

To start again from nothing: `docker compose down -v`.

## What is in it

| Service | Role |
| --- | --- |
| `keycloak` | Realm `ai-demo` (imported from `keycloak/realm-ai-demo.json`), synthetic users, client roles `rep` and `area-manager` |
| `keycloak-config` | One-shot `keycloak/configure.py`: agent scopes, agent clients, delegation permission |
| `litellm` | Gateway. Verifies the Keycloak token, admits a client only if it has a LiteLLM team, logs every call with the person's `sub` and the client's team |
| `litellm-setup` | One-shot: one LiteLLM team per Keycloak client |
| `demo-crm-api` | The target app. Trusts only Keycloak, applies its own roles, records `created_by`, `via_agent` and the correlation id |
| `demo-crm-ui` | Where every flow ends: accounts, assistant, notes with “via agent” badges, reminders |
| `demo-crm-mcp` | MCP server, seven narrow tools; passes on the bearer LiteLLM forwards |
| `crm-assistant` | Delegated agent: exchanges the rep's token (sub = rep, act = agent), then tools through LiteLLM |
| `agent-dq` | Autonomous agent: its own token, role `dq-agent`, creates reminders. `POST /run` stands in for the nightly scheduler |
| `pg-*`, `redis` | Databases |

Synthetic users (dev only, password = username):

| User | Territory | Roles |
| --- | --- | --- |
| `luca` | NORTH | rep, area-manager |
| `giulia` | CENTRE | rep |
| `marco` | SOUTH | rep |

## How the agents prove who they are

- **No secrets anywhere.** Each agent creates an RSA key pair when it starts and publishes the public
  half on `/jwks`. Keycloak reads it from there and the agent signs a client assertion
  (`private_key_jwt`). A restart rotates the key.
- **Delegation (Keycloak 26.8 preview).** The UI login asks for scope
  `delegation:client:agent-crm-assistant`; Luca consents and his token gets `may_act`. The assistant
  exchanges it (its own token as `actor_token`) for one with `sub` = Luca and `act` = the assistant.
  Keycloak keeps only the roles that both Luca and the assistant's scope `crm:ai` allow: `rep`, never
  `area-manager`. Without consent the exchange is refused. The permission behind it is a fine-grained
  admin permission (`delegate` on Users) for the assistant client.
- **Two tokens on MCP calls.** `x-litellm-api-key` carries the agent's own token (LiteLLM admits the
  agent); `Authorization` carries the token that reaches demo-crm (the delegated one, for the
  assistant). LiteLLM forwards `Authorization` only when it differs from the admission key. The
  gateway hook checks both and that the second belongs to the same agent, then logs the person.
- **One scope per kind of agent.** Keycloak puts a scope with a role mapping in a token only if the
  subject holds that role, so `crm:ai` (role `rep`) serves the delegated assistant, `crm:dq` (role
  `dq-agent`) the autonomous agent, and `gateway` gives every agent the gateway audience.

## Differences from the report, and why

- **LiteLLM runs open source, without the Enterprise licence.** LiteLLM's built-in JWT auth is
  Enterprise only. The same check is done by a small `custom_auth` hook, `litellm/keycloak_auth.py`
  (open source): it verifies issuer, audience and signature, then passes LiteLLM the person (`sub`) and
  the client (`azp`, one team per agent). LiteLLM's team checks still run after it, and the MCP endpoint
  uses the same hook. With the Enterprise trial, remove `custom_auth` from `litellm/config.yaml` and set
  `enable_jwt_auth` as in the report.
- **Keycloak is configured by realm import plus a Python script against the admin API, not Terraform.** Nothing extra to
  install, and it is still configuration as code. Terraform can come with Wave 1.
- **Every Keycloak client has full scope off.** With full scope on, Keycloak puts every client role
  in the token and adds those clients to `aud` by itself: a token for an unrelated app was accepted by
  demo-crm until this was turned off. The production realms need the same setting.
- **Seven MCP tools, not six.** `get_team_report` is on the assistant's list so that act 3 reaches
  demo-crm and is refused there (the token carries only `rep`), as the report describes.
- **The correlation id reaches demo-crm** through `extra_headers` on the MCP server in LiteLLM: no
  need for the report's fallback of passing it as a tool argument.
- **A `demo-mock` model** answers with a fixed text, so the checks run without a model API key.
  A real model needs `LLM_MODEL` plus its key (see *Run it*).
- **Test clients `demo-cli` and `other-app`** allow the password grant so the checks can get tokens.
  Dev only: they don't exist outside this POC.
