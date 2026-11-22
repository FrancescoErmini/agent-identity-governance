# Wave 0 POC: Foundation MVP

A working version of *Wave 0 — Foundation MVP* from the [architecture report](../docs/architecture-report.md):
people and AI agents reach one custom app (`demo-crm`) through Keycloak and LiteLLM, on synthetic data.

It is built in steps. Each step ends with a check script that passes from a clean `docker compose up`.

| Step | What it adds | Check |
| --- | --- | --- |
| **1 · Stack and identity** ✓ | Keycloak realm, LiteLLM gateway that verifies Keycloak tokens, demo-crm API with synthetic data | `tests/step1_check.py`: 21 checks |
| **2 · Agents** ✓ | MCP server, UI with “via agent” badges, `agent-dq`, `crm-assistant` with token exchange | `tests/step2_check.py`: acts 1–4, 16 checks |
| **3 · Controls** ✓ | “Draft only” guardrail at the gateway, direct-call test, kill switch | `tests/demo_check.py`: the seven acts, 13 checks |
| **4 · Demo pack** ✓ | [Demo script](DEMO.md) (Italian), evidence of every act | `evidence/sample-2026-11-22/` |

## Run it

You need Docker Desktop or OrbStack. On a Mac, Apple Silicon is fine: every image is multi-arch.

```bash
cd poc
cp .env.example .env              # then set the passwords and the master key
docker compose up -d --build      # about 1 minute the first time
docker compose --profile check run --rm check
```

The last command should end with `21/21 checks passed`, `16/16 checks passed` and
`Demo: 13/13 checks passed`.

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
| LiteLLM gateway | http://localhost:4000 | a Keycloak token (agents and people) |
| LiteLLM admin UI | http://localhost:4000/ui | `admin` / `LITELLM_MASTER_KEY` |
| demo-crm API | http://localhost:8081/docs | a Keycloak token |

Without a model the assistant runs a fixed plan (*scripted mode*): every identity and permission
flow is the same, only the note text is a template. To use a model, set in `.env` either
`LLM_MODEL=gpt` and `OPENAI_API_KEY`, or `LLM_MODEL=claude-sonnet` and `ANTHROPIC_API_KEY`, then
`docker compose up -d`. The key stays in LiteLLM; the assistant reaches the model only through the
gateway, with the delegated token. The OpenAI model is set in `litellm/config.yaml` (`gpt-4.1-mini`).

To start again from nothing: `docker compose down -v`.

## Demo and evidence

The demo script, act by act, is in [DEMO.md](DEMO.md) (Italian). To record evidence of a run:

```bash
docker compose --profile check run --rm evidence              # runs the seven acts, writes evidence/run-<UTC time>/
node scripts/capture-screens.js evidence/run-<UTC time>/screens   # optional: one UI screenshot per act (needs Playwright)
```

Each run folder holds `SUMMARY.md` (checks per act, LiteLLM log for Luca's `sub`), the assistant's responses
(`acts.json`, with the delegated token's claims), the LiteLLM log and the demo-crm records. Run folders are
git-ignored; [`evidence/sample-2026-11-22/`](evidence/sample-2026-11-22/) is a committed example.

## What is in it

| Service | Role |
| --- | --- |
| `keycloak` | Realm `ai-demo` (imported from `keycloak/realm-ai-demo.json`), synthetic users, client roles `rep` and `area-manager` |
| `keycloak-config` | One-shot `keycloak/configure.py`: agent scopes, agent clients, delegation permission |
| `litellm` | Gateway. Verifies the Keycloak token, admits a client only if it has a LiteLLM team, applies each team's tool list and the “draft only” guardrail, logs every call with the person's `sub` and the client's team |
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

## The seven acts

`tests/demo_check.py` runs them in order. In the UI, acts 1–6 are buttons on an account; act 7 is
run by the operator.

| # | What happens | Where it is stopped or recorded |
| --- | --- | --- |
| 1 | Luca signs in and sees only NORTH accounts | demo-crm reads roles and territory from the token |
| 2 | “Prepare visit and draft a note”: the draft shows *proposed by agent-crm-assistant for luca*; Luca confirms it | demo-crm records `created_by` and `via_agent` |
| 3 | “Team report” through the assistant | demo-crm: 403, the delegated token has only `rep` |
| 4 | “Run agent-dq now” (stands in for the scheduler): reminders tagged *agent-dq (autonomous)* | agent-dq's own token, role `dq-agent` |
| 5 | “Try a tool it doesn't have”, then “try a final note” | LiteLLM: tool not on the team's list; guardrail `agents-draft-only` |
| 6 | “Bypass the gateway”: the final note sent straight to demo-crm | demo-crm stores it as a draft anyway |
| 7 | `./scripts/kill-switch.sh block`, then any assistant button; `unblock` to restore | LiteLLM refuses the blocked team; the log shows `sub` and agent for every call |

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
  uses the same hook. Anything that is not a Keycloak token (master key, admin UI session, LiteLLM
  virtual keys) goes on to LiteLLM's own auth, so the admin UI works as usual. With the Enterprise trial, remove `custom_auth` from `litellm/config.yaml` and set
  `enable_jwt_auth` as in the report.
- **Keycloak is configured by realm import plus a Python script against the admin API, not Terraform.** Nothing extra to
  install, and it is still configuration as code. Terraform can come with Wave 1.
- **Every Keycloak client has full scope off.** With full scope on, Keycloak puts every client role
  in the token and adds those clients to `aud` by itself: a token for an unrelated app was accepted by
  demo-crm until this was turned off. The production realms need the same setting.
- **Seven MCP tools, not six.** `get_team_report` is on the assistant's list so that act 3 reaches
  demo-crm and is refused there (the token carries only `rep`), as the report describes.
- **The “draft only” rule is a small custom guardrail** (`litellm/draft_only_guardrail.py`, open
  source) on LiteLLM's `pre_mcp_call` hook. LiteLLM's built-in `tool_permission` guardrail checks the
  tools in model requests, not direct MCP tool calls, so it would not stop act 5.
- **The kill switch blocks the agent's LiteLLM team** (`scripts/kill-switch.sh`). It stops the agent's
  model and tool calls at once. It does not stop a direct call to demo-crm (act 6 still reaches the
  app, which keeps it as a draft): in production the apps must be reachable only through the gateway
  and the MCP servers, or the agent's Keycloak client must be disabled too.
- **The correlation id reaches demo-crm** through `extra_headers` on the MCP server in LiteLLM: no
  need for the report's fallback of passing it as a tool argument.
- **A `demo-mock` model** answers with a fixed text, so the checks run without a model API key.
  A real model needs `LLM_MODEL` plus its key (see *Run it*).
- **Test clients `demo-cli` and `other-app`** allow the password grant so the checks can get tokens.
  Dev only: they don't exist outside this POC.
