# Wave 0 POC: Foundation MVP

A working version of *Wave 0 — Foundation MVP* from the [architecture report](../docs/architecture-report.md):
people and AI agents reach one custom app (`demo-crm`) through Keycloak and LiteLLM, on synthetic data.

It is built in steps. Each step ends with a check script that passes from a clean `docker compose up`.

| Step | What it adds | Check |
| --- | --- | --- |
| **1 · Stack and identity** (this PR) | Keycloak realm, LiteLLM gateway that verifies Keycloak tokens, demo-crm API with synthetic data | `tests/step1_check.py`: 17 checks |
| 2 · Agents | MCP server, UI with “via agent” badges, `agent-dq`, `crm-assistant` with token exchange | Acts 1, 2, 4 |
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

The last command should end with `17/17 checks passed`.

To see the services from your browser, add this line to `/etc/hosts` once. Tokens are issued for
`sso.demo.local`, so the name must match inside and outside Docker:

```
127.0.0.1 sso.demo.local crm.demo.local
```

| Service | URL | Login |
| --- | --- | --- |
| Keycloak admin | http://sso.demo.local:8080 | `admin` / `KC_ADMIN_PASSWORD` |
| LiteLLM gateway | http://localhost:4000 | a Keycloak token, or the master key for admin |
| demo-crm API | http://localhost:8081/docs | a Keycloak token |

To start again from nothing: `docker compose down -v`.

## What is in it

| Service | Role |
| --- | --- |
| `keycloak` | Realm `ai-demo` (imported from `keycloak/realm-ai-demo.json`), synthetic users, client roles `rep` and `area-manager` |
| `keycloak-config` | One-shot `kcadm` script: scope `crm:ai` (adds the audiences and admits only the `rep` role) |
| `litellm` | Gateway. Verifies the Keycloak token, admits a client only if it has a LiteLLM team, logs every call with the person's `sub` and the client's team |
| `litellm-setup` | One-shot: one LiteLLM team per Keycloak client |
| `demo-crm-api` | The target app. Trusts only Keycloak, applies its own roles, records `created_by` and `via_agent` |
| `pg-*`, `redis` | Databases |

Synthetic users (dev only, password = username):

| User | Territory | Roles |
| --- | --- | --- |
| `luca` | NORTH | rep, area-manager |
| `giulia` | CENTRE | rep |
| `marco` | SOUTH | rep |

## Differences from the report, and why

- **LiteLLM runs open source, without the Enterprise licence.** LiteLLM's built-in JWT auth is
  Enterprise only. The same check is done by a small `custom_auth` hook, `litellm/keycloak_auth.py`
  (open source): it verifies issuer, audience and signature, then passes LiteLLM the person (`sub`) and
  the client (`azp`, one team per agent). LiteLLM's team checks still run after it, and the MCP endpoint
  uses the same hook. With the Enterprise trial, remove `custom_auth` from `litellm/config.yaml` and set
  `enable_jwt_auth` as in the report.
- **Keycloak is configured by realm import plus a `kcadm` script, not Terraform.** Nothing extra to
  install, and it is still configuration as code. Terraform can come with Wave 1.
- **Every Keycloak client has full scope off.** With full scope on, Keycloak puts every client role
  in the token and adds those clients to `aud` by itself: a token for an unrelated app was accepted by
  demo-crm until this was turned off. The production realms need the same setting.
- **A `demo-mock` model** answers with a fixed text, so the checks run without a model API key.
  The real model (`claude-sonnet`) needs `ANTHROPIC_API_KEY` from step 2.
- **Test clients `demo-cli` and `other-app`** allow the password grant so the checks can get tokens.
  Dev only: they don't exist outside this POC.
