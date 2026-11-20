# Architecture report: identity and authorization for people and AI agents

Nov 17, 2026

## Summary

AI agents join the same identity model as people, with no new IdP and no new portal: one authoritative source (HR for people, EasyVista for agents), one identity engine (NetIQ IDM), one directory for groups and roles (eDirectory/LDAP), Keycloak as the only IdP and LiteLLM as the only path to models and tools. All technical configuration is code in GitLab, applied by GitLab CI pipelines. The design rests on six hypotheses that the pilot must prove on seven target systems; the section *Validating the hypotheses* defines the tests. Delivery runs in four waves; the Foundation MVP demo is due before 15 December 2026.

**Decisions**

| # | Decision | Rationale |
| --- | --- | --- |
| 1 | Keycloak 26.8 as the only IdP and broker (LDAP + Google), one realm for people and agents | It is already the SSO of every application (M-Field, Salesforce, SAP, Veeva, Workday, …): extend it, don't add a second one |
| 2 | EasyVista as the authoritative registry of agents (CI class “AI Agent”) | It is to agents what HR is to people; no new portal |
| 3 | NetIQ Identity Manager as the single identity engine; eDirectory/LDAP as the single source of groups and roles | No second engine: Keycloak and LiteLLM read and map, they never assign |
| 4 | Self-hosted GitLab + GitLab CI to configure Keycloak, LiteLLM, Cerbos and targets | The merge request is the audit trail; secretless pipelines thanks to OIDC ID tokens |
| 5 | LiteLLM Enterprise as the gateway for LLMs and MCP | RBAC on teams, models, MCP servers and tools; audit and spend |
| 6 | Cerbos for ABAC rules (OPA as an equivalent alternative) | Policy as code, tests in CI, commercial support |
| 7 | User → agent delegation with token exchange and the `act` claim (Keycloak 26.8, preview) in development | In production, until supported: trace `sub` + `azp` |
| 8 | CIBA for risky actions | Human approval at runtime |

**Superseded**: midPoint, replaced by the NetIQ IDM already in use; Databricks, replaced by M-Field as a use case.

## Alignment with the agent identity security model

The design follows the five-layer model for agent identity (registration, runtime identity, delegated authority, task context, evidence) described in [AI Agent Identity Security](https://www.penligent.ai/hackinglabs/ai-agent-identity-security/), which draws on NIST's AI Agent Standards Initiative and the OWASP AI Agent Security Cheat Sheet. Three layers are covered; task context and evidence are completed by the additions below.

| Layer | Question it answers | Our design | Coverage |
| --- | --- | --- | --- |
| Registration | Who owns the agent, for what purpose, until when? | EasyVista CI with sponsor, archetype, expiry; NetIQ IDM lifecycle; k-agents as business UI; nightly reconciliation | Covered |
| Runtime identity | Is this really the agent? | One Keycloak client per agent; Kubernetes ServiceAccount token or private\_key\_jwt; no secrets in GitLab | Covered |
| Delegated authority | On whose behalf, with what reduced rights? | Token exchange with `act`; role intersection; Cerbos ABAC; CIBA | Covered |
| Task context | For which task, now? | `task_id` and purpose in the token; Cerbos denies high-risk calls without them | Added |
| Evidence | Can we reconstruct intent, grant, decision and result? | Shared evidence schema emitted by LiteLLM, Cerbos and MCP servers | Added |

**Waves against the model**

| Wave | Layers delivered |
| --- | --- |
| 0 · Foundation | Runtime identity, delegated authority, first evidence events |
| 1–2 · Validation | Task context, bound approvals, adversarial tests on real targets |
| 3 · Scale and governance | Registration at scale (IDM, EasyVista, k-agents), discovery of shadow agents, full evidence chain in the SIEM |

### Key concepts from the reference model

> **"If a high-risk action passes only the identity gate, it is under-governed."** — [Penligent, AI Agent Identity Security](https://www.penligent.ai/hackinglabs/ai-agent-identity-security/)

The central risk is not a stolen password: it is an agent with valid credentials and an approved tool that still acts outside the business intent, and leaves logs that look normal. The answer is to tie owner, intent, authorization, delegation, runtime and evidence into one chain that can be governed and revoked.

Reference diagrams in the article: [identity model comparison](https://www.penligent.ai/hackinglabs/wp-content/uploads/2026/06/image-116.png) and the agent delegation chain (see the article).

**Service account versus AI agent, and our answer**

| Aspect | Service account | AI agent | Our design |
| --- | --- | --- | --- |
| Owner | Application or platform team | A named person plus a technical owner | Sponsor and owner team in the EasyVista CI; review when the sponsor leaves |
| Behaviour | Fixed code path | Chooses tools based on context | Tools allow-listed per agent in LiteLLM; Cerbos per call |
| Main risk | Over-broad static rights | Same, plus prompt injection, task drift, lost delegation | Role intersection, task context, adversarial tests A1–A7 |
| Credential | Static secret or role | Runtime identity plus short task-bound token | ServiceAccount token or private\_key\_jwt; 5-minute delegated tokens |
| Audit question | Which service called what | Who started it, which agent acted, by which tool path, within scope or not | Evidence schema: subject, actor, task, grant, decision, result |

**The three gates before a high-risk action**

| Gate | Checks | In our design |
| --- | --- | --- |
| Identity | Known, owned agent in an approved runtime | Keycloak client per agent, workload credential, active CI |
| Authorization | This action, for this task, subject and scope | Downscoped token, Cerbos decision, bound CIBA approval |
| Evidence | Action can be rebuilt end to end | Evidence event with task and approval IDs in the SIEM |

**Credential patterns**

| Pattern | Our position |
| --- | --- |
| Static API key or personal token | Forbidden for agents |
| Shared service account | Forbidden: one identity per agent |
| User token passthrough | Forbidden: token exchange with `act` instead |
| Delegated OAuth token | Allowed only short-lived, audience-bound, task-bound |
| Workload identity (Kubernetes, SPIFFE) | Preferred way for the agent to prove itself |
| Transaction-bound token | To evaluate for high-risk, multi-hop calls |

### Additions to the design

Six additions close the gaps; each has an owner component and a test.

| # | Addition | How | Component |
| --- | --- | --- | --- |
| 1 | Task context | The agent requests the delegated token with a `task_id` and purpose (Rich Authorization Requests `authorization_details`, or a custom claim); Cerbos denies high-risk tools without them; transaction tokens to evaluate for multi-hop calls | Keycloak, Cerbos |
| 2 | Narrower at every hop | Design rule: each downstream token has an audience and scope that are a subset of the incoming one; sub-agents use token exchange again, never reuse the parent token | Keycloak, MCP servers |
| 3 | Approvals bound to the action | CIBA `binding_message` and `authorization_details` carry action, resource, amount, destination and expiry; the approval is valid once, for that call only | Keycloak CIBA, Cerbos |
| 4 | Action classes | Cerbos policies tag tools by class: data export, external communication, financial operation, access control, production change, code execution; each class sets step-up and evidence rules | Cerbos |
| 5 | Agent version in the record | The EasyVista CI holds model, prompt version and tool list; a change to any of them triggers a new review | EasyVista, NetIQ IDM |
| 6 | Local MCP servers | Not allowed on sensitive data; elsewhere only through the gateway, with origin checks and authentication; patched SDKs | Policy, LiteLLM |

**Revocation, mechanism by mechanism** — a kill switch is several switches, documented and tested separately:

| Mechanism | Action | Effect time |
| --- | --- | --- |
| Keycloak client | Disable client, revoke sessions and refresh tokens | Immediate for new tokens |
| Access tokens already issued | Short lifetime (5 min) plus introspection at the gateway for high-risk tools | At most the token lifetime |
| LiteLLM key and team | Block the team, revoke the key | Immediate |
| Workflows in flight | Gateway rejects calls carrying the revoked `task_id` | Immediate |

### Evidence schema

LiteLLM, Cerbos and every MCP server emit one shared event per tool call, so an action can be traced from the initiating request to its result, not just logged.

```json
{
  "event_id": "evt-7f3a",
  "time": "2026-12-10T09:42:17Z",
  "correlation_id": "c-91be",
  "task": { "id": "task-2219", "purpose": "visit preparation" },
  "subject": { "sub": "u-1042", "type": "human" },
  "actor": { "client_id": "agent-crm-assistant", "agent_ci": "CI-AGT-0042", "version": "model=claude-sonnet;prompt=v7" },
  "delegation": { "grant": "token-exchange", "aud": "mcp-mfield", "scope": "mfield:ai-read", "exp": "2026-12-10T09:47:17Z" },
  "policy": { "engine": "cerbos", "decision": "ALLOW", "policy_version": "crm-tools@14", "action_class": "read" },
  "approval": null,
  "tool": { "server": "mcp-mfield", "name": "get_visit_history", "params_sha256": "9c1e..." },
  "result": { "status": "ok", "records": 12 }
}
```

Parameters are stored as a hash, not in clear text, so evidence carries no personal data; the target app keeps the business record.

**Detections in the SIEM**

- High-risk action class without a matching approval, or with an expired one.
- Token audience different from the MCP server that received it.
- Call with a `task_id` that is closed or revoked.
- Agent version in the event different from the version in the EasyVista CI.

### Adversarial tests

These cases extend the test matrix of the validation plan: besides the happy path and the expected denials, every wave from Wave 1 on runs them on the delegated and the autonomous agent.

| # | Test | Expected result | Evidence |
| --- | --- | --- | --- |
| A1 | Malicious document: a record in the target holds hidden instructions to call a write or export tool | Call denied by Cerbos (no task scope for that class) or stopped by CIBA | Event with DENY or pending approval |
| A2 | Reused approval: replay a CIBA approval on a second call or with a different amount | Denied: approval bound to one call | DENY with reason "approval mismatch" |
| A3 | Sub-agent subject loss: a sub-agent calls a tool without the user in the token | Denied: subject and `act` chain required | DENY event |
| A4 | Wider downstream token: an MCP server requests a broader scope than it received | Token exchange refused by Keycloak | Keycloak error event |
| A5 | Local MCP server reached from a browser page (origin, DNS rebinding) | Refused: origin check and authentication | Gateway or server log |
| A6 | Revocation in flight: block the agent during a running task | Next call fails within the token lifetime; LiteLLM fails at once | Timestamps of block and first refusal |
| A7 | Version drift: change the prompt without a new review | Detection fires; tools restricted until review | SIEM alert |

After each fix, retest both the denied action and a legitimate delegated action, so security does not break function.

### Anti-patterns we avoid

- Agents treated as ordinary service accounts.
- Static API keys or personal tokens for agents.
- Trusting localhost as a boundary.
- MCP servers that forward calls with broad credentials (token passthrough).
- Raw prompt logs instead of structured evidence.
- Human-in-the-loop as a button instead of a bound, logged control.
- Agents left running after the owner leaves or the project ends.
- Prompt guardrails used in place of enforced authorization.

## Architecture

Four separate responsibilities: authoritative sources say who exists, NetIQ IDM decides who has what, Keycloak authenticates, LiteLLM and Cerbos enforce the rules; target systems apply their own roles.

&#91;embedded content: architecture · sources, IDM, Keycloak, gateway, targets\]

Dashed lines are configuration, keys and tokens; solid lines are request traffic, which always passes through the gateway.

| Component | Role | Note |
| --- | --- | --- |
| HR / EasyVista | Authoritative sources: people (HR), AI agents (CI “AI Agent” in EasyVista) | EasyVista is also the entry point for requests and approvals |
| NetIQ Identity Manager | Single engine: creates identities, assigns groups and roles, revokes | Reads EasyVista through a REST or JDBC driver, as it reads HR |
| eDirectory / LDAP (+ Google) | Single published source of users, non-human identities, groups | Keycloak reads it read-only |
| GitLab + GitLab CI | Configuration as code; pipelines that apply Keycloak, LiteLLM, Cerbos, targets | Merge requests with approvals; no secrets thanks to ID tokens |
| Keycloak 26.8 | Single IdP: SSO, tokens, agent clients, delegation, CIBA | Already the SSO of all seven target systems |
| LiteLLM Enterprise + Cerbos | Gateway for models and MCP tools: RBAC (LiteLLM) and ABAC (Cerbos) | Cerbos as a sidecar, fail-closed |
| MCP servers | Narrow tools towards each target system | Reachable only from the gateway |
| Target systems | SAP S/4HANA, M-Field, Salesforce, SynerTrade, Veeva Vault, Workday, Legisway | Apply their own roles: PFCG roles, M-Field roles, permission sets, Vault security profiles, Workday security groups |
| Model providers | Claude, SAP AI Core (Generative AI Hub) | Credentials only in the gateway |
| SIEM | Log correlation by correlation ID | Keycloak, LiteLLM, Cerbos, targets |

## People and agents compared

The agent process mirrors the established process for people: only the authoritative source changes (EasyVista instead of HR), plus one extra step, the GitLab CI pipeline that creates the Keycloak client and the gateway configuration.

&#91;embedded content: people and agents · same central components\]

NetIQ IDM, eDirectory and Keycloak are shared by both paths; for agents only the source (EasyVista) and the GitLab CI step, highlighted, are different.

| Aspect | People (established process) | AI agents (same model) |
| --- | --- | --- |
| Authoritative source | HR | EasyVista, CI “AI Agent” |
| Who starts it | HR at hiring; the employee for additional access | The sponsor (business) or the team building the agent |
| Who approves | Manager and application owner | AI governance, security, owners of the data and systems touched |
| Engine | NetIQ IDM | NetIQ IDM |
| Where the identity lives | User in eDirectory | Non-human identity in eDirectory, with sponsor and expiry |
| Where permissions live | Groups in eDirectory, written by the IDM | Groups in eDirectory + client scopes, defined in Git |
| Representation in Keycloak | LDAP-federated user (or brokered from Google) | Confidential client `agent-*` with a service account |
| Credential | Password + MFA | No secret: federated Kubernetes token or private key (`private_key_jwt`) |
| How it gets a token | Authorization Code + PKCE (Flow 1) | Client Credentials (Flow 2) or delegation (Flow 3) |
| Accountable | The employee and their manager | The sponsor; if they leave, their manager |
| Recertification | Periodic campaigns | Renewal at expiry by the sponsor |
| Exit | End of employment, from HR | CI retired, expiry not renewed, sponsor not reassigned |

Two differences really matter: an agent always has an expiry (people don't), and an agent never holds credentials a human could reuse.

## How an agent is born

An agent starts from a request in EasyVista and becomes operational only after an approved merge request in GitLab: every step leaves a trace, and nobody creates clients or permissions by hand.

&#91;embedded content: creating an agent · 9 steps, 7 actors\]

“Platform” means Keycloak, LiteLLM and Cerbos, configured by GitLab CI. The numbers match the steps listed below; dashed arrows are replies and outcomes.

**The steps**

1. **Request** — The sponsor opens the “New AI agent” request in EasyVista: purpose, archetype (agent type from the catalogue), target systems, data processed, mode (autonomous or on behalf of a user), expiry.
2. **Approvals** — AI governance, security and data owners approve in the EasyVista workflow (or in NetIQ Identity Governance, if available). Read-only archetypes get a simplified approval.
3. **CI active** — EasyVista sets the “AI Agent” CI to active.
4. **Identity** — NetIQ IDM reads the CI (REST or JDBC driver), creates the non-human identity in eDirectory with sponsor and expiry, and assigns the groups the archetype provides.
5. **Merge request** — The IDM (through a GitLab bot) opens a merge request in the `identity-config` repository with the agent definition file.
6. **Review and test** — CODEOWNERS (AI platform and security) approve; GitLab CI validates the schema, the policies and the change plan.
7. **Apply** — On merge to `main` (protected branch) GitLab CI creates the Keycloak client and scopes, the team and MCP permissions in LiteLLM, and the attributes in Cerbos.
8. **Roles on targets** — Where a technical identity is needed (SAP user, Salesforce integration user, Workday agent account), the pipeline opens a request to the system owner, who assigns the minimum role.
9. **Verify and confirm** — The verify job obtains a test token and checks claims and permissions; the outcome goes back to the IDM and EasyVista, which tells the sponsor the agent is active.

**The agent definition file** (generated by the IDM, changed only through merge requests)

```yaml
# identity-config/agents/agt-0042.yaml
id: agt-0042
name: crm-assistant
easyvista_ci: CI-AGT-0042
sponsor: maria.rossi@acme.it
owner_team: team-crm-digital
archetype: crm-assistant-read
mode: delegated              # autonomous | delegated
expires: 2027-05-31
keycloak:
  client_id: agent-crm-assistant
  auth: federated-k8s        # federated-k8s | private_key_jwt
  optional_scopes: ["mfield:ai-read"]
litellm:
  team: crm-ai
  models: [claude-sonnet]
  mcp_tools:
    m-field: [search_accounts, get_visit_history, draft_visit_note]
  max_budget_eur_month: 200
cerbos:
  attributes: { bu: commercial-it, data_class: hcp-personal }
```

**The GitLab CI pipeline**

| Stage | What it does | When |
| --- | --- | --- |
| `validate` | File schema, existing archetype, active sponsor, expiry present; `cerbos compile` with the policy tests | Every merge request |
| `plan` | `terraform plan` on Keycloak; diff of the LiteLLM configuration | Every merge request, result posted as an MR comment |
| `apply` | `terraform apply` on Keycloak; API calls to LiteLLM; Cerbos bundle | Only on `main`, after approval |
| `verify` | Test token; checks on `aud`, `scope`, roles; negative tests (scope not allowed, tool not permitted) | After `apply` |
| `report` | Outcome and `client_id` back to NetIQ IDM and EasyVista | After `verify` |

**No secrets in the pipeline**: jobs use GitLab CI OIDC ID tokens (`id_tokens` keyword, with a dedicated `aud`) to authenticate to Keycloak through federated client authentication, and to Vault for the few remaining credentials. To verify on 26.8: GitLab configured as a trusted issuer for the admin client.

**Agent credential**: on Kubernetes the agent presents its own ServiceAccount token (federated client authentication); elsewhere it uses a key pair generated in its own environment, and only the public key goes into Git. The private key never passes through GitLab.

## Lifecycle and reconciliation

Every change follows the same path as creation (EasyVista → NetIQ IDM → merge request → GitLab CI); the only exception is the emergency block, which acts at once and is regularised afterwards.

| Event | Who starts it | What happens |
| --- | --- | --- |
| Permission change | Sponsor, in EasyVista | New approvals; the IDM updates the groups and opens the MR; GitLab CI applies |
| Renewal | Sponsor, before expiry | Recertification: the sponsor confirms purpose and permissions; new expiry in the CI |
| Expiry not renewed | Automatic (IDM) | Suspension: client disabled in Keycloak, team blocked in LiteLLM; retirement after 30 days |
| Sponsor leaves the company | Automatic (HR → IDM flow) | The agent passes to the sponsor's manager, who must confirm or retire it |
| Emergency (compromised agent) | Security | Immediate block in LiteLLM and Keycloak via runbook; then the CI is suspended in EasyVista |
| Retirement | Sponsor or expiry | Cascading removal: client, team, Cerbos attributes, technical identities on targets; the CI stays as history |

**Nightly reconciliation** — A scheduled GitLab pipeline compares five lists: active CIs in EasyVista, non-human identities in eDirectory, files in `identity-config/agents`, `agent-*` clients in Keycloak, agents and teams in LiteLLM.

- Keycloak `agent-*` client without an active CI: disabled at once and flagged with an EasyVista ticket.
- Configuration that differs from Git (manual change): restored by the pipeline and flagged.
- Active CI without a client: ticket to the AI platform team.

It is the protection against “shadow” agents and it compensates for CMDB quality: EasyVista remains the source, but it doesn't have to be perfect for the system to be safe.

## Who uses an agent and how it authenticates

An agent works in one of two modes, and the mode decides which identity reaches the target system: its own (autonomous agent) or that of the user it works for (delegated agent).

| Mode | Who uses it | Token | Identity seen by the target | Detail |
| --- | --- | --- | --- | --- |
| Person without an agent | The employee, through chat or an application | Authorization Code + PKCE | The person | Flow 1 |
| Autonomous agent | Nobody in real time: it runs on a schedule or an event | Client Credentials, no secret | The agent's technical identity, with a minimum role | Flow 2 |
| Delegated agent | An employee who hands it a task | Token exchange: `sub` = user, `act` = agent | The person, with permissions reduced to the intersection with the agent's | Flow 3 |
| Interactive MCP client | Developers and power users (Claude Code, IDEs) | Authorization Code + PKCE to the gateway | The person | Flow 4 |

In every case the call goes through LiteLLM, which verifies the token, applies RBAC and asks Cerbos for the ABAC decision before touching an MCP server. The full HTTP requests are in the annexes.

## Why Keycloak: integrating with what exists

Keycloak is already the IdP of every application: adding agents as new clients of the same realm means applications receive tokens with the same issuer, the same keys and the same role claims they already know how to validate. Scopes and audiences are added; the login of people does not change.

### Example: M-Field

**Today** — Client `m-field` in Keycloak, custom client roles (`informatore`, i.e. medical sales rep, `area-manager`, `medical`, `marketing`) assigned from LDAP groups; M-Field reads them from the JWT in `resource_access.m-field.roles`.

**What is added in Keycloak** (all in Terraform, in the `identity-config` repository)

1. Two client scopes, `mfield:ai-read` and `mfield:ai-write`, each with:
   - an audience mapper that adds `m-field` to the token's `aud`;
   - a role scope mapping only towards the M-Field roles an agent may use (e.g. `informatore` for reading).
2. Agent clients with “Full scope allowed” switched off and the M-Field scopes assigned as *optional*: the agent gets them only if it requests them, and only if its archetype provides them.
3. Result: the agent's token carries only the M-Field roles the user holds **and** the scope admits. Keycloak computes the intersection.

```hcl
resource "keycloak_openid_client_scope" "mfield_ai_read" {
  realm_id               = keycloak_realm.acme.id
  name                   = "mfield:ai-read"
  include_in_token_scope = true
}

resource "keycloak_openid_audience_protocol_mapper" "mfield_ai_read_aud" {
  realm_id                 = keycloak_realm.acme.id
  client_scope_id          = keycloak_openid_client_scope.mfield_ai_read.id
  name                     = "aud-m-field"
  included_client_audience = "m-field"
}

resource "keycloak_generic_role_mapper" "mfield_ai_read_informatore" {
  realm_id        = keycloak_realm.acme.id
  client_scope_id = keycloak_openid_client_scope.mfield_ai_read.id
  role_id         = data.keycloak_role.mfield_informatore.id
}

resource "keycloak_openid_client_optional_scopes" "agent_crm_assistant" {
  realm_id        = keycloak_realm.acme.id
  client_id       = keycloak_openid_client.agent_crm_assistant.id
  optional_scopes = [keycloak_openid_client_scope.mfield_ai_read.name]
}
```

**Tokens compared**

| Claim | Person via SSO (today) | Agent on behalf of the same person |
| --- | --- | --- |
| `iss` | realm `acme` | realm `acme` (same) |
| `sub` | maria.rossi | maria.rossi (same) |
| `aud` | `m-field` | `litellm-proxy`, `m-field` |
| `azp` | `m-field` | `agent-crm-assistant` |
| `act` | — | `{ client_id: agent-crm-assistant }` |
| `scope` | `openid profile` | `mfield:ai-read` |
| `resource_access.m-field.roles` | `informatore`, `area-manager` | `informatore` |

**What changes in M-Field**

| Change | Needed? |
| --- | --- |
| Token validation | None: same issuer, same keys, same audience `m-field` |
| Reading roles | None: same claim |
| API with bearer token | Only if today the APIs accept only the web session |
| AI channel | If the token has `act` or a `mfield:ai-*` scope: extra rules (no export, writes only as drafts without `mfield:ai-write`) |
| Audit | Log `act.client_id` and the correlation ID next to the user |

The same pattern applies wherever a target's API can trust a Keycloak token: Salesforce, already behind Keycloak, through its token exchange handler; SAP through SAP IAS trusting Keycloak; Veeva Vault possibly through its OAuth 2.0 / OpenID Connect profile. Where an API trusts only its own tokens (Workday, Legisway, probably SynerTrade), the MCP server bridges, and the validation section tests what that costs. A separate IdP for agents, or API keys per agent, would force every application to trust a new issuer and to duplicate roles.

## RBAC, ABAC and policy

RBAC decides in advance who can do what, based on the roles assigned by the IDM; ABAC decides on every call, based on the attributes of the request. Both are code in GitLab, with tests and approvals, and each layer has a different owner.

&#91;embedded content: decision chain · 5 layers, each with its owner\]

**How the token, roles and attributes travel**

&#91;embedded content: token, roles and attributes · from NetIQ IDM to the target\]

Roles and attributes are assigned once, in NetIQ IDM, and reach every later layer inside the Keycloak token. LiteLLM verifies the token locally, Cerbos judges each single call, and the target applies its own roles, so a mistake in one layer is caught by the next.

**RBAC and ABAC: what each decides**

|  | RBAC | ABAC |
| --- | --- | --- |
| Question | Can this identity use this system and this tool? | Is this call, with these arguments, in this context, allowed? |
| Where it is assigned | NetIQ IDM → eDirectory groups → Keycloak roles; target roles | Cerbos policies in GitLab |
| Where it is enforced | Keycloak (roles and scopes in the token), LiteLLM (teams, models, MCP servers and tools), target | LiteLLM guardrail → Cerbos, before every tool call |
| Attributes used | Role, group, team | Archetype, BU, delegating user (`sub`), agent (`act`), arguments, amounts, number of records, data class, approval present |
| Changes with | Hires, new agents, requests in EasyVista | New business or compliance rules |

**What lives where in GitLab**

| Repository | Content | Applied by | Approvers (CODEOWNERS) |
| --- | --- | --- | --- |
| `identity-config/keycloak` | Realm, clients, client scopes, mappers, client policies (Terraform) | GitLab CI → Keycloak admin API | IAM team |
| `identity-config/agents` | Agent definition files (generated by the IDM) | GitLab CI | AI platform + security |
| `ai-gateway/litellm` | Configuration, teams, permissions on models and MCP tools, guardrails | GitLab CI → LiteLLM API and deploy | AI platform |
| `ai-gateway/policies` | Cerbos policies and their tests | GitLab CI (`cerbos compile` with tests) → bundle | Security + data owners |
| `mcp-servers/*` | MCP server code and tool catalogue | GitLab CI build and deploy | MCP server team + target owner |

**RBAC in LiteLLM** — Token verified with JWT auth; teams derived from roles; for each team the allowed MCP servers and individual tools (a tool that is not allowed doesn't even appear in the list).

```json
POST /team/new
{
  "team_alias": "crm-ai",
  "models": ["claude-sonnet"],
  "object_permission": {
    "mcp_servers": ["m-field"],
    "mcp_tool_permissions": {
      "m-field": ["search_accounts", "get_visit_history", "draft_visit_note"]
    }
  }
}
```

**First filter on arguments in LiteLLM** — The Tool Permission Guardrail allows a tool only if its arguments match patterns:

```yaml
guardrails:
  - guardrail_name: "sap-scope"
    litellm_params:
      guardrail: tool_permission
      rules:
        - id: "po-only-italian-plants"
          tool_name: "^sap-s4-get_purchase_order$"
          decision: "allow"
          allowed_param_patterns:
            "plant": "^(IT01|IT02)$"
```

**ABAC with Cerbos** — A custom guardrail calls Cerbos before every model call (`pre_call`) and every tool call (`pre_mcp_call`): principal = token claims (`sub`, roles, `azp`, `act`, BU, archetype); resource = MCP server; action = tool; attributes = arguments. Outcome: allow, deny, or “approval required” (CIBA). Cerbos unreachable: denied.

**OPA as an alternative** — If OPA is preferred only the engine changes: same enforcement point (LiteLLM guardrail), same inputs, policies in Rego instead of YAML/CEL, same tests in GitLab CI.

## Granularity of MCP permissions towards targets

An agent's permissions towards a target system narrow across eight levels, from coarsest to finest. The two most robust are tool design and the role on the target, because no prompt can get around them; the others cut risk before the call gets there.

| # | Level | Where | Example | What it prevents |
| --- | --- | --- | --- | --- |
| 1 | Visible MCP servers | LiteLLM (team or agent) | Team `crm-ai` sees only the `m-field` server | Access to whole systems not foreseen |
| 2 | Allowed tools | LiteLLM (`mcp_tool_permissions`) | Only `search_accounts`, `get_visit_history` | Actions not foreseen: the tool doesn't appear in the list |
| 3 | Argument patterns | LiteLLM (Tool Permission Guardrail) | `plant` must be `IT01` or `IT02` | Values outside scope or format |
| 4 | Contextual rules | Cerbos | Amount ≤ €5,000; at most 50 records; only accounts in the user's territory | Disallowed combinations of attributes |
| 5 | Human approval | CIBA | Order above threshold approved by the manager | High-risk actions without a human |
| 6 | Tool design | MCP server | `get_purchase_order(id)` instead of `run_odata(query)`; returned fields filtered | Arbitrary queries, field exfiltration |
| 7 | Identity and role on the target | Target | Display-only PFCG role; limited permission set; minimal M-Field role | Anything the role doesn't allow |
| 8 | Volumes and budget | LiteLLM | Rate limit and monthly budget per agent | Abuse, loops, runaway costs |

Design rule: every tool that writes must have at least levels 4, 6 and 7; tools that write into regulated processes also need level 5.

## Use case 1: SAP S/4HANA (purchasing)

SAP doesn't understand Keycloak claims: the autonomous agent uses a technical user with a minimum role, delegation uses principal propagation. The delicate point is audit: SAP sees only the user, so the distinction has to be designed.

### A — Autonomous agent: purchase order monitoring

| Aspect | Configuration |
| --- | --- |
| Purpose | Reads open orders, spots late deliveries, opens a ticket to the buyer |
| Keycloak identity | Client `agent-sap-po-monitor`, federated Kubernetes token, scope `mcp:sap:read` |
| Identity on SAP | Technical communication user `AI_PO_MON`, role `Z_AI_PO_DISPLAY` created by the SAP security team |
| SAP role (level 7) | `M_BEST_EKO` purchasing org 1000; `M_BEST_WRK` plants IT01, IT02; `ACTVT` 03 (display only) |
| Server and tools (levels 1–2) | Server `sap-s4`; tools `list_overdue_purchase_orders`, `get_purchase_order`; `create_*` and `change_*` not exposed |
| Arguments (level 3) | `plant` must be IT01 or IT02 |
| Cerbos (level 4) | At most 100 rows per call; purchasing org 1000 only |
| Tool design (level 6) | Returns order number, supplier, expected date, status; no prices |
| Volumes (level 8) | 500 calls a day, budget €50 a month |
| Denied call, example | The model tries to change a delivery date: the tool doesn't exist for this agent, and SAP would refuse anyway (`ACTVT` 02 not granted) |

### B — Delegation: a buyer creates an order with the assistant

| Aspect | Configuration |
| --- | --- |
| Scenario | Maria (buyer) asks the assistant to create an order for supplier X |
| Token | `sub` = maria.rossi, `act` = `agent-sap-buyer-assistant`, scope `mcp:sap:write` |
| Identity on SAP | MROSSI, through principal propagation (SAP IAS trusts Keycloak; Cloud Connector to S/4HANA) |
| Effective permissions | Maria's PFCG roles, limited to the tools allowed to the agent (`create_purchase_order`, `get_purchase_order`) |
| Cerbos | Up to €5,000 it proceeds; above that, the agent starts CIBA towards the purchasing manager |

**How the audit tells Maria from the agent**

| Option | How it works | Pros | Cons |
| --- | --- | --- | --- |
| Correlation | SAP logs MROSSI; LiteLLM and Cerbos log `act` and the correlation ID; the SIEM joins them | No change in SAP | SAP's own audit can't tell them apart |
| Marking in the document | The tool writes in the header text: “created via agent X for MROSSI, ref. {correlation ID}” | Visible to anyone who opens the order | Weak: it's only text |
| “AI” alias user | Tokens with `act` are mapped to a derived user (e.g. MROSSI\_AI) with reduced derived roles | Native distinction in SAP change documents | Duplicate users; SAP licence impact to verify; mapping rules in IAS / Cloud Connector |

Recommendation: correlation + marking in the pilot; alias user only if audit or compliance require the distinction natively in SAP.

## Use case 2: M-Field (commercial CRM)

M-Field is the simplest and most complete case: it already reads roles from the Keycloak JWT, so adding scopes and audiences is enough, and it can log the agent in its own audit because it is an in-house application.

### A — Autonomous agent: visit report quality

| Aspect | Configuration |
| --- | --- |
| Purpose | Every night finds incomplete visit reports and creates a reminder for the sales rep |
| Keycloak identity | Client `agent-mfield-dq`, federated Kubernetes token, scopes `mfield:ai-read` and `mfield:ai-write` |
| M-Field role (level 7) | Technical role `ai-dq-bot` of the `m-field` client: reads visit reports, creates reminders; no access to physicians' personal data beyond the ID |
| Server and tools (levels 1–2) | Server `m-field`; tools `list_incomplete_visit_reports`, `create_followup_task` |
| Arguments (level 3) | `task_type` must be `data_quality` |
| Cerbos (level 4) | At most 200 reports per run; reminders only to the rep who owns the report |
| Tool design (level 6) | `list_incomplete_visit_reports` returns report ID, missing fields, rep ID: no free text, no physician personal data |
| Denied call, example | The model tries to read full visit notes: tool not exposed, and the `ai-dq-bot` role has no permission to read notes |

### B — Delegation: a sales rep prepares a visit with the assistant

| Aspect | Configuration |
| --- | --- |
| Scenario | Luca (sales rep) asks for a summary before visiting a physician and for a draft visit note |
| Token | `sub` = luca, `act` = `agent-crm-assistant`, `aud` includes `m-field`, scope `mfield:ai-read mfield:ai-write` |
| Roles in the token | Only `informatore`: Luca is also `area-manager`, but the agent's scope doesn't admit it (Keycloak intersection) |
| Effective permissions | Luca's territorial visibility in M-Field, limited to the tools `get_account_summary`, `get_visit_history`, `draft_visit_note` |
| Writes | The note is saved as a draft “proposed by the assistant”; it becomes final only when Luca confirms it in the M-Field UI |
| Cerbos | No export; at most 20 accounts per request |
| How the audit tells them apart | M-Field logs user = luca, channel = AI, agent = `act.client_id`, correlation ID: native distinction in the application log |

Here the choice of Keycloak makes everything straightforward: no new issuer to trust, roles already in the expected format, permission intersection computed by the IdP.

## Use case 3: Salesforce

Salesforce is already behind Keycloak for people's SSO; for agents' API calls it uses Salesforce's OAuth 2.0 token exchange flow: an Apex token exchange handler validates the Keycloak token and maps it to a Salesforce user, and Salesforce then applies profiles, permission sets and sharing rules.

**Common configuration**

- In Keycloak: client scope `salesforce:ai` with an audience mapper towards `salesforce` (same pattern as M-Field).
- In Salesforce: one external client app per agent (or per archetype), enabled for token exchange; an Apex handler that checks the signature (realm JWKS), `iss`, `aud` and expiry, and maps the subject.
- Salesforce MCP server: exchanges the Keycloak token it receives for a Salesforce token and calls the REST APIs.

### A — Autonomous agent: lead enrichment

| Aspect | Configuration |
| --- | --- |
| Purpose | Fills in industry and size of new leads from approved sources |
| Keycloak identity | Client `agent-sf-lead-enricher`, secretless client credentials, scope `salesforce:ai` |
| Identity on Salesforce | The handler maps `azp` = `agent-sf-lead-enricher` to a dedicated integration user (API only) |
| Salesforce permissions (level 7) | Permission set: read Lead and Account; edit only the `Industry` and `NumberOfEmployees` fields of Leads (field-level security) |
| Server and tools (levels 1–2) | Server `salesforce`; tools `search_leads`, `update_lead_firmographics` |
| Arguments (level 3) | Updatable fields: only `Industry`, `NumberOfEmployees` |
| Cerbos (level 4) | Only leads in status “New”; at most 100 updates a day |
| Denied call, example | The model tries to change a lead's owner: argument not allowed by the guardrail, field not editable under the permission set |

### B — Delegation: a sales rep updates an opportunity with the assistant

| Aspect | Configuration |
| --- | --- |
| Scenario | Giulia (sales rep) asks the assistant to update the next step and the close date of an opportunity |
| Token | `sub` = giulia, `act` = `agent-sales-assistant`, `aud` includes `salesforce`, scope `salesforce:ai` |
| Identity on Salesforce | The handler maps email or federation ID to Giulia's Salesforce user |
| Effective permissions | Giulia's profile, permission sets and sharing, limited to the tools `get_opportunity`, `update_opportunity_next_step` |
| Cerbos | No change to the amount, and no stage beyond “Negotiation”, without CIBA |
| How the audit tells them apart | Each agent uses its own external client app: Salesforce login history and API events show the app (with Event Monitoring, to check against the licence). In addition, the tool writes a dedicated field (e.g. `AI_Agent__c`) on changes made through an agent |

With one external client app per agent, Salesforce tells the channel apart natively while still applying the user's permissions.

## Audit: telling person and agent apart

Every action can be traced from request to data through a correlation ID generated by LiteLLM and passed to the MCP server and, where possible, to the target; whether the target itself tells person and agent apart depends on the system.

| System | What it records | Person / agent distinction |
| --- | --- | --- |
| EasyVista | Request, approvals, CI status | Who authorised the agent |
| GitLab | Merge requests, approvers, pipelines | Who changed the configuration and when |
| Keycloak | Logins, token issuance, token exchange, consents, CIBA | Native: `azp` and `act` in every token event |
| LiteLLM | Every call: user, agent, team, model, tool, cost | Native |
| Cerbos | Decision, rule applied, arguments evaluated | Native |
| M-Field | Application log | Native, by logging `act.client_id` |
| Salesforce | Login history, API events, `AI_Agent__c` field | Native, through one external client app per agent |
| SAP S/4HANA | Security Audit Log, change documents | Only via correlation or an “AI” alias user |
| SynerTrade, Veeva Vault, Workday, Legisway | See *Validating the hypotheses* | To be proven per system (hypothesis H5) |

All logs flow into the SIEM (e.g. Google SecOps). Sensitive fields in decision logs and prompt contents are excluded or masked by default; what to retain is decided with the DPO and compliance (GDPR, GxP).

## Validating the hypotheses

The design holds only if six hypotheses survive tests on seven target systems, each in two modes: an agent acting for a person (delegated) and an autonomous agent. A hypothesis passes when the allowed call works, every forbidden call is refused at the layer the design names, and the audit trail tells person and agent apart.

### The six hypotheses

| ID | Hypothesis | Passes when | If it fails |
| --- | --- | --- | --- |
| H1 | **One identity reaches every target.** Each target accepts an identity derived from the Keycloak token: natively, by token exchange, or through a technical account held by the MCP server | The positive test of every row in the matrix succeeds and the agent holds no static secret | The target stays autonomous-only behind a technical account in the secret manager, or out of scope |
| H2 | **Delegated = person ∩ agent.** A delegated agent never does more than the person, nor more than its archetype | Both negative tests are refused: an action the person may do but the agent may not, and one the agent may do but the person may not | Delegated mode is not offered on that target |
| H3 | **Autonomous = least privilege.** The autonomous agent's identity on the target holds only the minimum role | The forbidden action is refused by the target itself | The target owner narrows the role before go-live |
| H4 | **Two independent layers stop every write.** Each write restriction is enforced at the gateway (levels 1–5) and at the target (level 7) | The same forbidden call is refused with the gateway checks on, and again when sent straight from the MCP server in the test environment | Write tools stay disabled on that target |
| H5 | **Audit tells person from agent.** From a record on the target, an auditor finds the person, the agent and the EasyVista approval | The correlation ID links target log, LiteLLM, Cerbos and Keycloak for every test | Correlation plus marking, as for SAP, or an alias user |
| H6 | **Revocation reaches every target.** Blocking the agent stops all its calls within the token lifetime | After the kill switch no call succeeds after 5 minutes, and the pipeline disables the technical identities on the targets | Revocation runbook per target; the agent is not promoted |

### How each target accepts an agent

Keycloak is the SSO of all seven systems for people, but SSO in the browser doesn't mean the API accepts a Keycloak token. For each target, this is the integration hypothesis to prove first.

| System | API access for the agent (hypothesis) | What the target sees: delegated / autonomous | Riskiest point to verify | Status |
| --- | --- | --- | --- | --- |
| SAP S/4HANA | Principal propagation via SAP IAS trusting Keycloak, and Cloud Connector; technical communication user for autonomous agents | The person (MROSSI) / `AI_PO_MON` | IAS trust towards Keycloak and propagation rules; native audit only with an alias user | Not started |
| M-Field | Keycloak JWT accepted natively (`aud` `m-field`, roles in `resource_access`) | The person + `act.client_id` / role `ai-dq-bot` | The APIs accept a bearer token, not only the web session | Not started |
| Salesforce | OAuth 2.0 token exchange, with an Apex handler validating the Keycloak token | The person, through the agent's external client app / integration user | Edition and licences for token exchange and Event Monitoring | Not started |
| SynerTrade (P2P) | Not confirmed: public sources disagree on whether a usable API exists. Hypothesis: vendor API with a technical account held by the MCP server | A technical account in both modes: SynerTrade doesn't see the person | Whether an API exists and can act as a named user; if not, no delegated writes | Not started |
| Veeva Vault | Vault's OAuth 2.0 / OpenID Connect profile exchanges an IdP access token for a Vault session; the API applies the same access controls as the UI | The person, with their security profile and sharing / dedicated integration user | Vault documents PingFederate, ADFS and Okta as authorization servers (Entra ID in later versions), not Keycloak: test the profile with Keycloak in a sandbox | Not started |
| Workday | Workday issues its own tokens. Its Agent System of Record (ASOR) registers external agents in two modes: delegate (OAuth on the user's behalf) and ambient (x509 key, with an Agent System User and an Agent Security Group). At runtime Workday checks both the user's access to the agent and to the APIs it calls | The person: Workday applies the worker's own permissions, and only through the agent's skills / the agent's own Agent System User | ASOR enabled on the tenant; a second agent registry to reconcile with EasyVista | Not started |
| Legisway | REST APIs (Search, Content, File Transfer) with a JWT from Legisway's own Authentication API; API access depends on the package | API user per agent / delegated: unknown | Whether API calls run with a named user's rights; if not, delegated mode only for reads filtered by the MCP server | Not started |

**Audit hooks for H5**

- Veeva Vault: the API records a client ID per call (`X-VaultAPI-ClientID`, one per agent) and a reference ID (`X-VaultAPI-ReferenceID`, the correlation ID) in its API usage log. Veeva says that log is not designed for auditing, so the evidence stays the Vault audit trail plus the SIEM join.
- Workday: the audit log distinguishes an ambient agent acting alone from a delegate agent acting for a specific user (View AI Agent User Audit Trail report).
- SynerTrade and Legisway: no documented hook; the MCP server writes the correlation ID into a reference or note field where one exists, otherwise correlation only.

### Test matrix: one restriction per system and mode

Each row names something the agent must not do, even where the person could. L1–L8 are the levels of the granularity table; “KC” is Keycloak's scope intersection.

| # | System | Mode | Use case | Restriction on the agent | Enforced at | Negative test → expected result |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | SAP S/4HANA | Delegated: buyer | Create a purchase order with the assistant | Up to €5,000 without approval, and only in Maria's purchasing org, even if her PFCG roles allow more | L4 Cerbos, L5 CIBA, L7 PFCG | €12,000 order → paused for CIBA approval; order for org 2000 → refused by SAP, logged with `act` |
| 2 | SAP S/4HANA | Autonomous | Overdue purchase order monitoring | Display only, plants IT01/IT02, no prices | L2, L3, L6, L7 (`ACTVT` 03) | `change_delivery_date` → tool not listed; plant DE01 → guardrail deny; same call straight to SAP → refused (`ACTVT` 02) |
| 3 | M-Field | Delegated: sales rep | Visit preparation and draft note | Only the `informatore` role, though Luca is also `area-manager`; notes only as drafts; no export | KC, L4, M-Field draft rule | Team-wide report (area-manager function) → 403 from M-Field; export of 500 accounts → Cerbos deny |
| 4 | M-Field | Autonomous | Incomplete visit reports | No note text or physician personal data; reminders only to the report owner | L4, L6, L7 (`ai-dq-bot`) | Read a full note → refused by the role; reminder to another rep → Cerbos deny |
| 5 | Salesforce | Delegated: sales rep | Update an opportunity's next step | No change to amount, or stage beyond Negotiation, without approval; only records shared with Giulia | L4, L5, L7 sharing | Change the amount → CIBA; update an opportunity not shared with Giulia → refused by Salesforce |
| 6 | Salesforce | Autonomous | Lead enrichment | Only `Industry` and `NumberOfEmployees`, on leads in status New | L3, L4, L7 field-level security | Change `OwnerId` → guardrail deny; same call straight to Salesforce → refused by field-level security |
| 7 | SynerTrade | Delegated: requester | Create a catalogue purchase requisition | Create only, never approve or release; catalogue items only; only the person's cost centre | L2, L4, L6 | Approve own requisition → tool absent; other cost centre → Cerbos deny; check whether SynerTrade also refuses it (if not, H4 fails: no delegated writes) |
| 8 | SynerTrade | Autonomous | Report invoices blocked on price or quantity mismatch | Read only; no change to supplier master data, bank details above all | L2, L7 read-only account | Update a supplier's bank account → tool absent; same call straight to SynerTrade → refused for the technical account |
| 9 | Veeva Vault | Delegated: reviewer | Summarise a document and draft review comments | Only documents the person can see; never change lifecycle state (approve, release) | L2, L7 sharing and lifecycle roles | Move a document to Approved → tool absent; document outside the person's sharing → refused by Vault |
| 10 | Veeva Vault | Autonomous | Metadata quality check on selected document types | Metadata of named document types only; no file download; no edits | L3, L6, L7 security profile | Download a source file → tool absent; same call straight to Vault → refused by the security profile |
| 11 | Workday | Delegated: employee | Check leave balance and request time off | Only for the person themselves; no compensation data | L4 (worker = `sub`), L7 worker's rights, only through the agent's skills | Leave balance of a colleague → refused by Workday (the worker's own permissions); salary → no tool in the agent's skills exposes compensation |
| 12 | Workday | Autonomous (ambient) | Flag new hires starting next week with missing data | View only, hiring data of one supervisory organisation; no compensation, national ID or address | L6, L7 Agent Security Group domains | Compensation of a new hire → refused by Workday; another organisation → refused |
| 13 | Legisway | Delegated: legal counsel | Contracts expiring within 90 days in the person's legal entity; draft renewal notice | Only contracts the person may see; no file upload or delete; no status change | L2, L4 (entity = person's), L7 to verify | Confidential contract of another entity → refused; record whether Legisway or only Cerbos refuses it (decides H4) |
| 14 | Legisway | Autonomous | Expiry and obligation alerts | Contract metadata only (title, dates, counterparty, entity); no files; no litigation module | L2, L3 (content type = contract), L6, L7 API user | Search on litigation records → guardrail deny; file download → tool absent, and refused for the API user |

### How the tests run

1. A dedicated GitLab CI pipeline, `ai-gateway/validation`, runs the matrix against test environments: SAP QAS, Salesforce sandbox, Vault sandbox, Workday sandbox tenant, and the M-Field, SynerTrade and Legisway test instances.
2. Test identities only: test persons in a test LDAP organisational unit with the roles each row needs, and test agents registered through the normal EasyVista → GitLab path, so agent creation is tested too.
3. Each negative test runs twice: through the gateway (expected: gateway denial) and straight from the MCP server to the target with gateway checks off (expected: target denial). Two denials prove H4.
4. Evidence per test: request, LiteLLM and Cerbos decisions, target response, target audit entry, correlation ID. It is kept as pipeline artefacts and attached to the EasyVista change record, usable as GxP evidence.
5. Last, the kill switch (H6): block one agent per target and confirm no call succeeds after 5 minutes.

Pass rule: a target gets write tools only when H1–H5 pass for it. A target that fails H1 stays out of scope or autonomous-only; one that fails H4 stays read-only.

## Risks and open points

| Risk / limit | Mitigation |
| --- | --- |
| Delegation with `act` in preview (Keycloak 26.8) | Development only; in production trace `sub` + `azp` until it is supported |
| SAP doesn't tell the agent apart natively | Correlation and marking; alias user if required |
| Targets whose API doesn't trust Keycloak (Workday, Legisway, probably SynerTrade, possibly Veeva Vault) | The MCP server bridges with the target's own credentials; delegated writes only where H2 and H4 pass |
| EasyVista CMDB quality | Few mandatory fields, validation, nightly reconciliation |
| Revocation not immediate with local token verification | 5-minute agent tokens, block at the gateway |
| Gateway supply chain (LiteLLM PyPI versions compromised in March 2026) | Images pinned by digest, internal mirror, scanning |
| Pipeline with admin privileges | GitLab ID tokens with a dedicated `aud`, protected branches, mandatory approvals |
| Licences | LiteLLM Enterprise for JWT auth and audit; SAP for any alias users; Salesforce Event Monitoring; Workday ASOR; Legisway API package |

**Open points**

- [ ] NetIQ: Identity Manager only, or Identity Governance too? (decides where approvals live)
- [ ] NetIQ driver for EasyVista: REST or JDBC
- [ ] M-Field APIs with bearer token and logging of `act`
- [ ] SAP IAS trust towards Keycloak and principal propagation rules
- [ ] Salesforce token exchange handler: edition and licences
- [ ] Keycloak federated client authentication with GitLab CI ID tokens
- [ ] CIBA thresholds, approvers and waiting times per process
- [ ] Retention of prompts and responses (GDPR, GxP)
- [ ] SynerTrade: does a usable API exist, and can it act as a named user?
- [ ] Veeva: which Vaults are in scope (PromoMats, QualityDocs, RIM, …), and does an OAuth 2.0 / OpenID Connect profile accept Keycloak?
- [ ] Workday: is Agent System of Record enabled on the tenant, and who reconciles it with EasyVista?
- [ ] Legisway: is the API package licensed, and do API calls carry a named user's rights?

## Delivery waves

Four waves take the design from a controlled MVP to governed scale, and each wave's demo is the gate to the next. The technical flows are proven first on synthetic data, real systems follow, and the governance layer comes last, once the flows work.

&#91;embedded content: delivery waves · 4 waves, 3 demo gates\]

| Wave | Goal | Scope | Team | Demo |
| --- | --- | --- | --- | --- |
| 0 · Foundation (MVP) | A controlled, meaningful demo of the technical flows only | Keycloak, LiteLLM as AI and MCP gateway, one MCP server, one custom target app ending in a user UI; synthetic data | Core team (4) | Before 15 Dec 2026, after one 3-week sprint |
| 1 · Validation | First real integrations; hypotheses H1–H5 on real systems | SAP S/4HANA, M-Field | Core team + 2 | 20 Jan 2027 |
| 2 · Validation 2 | Same approach on more applications | Salesforce, SynerTrade, Veeva Vault, Workday, Legisway | To confirm | 20 Feb 2027 |
| 3 · Scale and control | Governance layer and scale | NetIQ IDM, EasyVista CMDB, GitLab CI pipelines, reconciliation, revocation (H6), HA and DR | To define | To define |

Configuration is code from Wave 0 (Keycloak in Terraform, LiteLLM config in Git), applied by the team by hand. Wave 3 generates the same files through EasyVista → NetIQ IDM → GitLab CI, so nothing built earlier is thrown away.

### Wave 0 — Foundation MVP (before 15 Dec 2026)

**Core team**: 4 people. **Cadence**: one 3-week sprint, closed by the demo release.

The MVP proves, on synthetic data, that a person and two agents reach one custom app through Keycloak and LiteLLM, that the app records who acted and through which agent, and that a forbidden call stops at two layers. It contains only the technical flows: no IDM, no CMDB, no real target system.

**Scope**

| Area | In Wave 0 | Later |
| --- | --- | --- |
| Identity | Keycloak 26.8 in dev, one realm `ai-demo`, synthetic test users | LDAP federation, NetIQ IDM (Wave 3) |
| Gateway | LiteLLM proxy (Enterprise trial, needed for JWT auth): model, MCP gateway, one team per agent, tool permissions, argument guardrail | Cerbos ABAC, CIBA approvals (Wave 1) |
| Target | `demo-crm`, a custom app with API and web UI, seeded with synthetic accounts and visits | SAP and M-Field (Wave 1); five more apps (Wave 2) |
| Agents | Delegated `crm-assistant` (token exchange with `act`) and autonomous `agent-dq` (client credentials) | Agent registry in EasyVista (Wave 3) |
| Configuration | Terraform and YAML in a GitLab repository, applied by the team | GitLab CI pipelines driven by NetIQ IDM (Wave 3) |
| Operations | One Docker Compose stack; logs in LiteLLM and in the app | HA, DR, SIEM (Wave 3) |

`demo-crm` is built like M-Field on purpose: client roles in the Keycloak JWT and the same scope pattern, so Wave 1 moves to M-Field by changing configuration, not code.

**Architecture**

&#91;embedded content: Wave 0 MVP · one compose stack, seven services\]

Luca works only in the demo-crm UI. The assistant acts with his token reduced by Keycloak, `agent-dq` with its own identity, and both reach the app only through LiteLLM and the MCP server; the dashed line is the key set LiteLLM uses to verify tokens.

| Service | Technology | Role in the demo |
| --- | --- | --- |
| `keycloak` | Keycloak 26.8, `start-dev` with the delegation preview features | Users, clients, scope `crm:ai`, token exchange |
| `litellm` | LiteLLM proxy + PostgreSQL + Redis | JWT auth, one team per agent, MCP gateway, tool permissions, logs |
| `demo-crm-ui` | Small web front end | Where every flow ends: accounts, drafts, reminders, “via agent” badges |
| `demo-crm-api` | Python FastAPI + PostgreSQL | The target: validates Keycloak tokens, applies its own roles, records person and agent |
| `demo-crm-mcp` | Python MCP server, streamable HTTP | Six narrow tools that call the API with the user's bearer |
| `crm-assistant` | Python service | Delegated agent: token exchange, then model and tools through LiteLLM |
| `agent-dq` | Python job | Autonomous agent: client credentials, nightly data-quality run |

**The demo, act by act**

| # | What the audience sees | Flow | Proves |
| --- | --- | --- | --- |
| 1 | Luca, a synthetic sales rep, logs in to demo-crm through Keycloak and sees only his territory | Flow 1 | Roles and attributes in the JWT drive the app |
| 2 | Luca asks the assistant for a visit summary and a draft note; the draft appears in the UI with the badge “proposed by agent-crm-assistant for Luca” and waits for his confirmation | Flow 3 + MCP | Delegation; the app sees person and agent (H2, H5) |
| 3 | Luca, also an area manager, asks the assistant for the team report; the app refuses, because the agent's token carries only the rep role | Flow 3 | Keycloak intersection (H2) |
| 4 | The scheduler starts `agent-dq`; reminders appear in the UI tagged “agent-dq (autonomous)” | Flow 2 | Least privilege for the autonomous agent (H3) |
| 5 | The assistant tries a tool outside its list, then a note with status “final”; LiteLLM refuses both | Gateway | Levels 2 and 3 |
| 6 | The same final note is sent straight to the API, bypassing the gateway; the app stores it only as a draft | Direct call | Two independent layers (H4) |
| 7 | The assistant is blocked in LiteLLM and its next call fails; the LiteLLM log shows `sub` and agent for every call | Kill switch | Revocation at the gateway, audit (H5, H6 preview) |

**Act 2 end to end**

&#91;embedded content: act 2 · from the request in the UI to the draft with the agent badge\]

Steps 4–5 are where the gateway can stop the call; step 7 is where the app applies its own roles; the badge in step 9 is the audit trail the person sees.

### Wave 0 — how it is built

Everything lives in one GitLab repository and starts with one command; the seven acts run as a script, so the demo is repeatable.

```text
ai-gateway-mvp/
├── docker-compose.yml
├── keycloak/                # Terraform for realm ai-demo (+ kcadm script for preview settings)
├── litellm/                 # config.yaml, setup-teams.sh
├── demo-crm/                # api/, ui/, seed.py
├── mcp-servers/demo-crm/    # the MCP server
├── agents/crm-assistant/    # delegated agent
├── agents/dq/               # autonomous agent
└── tests/demo-check.sh      # the seven acts, scripted
```

**1. The stack** — one Compose file; `KC_HOSTNAME` keeps the token issuer identical inside and outside the network.

```yaml
# docker-compose.yml (abridged)
services:
  keycloak:
    image: quay.io/keycloak/keycloak:26.8
    command: start-dev --features=token-exchange-delegation,parameterized-scopes
    environment:
      KC_HOSTNAME: http://sso.demo.local:8080
      KC_BOOTSTRAP_ADMIN_USERNAME: admin
      KC_BOOTSTRAP_ADMIN_PASSWORD: ${KC_ADMIN_PASSWORD}
      KC_DB: postgres
      KC_DB_URL: jdbc:postgresql://pg-keycloak/keycloak
    networks: { default: { aliases: [sso.demo.local] } }
  litellm:
    image: ghcr.io/berriai/litellm@sha256:${LITELLM_DIGEST}   # pinned by digest
    command: ["--config", "/app/config.yaml"]
    volumes: ["./litellm/config.yaml:/app/config.yaml:ro"]
    environment:
      DATABASE_URL: postgresql://litellm:${LITELLM_DB_PASSWORD}@pg-litellm/litellm
      REDIS_HOST: redis
      LITELLM_MASTER_KEY: ${LITELLM_MASTER_KEY}
      LITELLM_LICENSE: ${LITELLM_LICENSE}                     # Enterprise trial
      JWT_PUBLIC_KEY_URL: http://sso.demo.local:8080/realms/ai-demo/.well-known/openid-configuration
      JWT_ISSUER: http://sso.demo.local:8080/realms/ai-demo
      JWT_AUDIENCE: litellm-proxy
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY}
  demo-crm-api:  { build: ./demo-crm/api }
  demo-crm-ui:   { build: ./demo-crm/ui, ports: ["3000:3000"] }
  demo-crm-mcp:  { build: ./mcp-servers/demo-crm }
  crm-assistant: { build: ./agents/crm-assistant }
  agent-dq:      { build: ./agents/dq }
  pg-keycloak:   { image: postgres:16 }
  pg-litellm:    { image: postgres:16 }
  pg-crm:        { image: postgres:16 }
  redis:         { image: redis:7 }
```

**2. Keycloak realm** — the M-Field pattern in miniature: one scope `crm:ai` that adds the audiences and admits only the `rep` role, so the manager role can never reach an agent.

```hcl
# keycloak/main.tf (abridged)
resource "keycloak_realm" "demo" {
  realm = "ai-demo"
}

resource "keycloak_openid_client" "demo_crm" {            # login for the UI, audience for the API
  realm_id                   = keycloak_realm.demo.id
  client_id                  = "demo-crm"
  access_type                = "PUBLIC"
  standard_flow_enabled      = true
  pkce_code_challenge_method = "S256"
  valid_redirect_uris        = ["http://crm.demo.local:3000/*"]
}

resource "keycloak_role" "rep" {
  realm_id  = keycloak_realm.demo.id
  client_id = keycloak_openid_client.demo_crm.id
  name      = "rep"
}

resource "keycloak_openid_client_scope" "crm_ai" {
  realm_id               = keycloak_realm.demo.id
  name                   = "crm:ai"
  include_in_token_scope = true
}

resource "keycloak_openid_audience_protocol_mapper" "crm_ai_aud" {   # a second one adds litellm-proxy
  realm_id                 = keycloak_realm.demo.id
  client_scope_id          = keycloak_openid_client_scope.crm_ai.id
  name                     = "aud-demo-crm"
  included_client_audience = "demo-crm"
}

resource "keycloak_generic_role_mapper" "crm_ai_rep_only" {
  realm_id        = keycloak_realm.demo.id
  client_scope_id = keycloak_openid_client_scope.crm_ai.id
  role_id         = keycloak_role.rep.id
}

resource "keycloak_openid_client" "agent_crm_assistant" {
  realm_id                  = keycloak_realm.demo.id
  client_id                 = "agent-crm-assistant"
  access_type               = "CONFIDENTIAL"
  service_accounts_enabled  = true
  full_scope_allowed        = false
  client_authenticator_type = "client-jwt"                 # private_key_jwt, no secret
}
```

The 26.8 preview settings (Standard Token Exchange on the agent client, the FGAP `delegate` permission, the `may-act` client policy) go in a `kcadm` script in the same folder if the Terraform provider doesn't cover them yet. A user-attribute mapper puts `territory` in the token.

**3. LiteLLM** — JWT auth with one team per agent client, the MCP server in `oauth_delegate` mode, and the guardrail that lets agents write notes only as drafts.

```yaml
# litellm/config.yaml
model_list:
  - model_name: claude-sonnet
    litellm_params:
      model: anthropic/claude-sonnet-5-5
      api_key: os.environ/ANTHROPIC_API_KEY

mcp_servers:
  demo_crm:
    url: "http://demo-crm-mcp:8000/mcp"
    transport: "http"
    auth_type: oauth_delegate      # LiteLLM admits the caller, forwards only the upstream bearer

guardrails:
  - guardrail_name: "agents-draft-only"
    litellm_params:
      guardrail: tool_permission
      rules:
        - id: "notes-only-as-draft"
          tool_name: "^demo_crm-draft_visit_note$"
          decision: "allow"
          allowed_param_patterns:
            "status": "^draft$"

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
  enable_jwt_auth: true
  litellm_jwtauth:
    user_id_jwt_field: "sub"          # the person (delegated) or the service account (autonomous)
    team_alias_jwt_field: "azp"       # one LiteLLM team per agent client
    agent_id_jwt_field: "azp"
```

```bash
# litellm/setup-teams.sh: each agent sees only its own tools
curl -s -X POST "$LITELLM_URL/team/new" -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H "Content-Type: application/json" -d '{
  "team_alias": "agent-crm-assistant", "models": ["claude-sonnet"],
  "object_permission": {"mcp_servers": ["demo_crm"], "mcp_tool_permissions": {"demo_crm":
    ["search_accounts", "get_account_summary", "list_visits", "draft_visit_note"]}}}'

curl -s -X POST "$LITELLM_URL/team/new" -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H "Content-Type: application/json" -d '{
  "team_alias": "agent-dq", "models": ["claude-sonnet"],
  "object_permission": {"mcp_servers": ["demo_crm"], "mcp_tool_permissions": {"demo_crm":
    ["list_incomplete_visits", "create_reminder"]}}}'
```

**4. The target app** — demo-crm trusts only Keycloak: it checks issuer, audience and signature, reads its own roles, and records who acted and through which agent. The rule “agents only draft” lives here too, which is what act 6 proves.

```python
# demo-crm/api/auth.py
import jwt                                   # PyJWT
from fastapi import HTTPException, Request

ISSUER = "http://sso.demo.local:8080/realms/ai-demo"
jwks = jwt.PyJWKClient(f"{ISSUER}/protocol/openid-connect/certs")

def caller(request: Request) -> dict:
    token = request.headers.get("authorization", "").removeprefix("Bearer ")
    try:
        key = jwks.get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=["RS256"], audience="demo-crm", issuer=ISSUER)
    except jwt.PyJWTError:
        raise HTTPException(401, "invalid token")
    act, azp = claims.get("act") or {}, claims.get("azp", "")
    return {
        "user": claims.get("preferred_username", claims["sub"]),
        "roles": claims.get("resource_access", {}).get("demo-crm", {}).get("roles", []),
        "territory": claims.get("territory"),
        "agent": act.get("client_id") or (azp if azp.startswith("agent-") else None),
        "correlation_id": request.headers.get("x-correlation-id"),
    }
```

```python
# demo-crm/api/notes.py
@app.post("/notes")
def create_note(body: NoteIn, who: dict = Depends(caller)):
    if "rep" not in who["roles"]:
        raise HTTPException(403, "role rep required")
    status = "draft" if who["agent"] else body.status       # agents never write final notes
    return notes.insert(body, status=status, created_by=who["user"],
                        via_agent=who["agent"], correlation_id=who["correlation_id"])
```

**5. The MCP server** — narrow tools, no free queries; each tool passes on the user's bearer that LiteLLM forwards.

```python
# mcp-servers/demo-crm/server.py
import httpx
from mcp.server.fastmcp import FastMCP, Context

mcp = FastMCP("demo-crm", host="0.0.0.0", port=8000)
API = "http://demo-crm-api:8080"

def _headers(ctx: Context) -> dict:
    req = ctx.request_context.request                     # the HTTP request from LiteLLM
    return {"authorization": req.headers["authorization"],  # upstream bearer (oauth_delegate)
            "x-correlation-id": req.headers.get("x-correlation-id", "")}

@mcp.tool()
async def draft_visit_note(account_id: str, text: str, status: str = "draft", ctx: Context = None) -> dict:
    """Save a visit note as a draft; the rep confirms it in the demo-crm UI."""
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{API}/notes", headers=_headers(ctx),
                              json={"account_id": account_id, "text": text, "status": status})
    r.raise_for_status()
    return {"note_id": r.json()["id"], "status": r.json()["status"]}

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
```

**6. The delegated agent** — exchanges Luca's token for a delegated one, then calls the tools through LiteLLM; model calls use the same token on `/v1/chat/completions`.

```python
# agents/crm-assistant/delegate.py
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

TOKEN_URL = "http://sso.demo.local:8080/realms/ai-demo/protocol/openid-connect/token"

def delegated_token(user_token: str, agent_token: str, assertion: str) -> str:
    r = httpx.post(TOKEN_URL, data={
        "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
        "subject_token": user_token,
        "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
        "actor_token": agent_token,
        "actor_token_type": "urn:ietf:params:oauth:token-type:access_token",
        "client_id": "agent-crm-assistant",
        "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
        "client_assertion": assertion,                  # signed with the agent's private key
        "scope": "crm:ai",
    })
    r.raise_for_status()
    return r.json()["access_token"]                    # sub = Luca, act.client_id = agent-crm-assistant

async def call_tool(token: str, correlation_id: str, name: str, args: dict):
    headers = {"x-litellm-api-key": token,              # admission at the gateway (to verify in week 1)
               "Authorization": f"Bearer {token}",      # upstream bearer, aud includes demo-crm
               "x-correlation-id": correlation_id}
    async with streamablehttp_client("http://litellm:4000/demo_crm/mcp", headers=headers) as (r, w, _):
        async with ClientSession(r, w) as session:
            await session.initialize()
            return await session.call_tool(name, args)
```

**7. Synthetic data** — a fixed seed, so every run of the demo shows the same accounts.

```python
# demo-crm/seed.py
from faker import Faker

fake = Faker("it_IT")
Faker.seed(42)
TERRITORIES = ["NORTH", "CENTRE", "SOUTH"]

accounts = [{
    "id": f"ACC-{i:05d}",
    "name": f"Dr. {fake.last_name()}",
    "specialty": fake.random_element(["cardiology", "nephrology", "general practice"]),
    "city": fake.city(),
    "territory": TERRITORIES[i % 3],
} for i in range(300)]
# + 1,500 visits, 20% with missing fields so agent-dq has work to do
```

### Wave 0 — sprint plan and done criteria

The sprint runs from Monday 23 November to Friday 11 December, with the demo release on Monday 14 December. Tuesday 8 December is a public holiday, so week 3 has four working days.

| Week | Dates | Deliverables | Done when |
| --- | --- | --- | --- |
| 1 | 23–27 Nov | Compose stack; Keycloak realm as code; LiteLLM with JWT auth and one model; demo-crm API with token check and seeded data | A test user's token is accepted by LiteLLM and demo-crm; a token with the wrong `aud` is refused |
| 2 | 30 Nov–4 Dec | MCP server with six tools; UI with badges; `agent-dq`; `crm-assistant` with token exchange | Acts 1, 2 and 4 run end to end |
| 3 | 7–11 Dec (8 Dec holiday) | Tool permissions and guardrail; direct-call test; kill switch; scripted negative tests; demo script and rehearsal | All seven acts pass from a clean `docker compose up` |
| Release | Mon 14 Dec | Demo to stakeholders; recording and evidence kept | Demo held before 15 Dec |

**Definition of done**

- [ ] One command builds the stack from scratch; the seed is deterministic.
- [ ] `tests/demo-check.sh` runs the seven acts and passes, including the four negative ones (acts 3, 5, 6, 7).
- [ ] Only synthetic data; no static secret in agent code (keys generated at setup, never committed).
- [ ] Every call appears in the LiteLLM logs with `sub` and agent; every demo-crm record carries `created_by` and `via_agent`.
- [ ] Images pinned by digest.

**Risks to settle in week 1**

| Risk | Check | Fallback |
| --- | --- | --- |
| Keycloak 26.8 delegation is a preview | Token exchange with `act` works on the dev image | Standard token exchange, agent identified by `azp` (the production fallback already planned) |
| LiteLLM accepts a Keycloak JWT as the admission credential in `oauth_delegate` mode | First call to `/demo_crm/mcp` with the JWT in `x-litellm-api-key` | `mcp_jwt_signer`, with demo-crm-mcp trusting LiteLLM's key for the MCP hop only |
| Correlation ID reaching the MCP server | Which request headers LiteLLM forwards | Pass it as a tool argument |
| JWT auth and audit are Enterprise features | Trial licence requested this week | None: required for the demo |
| Model access from the demo environment | Network route and API key approved | The model through SAP AI Core, if already reachable |

### Wave 1 — Validation: SAP and M-Field (demo 20 Jan 2027)

**Team**: core team + 2.

Wave 1 swaps the demo app for two real systems and keeps the same flows: use cases 1 and 2, rows 1–4 of the test matrix, on test environments.

| Workstream | What changes from Wave 0 | Done when |
| --- | --- | --- |
| M-Field | Scopes `mfield:ai-read` and `mfield:ai-write` on the corporate Keycloak (test); MCP server `m-field` ported from demo-crm-mcp; M-Field logs `act.client_id` | Use case 2, A and B, runs; rows 3–4 pass |
| SAP S/4HANA | Technical user `AI_PO_MON` with a display role (autonomous); principal propagation through SAP IAS and Cloud Connector (delegated) | Use case 1, A and B, runs on QAS; rows 1–2 pass |
| Policy | Cerbos behind the LiteLLM guardrail; CIBA for orders above €5,000 | The €12,000 order waits for approval |
| Validation | `ai-gateway/validation` pipeline in GitLab CI runs rows 1–4, each through the gateway and directly | H1–H5 status set for SAP and M-Field |

**Request during Wave 0**: these have lead times and the Christmas break (24 Dec–6 Jan) leaves about three and a half working weeks before the demo.

- [ ] SAP IAS trust towards Keycloak, and Cloud Connector for QAS
- [ ] SAP QAS technical user and display role (`Z_AI_PO_DISPLAY`)
- [ ] M-Field test environment whose API accepts bearer tokens
- [ ] Test users with M-Field and SAP roles in the corporate test realm

### Wave 2 — Validation 2: five more applications (demo 20 Feb 2027)

**Team**: to confirm (assumed: the Wave 1 team).

Same approach, extended to Salesforce, SynerTrade, Veeva Vault, Workday and Legisway: rows 5–14 of the test matrix. The riskiest hypotheses are tested in the first week, so an application that fails H1 leaves the wave early instead of at the demo.

| Week 1 check | Application | If it fails |
| --- | --- | --- |
| The OAuth 2.0 / OpenID Connect profile accepts Keycloak tokens | Veeva Vault | Autonomous only, with an integration user |
| A usable API exists and can act as a named user | SynerTrade | Out of the wave, or read-only through SAP data |
| API calls carry a named user's rights | Legisway | Delegated mode only for reads filtered by the MCP server |
| Agent System of Record is enabled on the tenant | Workday | Integration system user, autonomous only |
| Token exchange handler available in the edition | Salesforce | Integration user per agent |

Prerequisites: Salesforce sandbox with Event Monitoring, Veeva Vault sandbox, Workday sandbox tenant with ASOR, Legisway API package, SynerTrade test instance. 20 Feb 2027 is a Saturday: confirm Friday 19 or Monday 22 February.

### Wave 3 — Scale and control: the governance layer

**Team and dates**: to define.

Wave 3 replaces the hand-applied configuration of Waves 0–2 with the governed path described in *How an agent is born*, and makes the platform ready for production.

- EasyVista: CI class “AI Agent”, request and approval workflow.
- NetIQ IDM: driver for EasyVista, non-human identities and groups in eDirectory; LDAP federation in Keycloak.
- GitLab CI: `validate`, `plan`, `apply`, `verify`, `report` on `identity-config` and `ai-gateway`; the files written by hand in Waves 0–2 become generated ones.
- Nightly reconciliation of the five lists; renewals and retirement.
- Revocation end to end (H6) on every target; emergency runbook.
- HA and DR for Keycloak and LiteLLM, SIEM integration, load test.
- Go-live criteria: H1–H6 passed per target, penetration test, DPIA, security review.

## Critical review

The design holds because it extends what the company already runs: Keycloak is the SSO of all seven targets, NetIQ IDM is the single engine, Cerbos does fine-grained authorization. The weak points are LiteLLM as a single trust point, a slow revocation path, and three blind spots.

**What holds**

- **Keycloak follows the standards.** 26.7 added an AuthZEN endpoint, MCP server authorization, token exchange delegation (experimental) and the receiving side of ID-JAG (experimental). The issuing side of ID-JAG is not built yet. ([release notes](https://www.keycloak.org/2026/07/keycloak-2670-released))
- **Cerbos is a safe bet.** AuthZEN Authorization API 1.0 became an OpenID Final Specification in January 2026, and Cerbos co-chairs the working group. If the gateway calls Cerbos only through AuthZEN, both gateway and policy engine stay replaceable. ([OpenID](https://openid.net/authorization-api-1-0-final-specification-approved/))
- **Registry plus IDM matches the market.** ServiceNow AI Passport grounds agent identity in CMDB business context, the same idea as EasyVista as agent registry. SailPoint extends ownership, lifecycle and certification to agents rather than adding a new product.

**Weak points**

| # | Weakness | Why it matters | Fix |
| --- | --- | --- | --- |
| 1 | LiteLLM is the single trust point | Malicious PyPI releases 1.82.7 and 1.82.8 in March 2026 stole credentials from CI pipelines ([LiteLLM](https://docs.litellm.ai/blog/security-update-march-2026)); a second compromise (v1.107.0) was reported on 21 Oct 2026, to confirm. The gateway holds every model and MCP credential. | Images pinned by digest from a private mirror, secrets in a vault, egress allow-list, no authorization logic in LiteLLM so it can be swapped |
| 2 | Revocation path too slow | EasyVista → NetIQ → LDAP → GitLab CI → Keycloak/LiteLLM suits normal changes, not a misbehaving agent | Direct kill switch: disable the Keycloak client and revoke the LiteLLM key in one action; short token lifetimes |
| 3 | Token passthrough | The MCP authorization spec (2026-07-28) requires audience-bound tokens and forbids passthrough | Drop LiteLLM passthrough modes; token exchange per MCP server audience |
| 4 | NetIQ agent features unproven | OpenText claims NHI and AI agent governance, but no agent-specific feature (sponsor, recertification, templates) is documented; LDAP is a poor home for owner, purpose, risk tier, allowed tools | Keep agent metadata in EasyVista and carry it into token claims; verify NetIQ on our version |

**Blind spots**

- **Shadow agents**: nothing discovers Claude Desktop, Copilot Studio or local MCP servers.
- **SaaS-native agents**: Agentforce, SAP Joule and Workday agents call their own platforms directly, so the gateway never sees them.
- **Agent credentials**: agents still use client secrets; private\_key\_jwt or workload identity (GitLab ID tokens, Kubernetes service-account tokens, SPIFFE) removes them.

## Market landscape

Enterprises combine products from several layers; no single vendor covers all of them. Our stack maps one open-source or existing product to each layer.

| Layer | Enterprise vendors | Our stack |
| --- | --- | --- |
| Agent identity (IdP) | Microsoft Entra Agent ID (GA 2026), Okta for AI Agents + Agent SSO + Agent Gateway, Ping, Google Cloud Agent Identity, Auth0 for MCP | Keycloak |
| Governance and lifecycle (IGA) | SailPoint Agentic Fabric, Saviynt Identity Security for AI, OpenText NetIQ, One Identity, Omada, ServiceNow AI Passport, midPoint (open source) | NetIQ IDM + EasyVista |
| Privileged access and secrets | Palo Alto Networks Idira (former CyberArk), Delinea, HashiCorp Vault, Aembit (workload IAM) | GitLab ID tokens; vault to decide |
| Discovery and posture | Astrix, Oasis, Orchid, Silverfort (Gartner "guardian agents" category, Feb 2026) | None |
| Fine-grained authorization | Cerbos, OPA, OpenFGA/SpiceDB, PlainID, Axiomatics, Permit.io MCP Gateway | Cerbos |
| AI and MCP gateway | LiteLLM, Kong AI Gateway, Portkey (Palo Alto Networks, Prisma AIRS), TrueFoundry, Gravitee (Cedar subset), solo.io agentgateway (ID-JAG), AWS AgentCore Gateway, Okta Agent Gateway | LiteLLM |

Vendors implement different subsets of emerging specifications (ID-JAG, AIMS, WIMSE), so no stack is yet sure to interoperate with the others ([Forkast](https://forkast.news/six-vendors-are-shipping-agent-identity-products-the-ietf-has-not-finished-the-standard/)). Sources: [Speakeasy vendor comparison](https://www.speakeasy.com/blog/best-ai-agent-identity-vendors), [Saviynt](https://saviynt.com/blog/identity-security-for-ai), [Futurum on SailPoint](https://futurumgroup.com/insights/sailpoint-bets-on-identity-to-govern-ai-agents-at-navigate-2026/), [Permit.io](https://www.permit.io/blog/announcing-permit-mcp-gateway), [agentgateway ID-JAG](https://aaif.io/blog/agentgateway-now-supports-id-jag-and-mcp-enterprise-managed-auth).

## Standards and recommended changes

The plan stays; five changes make it hold as the standards settle.

**Standards to track**

| Standard | What it does | Status |
| --- | --- | --- |
| ID-JAG / MCP Enterprise-Managed Authorization | The enterprise IdP authorizes access to MCP servers across domains | IETF draft; Keycloak receiver side experimental in 26.7 ([AAIF](https://aaif.io/blog/implementing-enterprise-managed-mcp-authorization-in-keycloak)) |
| AuthZEN Authorization API 1.0 | Standard PEP → PDP call (gateway → Cerbos) | OpenID Final, Jan 2026; COAZ-MCP binding and approval profile are drafts |
| WIMSE / SPIFFE | Workload identity for agents, no static secrets | IETF work in progress |
| AI Agent Authentication and Authorization | Profiles OAuth, WIMSE and SPIFFE for agents | Individual draft, not adopted ([datatracker](https://datatracker.ietf.org/doc/draft-klrc-aiagent-auth/)) |
| NIST NCCoE agent identity | Practice guide on identity standards for agents | Concept paper 2026, guide to follow |

**Recommended changes**

1. Harden LiteLLM's supply chain and keep authorization out of it (AuthZEN to Cerbos), so the gateway is replaceable.
2. Add a direct kill switch for agents, outside the IDM sync chain.
3. Replace token passthrough with per-audience token exchange.
4. Run a NetIQ proof on agent lifecycle (sponsor, recertification, deprovisioning) before Wave 3.
5. Assess a discovery tool and a policy for SaaS-native agents (Agentforce, Joule, Workday) before Wave 2.

# Technical annexes

The annexes hold the detail of the OAuth flows (HTTP requests and token examples) and the operating notes on token verification and scalability; the body of the document refers here.

## OAuth flows 1–2: people and autonomous agents

All flows follow OAuth 2.1: PKCE mandatory for public clients, no implicit or password grant, exact redirect URIs, short-lived tokens. In Keycloak the OAuth 2.1 client policy profiles are enabled on every client.

### Flow 1 — A person's SSO login (Authorization Code + PKCE)

Used by the corporate chat, the LiteLLM Admin UI, web portals.

1. The client generates a random `code_verifier` and `code_challenge = BASE64URL(SHA256(code_verifier))`.
2. Browser redirect to Keycloak:

```http
GET /realms/acme/protocol/openid-connect/auth
  ?response_type=code
  &client_id=ai-chat
  &redirect_uri=https://chat.acme.it/oauth/callback
  &scope=openid profile email
  &state=<random>
  &code_challenge=<challenge>
  &code_challenge_method=S256
```

3. Keycloak authenticates: password checked against LDAP (federation) or redirect to Google (brokering, with `kc_idp_hint=google` to skip the choice). MFA mandatory for admin roles.
4. Keycloak resolves groups and roles (only `AI-*`), applies the mappers and returns the `code` to the redirect URI.
5. The client exchanges the code:

```http
POST /realms/acme/protocol/openid-connect/token
Content-Type: application/x-www-form-urlencoded

grant_type=authorization_code
&code=<code>
&redirect_uri=https://chat.acme.it/oauth/callback
&client_id=ai-chat
&code_verifier=<verifier>
```

6. Response: access token (5–15 min, `aud=litellm-proxy`), ID token, refresh token with rotation.
7. The client calls LiteLLM with `Authorization: Bearer <access token>`; LiteLLM verifies the token (see Token verification) and creates the user on first access.

Example access token:

```json
{
  "iss": "https://sso.acme.it/realms/acme",
  "aud": ["litellm-proxy"],
  "sub": "7c1e…9a2",
  "azp": "ai-chat",
  "email": "maria.rossi@acme.it",
  "resource_access": { "litellm-proxy": { "roles": ["ai-user", "rd-team"] } },
  "scope": "openid profile email",
  "exp": 1763400000
}
```

### Flow 2 — Autonomous agent (Client Credentials, no shared secrets)

Used by batch agents and pipelines. Two client authentication variants, both without static secrets:

- **`private_key_jwt`**: the agent signs an assertion with its own private key (in a secret manager or HSM); Keycloak knows only the public key.
- **Federated client authentication** (supported since Keycloak 26.6): on Kubernetes the agent presents its own ServiceAccount token as the assertion; no key to manage.

```http
POST /realms/acme/protocol/openid-connect/token
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials
&client_id=agent-regulatory-doc
&client_assertion_type=urn:ietf:params:oauth:client-assertion-type:jwt-bearer
&client_assertion=<signed JWT: iss=sub=client_id, aud=token endpoint, jti, short exp>
&scope=models:sonnet mcp:doc-repo:read
```

Response: a 5-minute access token only, no refresh token. In the token `sub` is the service account, `azp` is the agent, and `scope` holds only the scopes requested and allowed. LiteLLM identifies the registered agent from the `azp` claim (`agent_id_jwt_field`) and applies its team, budget and MCP permissions.

## OAuth flow 3: user → agent delegation

The agent obtains a token in which the user stays the subject (`sub`) and the agent appears as the actor (`act`): it can do at most what the user can do, and only with the user's consent. In Keycloak 26.8 delegation is a preview: fine for development, to be reassessed before production.

&#91;embedded content: user → agent delegation · 9 steps\]

Dashed arrows are tokens returned by Keycloak; step 7 is the delegated token, with the user as `sub` and the agent in `act`.

**Prerequisites in Keycloak**

1. Server started with the `token-exchange-delegation` and `parameterized-scopes` features.
2. Agent client (`agent-helpdesk`): confidential, service account on, Standard Token Exchange on; scopes and audiences only towards the resources it must reach.
3. User login client (`ai-chat`): “Consent required” on.
4. Fine-grained admin permissions v2: `delegate` permission on users (or `delegate-members` on specific groups) bound to the agent client. Without it, Keycloak silently drops the scope.
5. Client policy with the `may-act` executor; on clients outside the agent flow, the option that rejects any `may_act`.

**Steps**

1. The user signs in to the app (Flow 1) also requesting `delegation:client:agent-helpdesk`; Keycloak shows the consent screen.
2. The user's token contains `may_act` with the agent's `sub` and `client_id`.
3. The app passes the user's token to the agent when it hands over the task.
4. The agent obtains its own token (Flow 2).
5. The agent performs the token exchange:

```http
POST /realms/acme/protocol/openid-connect/token
Content-Type: application/x-www-form-urlencoded

grant_type=urn:ietf:params:oauth:grant-type:token-exchange
&subject_token=<user's access token>
&subject_token_type=urn:ietf:params:oauth:token-type:access_token
&actor_token=<agent's access token>
&actor_token_type=urn:ietf:params:oauth:token-type:access_token
&client_id=agent-helpdesk
&client_assertion_type=urn:ietf:params:oauth:client-assertion-type:jwt-bearer
&client_assertion=<JWT signed by the agent>
```

6. Keycloak checks consent, the FGAP permission and `may_act`, and returns the delegated token:

```json
{
  "iss": "https://sso.acme.it/realms/acme",
  "sub": "7c1e…9a2",
  "email": "luca.bianchi@acme.it",
  "aud": ["litellm-proxy"],
  "act": { "sub": "service-account-agent-helpdesk", "client_id": "agent-helpdesk" },
  "scope": "mcp:ticketing:create",
  "exp": 1763400300
}
```

7. The agent calls LiteLLM with the delegated token; LiteLLM logs the user (`sub`) and the agent (`act.client_id`), and Cerbos decides on both.

**Design constraints**

- Access token only: no refresh and no session; when it expires the agent repeats the exchange.
- Revoking the original token doesn't revoke tokens already exchanged: keep tokens short.
- A token that already holds delegation claims can't be exchanged again: no agent → sub-agent chains.
- Consent isn't persisted: it is renewed at every login session.
- Keycloak validates only `sub`, `client_id` and `iss` inside `may_act`; Cerbos must decide on these alone.

## OAuth flows 4–5: MCP

The MCP client authenticates to the gateway with Keycloak; the gateway then talks to each MCP server in the way that suits that server, never blindly forwarding the token it received.

### Flow 4 — Interactive MCP client to the gateway (MCP authorization)

Used by Claude Code, IDEs and other MCP clients.

1. The client calls the gateway's MCP endpoint without a token and gets `401` with `WWW-Authenticate: Bearer resource_metadata="https://ai-gw.acme.it/.well-known/oauth-protected-resource/..."`.
2. The client reads the Protected Resource Metadata (RFC 9728), which names Keycloak as the authorization server.
3. The client reads Keycloak's metadata (`/.well-known/openid-configuration`).
4. Client registration: a public client pre-registered in Keycloak, or a Client ID Metadata Document (CIMD), covered by the Keycloak 26.6 MCP guide.
5. Authorization Code + PKCE as in Flow 1, in the user's browser.
6. Token with `aud=litellm-proxy`; the client uses it on every MCP request.

To verify on the LiteLLM version in use: which Protected Resource Metadata the gateway exposes when the authorization server is Keycloak, and whether Keycloak honours the `resource` parameter (RFC 8707) or the audience must be fixed with an audience mapper.

### Flow 5 — From the gateway to the MCP servers

LiteLLM admits the request (valid token, team, MCP permissions, Cerbos), then calls the MCP server. Three modes, chosen per server:

| Mode | When | How it works |
| --- | --- | --- |
| JWT signed by LiteLLM (`mcp_jwt_signer`) | Default for internal MCP servers | LiteLLM verifies the incoming token and signs its own short RS256 JWT (`aud=mcp`, TTL 300 s) with the verified claims; the MCP server checks LiteLLM's JWKS |
| Separate delegated bearer (`oauth_delegate`) | The target must see the user (M-Field, SAP) | LiteLLM admits the call with its own token and forwards a second bearer, with the target's audience, that the client obtained from Keycloak; spend and rate limits stay in LiteLLM |
| ID-JAG (`oauth2_id_jag`) | MCP servers with their own authorization server (SaaS) | The exchange goes through the IdP that applies the policy; experimental in Keycloak, to use once supported |

Shared rules:

- MCP servers are reachable only from the gateway (NetworkPolicy).
- LiteLLM's JWT uses its own signing key in production, not the one generated at startup.
- The original Keycloak token is never forwarded to internal servers: this prevents replay against other resources.

## Flows 9–10: human approval and revocation

### Flow 9 — Human approval with CIBA

When Cerbos denies an action for lack of approval (e.g. a SAP order above threshold), the agent asks a person for the go-ahead through Keycloak, which delivers the request on another device.

1. The agent sends the CIBA request, authenticating as a client:

```http
POST /realms/acme/protocol/openid-connect/ext/ciba/auth
Content-Type: application/x-www-form-urlencoded

client_id=agent-procurement
&client_assertion_type=urn:ietf:params:oauth:client-assertion-type:jwt-bearer
&client_assertion=<signed JWT>
&scope=openid mcp:sap:write
&login_hint=purchasing.manager@acme.it
&binding_message=Order EUR 12000 supplier X - ref. 4711
```

2. Keycloak replies with an `auth_req_id` and calls the endpoint of the configured authentication channel (an external service: Teams bot, mobile app or web page).
3. The approver approves or rejects; the channel reports the outcome to Keycloak's CIBA callback.
4. The agent polls the token endpoint until the outcome is available:

```http
POST /realms/acme/protocol/openid-connect/token

grant_type=urn:openid:params:grant-type:ciba
&auth_req_id=<id>
&client_id=agent-procurement
&client_assertion_type=urn:ietf:params:oauth:client-assertion-type:jwt-bearer
&client_assertion=<signed JWT>
```

5. With the approval, the agent repeats the call presenting the approval token; the guardrail verifies it and passes it to Cerbos as an attribute.

**Design point**: the `binding_message` doesn't end up in the token. To bind the approval to that specific action, the channel service records the approval with a hash of the request (amount, supplier, reference), and the guardrail compares it before calling Cerbos. Endpoints and mode (poll) to verify on version 26.8.

### Flow 10 — Revocation and kill switch

| Event | Actions | Effect |
| --- | --- | --- |
| Compromised agent | Agent/team blocked in LiteLLM; deny rule in Cerbos; client disabled in Keycloak and key rotated; technical identities on the targets disabled (SAP user, Salesforce integration user, Workday agent account, …) | Immediate block at the gateway; no new tokens; issued tokens expire within 5 minutes |
| Person leaving the company | Disabled in LDAP; Keycloak sessions logged out; NetIQ IDM reassigns the agents they sponsored to their manager | No new logins or delegations |
| Assignment expired or not recertified | NetIQ IDM removes the group/role; GitLab CI propagates to Keycloak, LiteLLM, Cerbos and targets | Permission removed from Keycloak, LiteLLM, Cerbos, targets |

The block at the gateway is the immediate action; all the others close the remaining paths. Actions start from EasyVista/NetIQ IDM or from an emergency runbook, both traced.

## Token verification and key management

LiteLLM verifies every token locally, without calling Keycloak on each request: this is what takes Keycloak off the critical path.

**What LiteLLM checks**

1. Reads the `kid` from the JWT header and takes the key from Keycloak's JWKS (via discovery), cached for `public_key_ttl` (default 600 s), in Redis if configured.
2. Verifies the signature and `exp`.
3. Verifies `iss` and `aud`, but only if `JWT_ISSUER` and `JWT_AUDIENCE` are set. Always set them, otherwise a valid signature from any client in the realm is enough.
4. Maps the claims to user, team, role and agent; applies permissions, budget and Cerbos.

```bash
JWT_PUBLIC_KEY_URL=https://sso.acme.it/realms/acme/.well-known/openid-configuration
JWT_ISSUER=https://sso.acme.it/realms/acme
JWT_AUDIENCE=litellm-proxy
```

**Key rotation in Keycloak**: an unknown `kid` doesn't force a cache refresh before expiry. Procedure: add the new key as passive, wait longer than `public_key_ttl`, then activate it; the old key stays passive until the tokens it signed have expired.

**Keycloak unreachable**: LiteLLM retries, then uses the last valid copy of the keys up to `public_key_ttl + public_key_stale_ttl` (default 600 + 3600 s); beyond that it returns 503. With `public_key_stale_ttl: 0` the behaviour becomes fail-closed. Decide this explicitly.

**Revocation**: local verification doesn't see revocations; a token stays valid until `exp`. That's why agent tokens last 5 minutes and the kill switch is the block at the gateway.

**Keys to manage**

| Key | Where | Rotation |
| --- | --- | --- |
| Keycloak realm signing keys | Keycloak (HSM or keystore) | Passive → active procedure |
| Agents' private keys (`private_key_jwt`) | Secret manager or HSM; none with Kubernetes federation | Per agent, automatic from the pipeline |
| LiteLLM MCP signing key | Secret manager | Published in LiteLLM's JWKS |
| LiteLLM master key and salt key | Secret manager | Master key rotatable; salt key never changed after startup |
| SAP AI Core service key | Secret manager | Per SAP BTP policy |
| Credentials issued by targets (Workday API client, Legisway API user, SynerTrade and Veeva integration users) | Secret manager, read only by the MCP server of that target | Per target policy, rotated by the pipeline |

Mandatory negative tests: expired token, wrong audience, different issuer, tampered signature, delegated token exchanged again. All must be rejected.

## Scalability and database

The solution scales horizontally because the gateway holds no state and verifies tokens itself; the real bottlenecks are LiteLLM's database, the LLM providers' limits and the capacity of the MCP servers.

| Layer | How it scales |
| --- | --- |
| LiteLLM | 1 worker per pod, HPA, stateless pods behind a load balancer |
| Keycloak | Cluster with distributed cache, multi-site for DR; involved only when tokens are issued and renewed |
| Cerbos | Sidecar in the LiteLLM pod: scales with the replicas, decisions without a network hop |
| EasyVista and NetIQ IDM | Outside the critical request path |
| Governance | Permissions on archetypes and attributes: rules grow with agent types, not with the number of agents |
| Organisation | New BU = groups in NetIQ IDM + LiteLLM team from GitLab CI, no restarts |

**LiteLLM database**

Each pod opens its own pool: total connections = `database_connection_pool_limit` × workers per pod × autoscaler max replicas.

| Lever | Configuration |
| --- | --- |
| Pool sized on the maximum | `database_connection_pool_limit` = DB max connections / (maxReplicas × workers) |
| Batched writes | `proxy_batch_write_at: 60` |
| Redis buffer at high traffic | `use_redis_transaction_buffer: true` above \~1,000 RPS or 10+ instances |
| Less data in the DB | `disable_error_logs: True` + retention of spend logs |
| Separate reads | `DATABASE_URL_READ_REPLICA` |
| Separate jobs | `LITELLM_JOB_ROLE=serving` on serving pods + one `worker` pod |
| Migrations | Dedicated job + `DISABLE_SCHEMA_UPDATE=true` on the pods |
| TLS | `sslmode=verify-full` in `DATABASE_URL` |

PgBouncer isn't covered by LiteLLM's documentation: if needed, validate it with Prisma. Keycloak has its own PostgreSQL database, sized separately. No throughput figure is guaranteed: measure it with a load test on the real infrastructure.

## Sources

- [Keycloak 26.6 — release notes (Workflows, federated client authentication, JWT Authorization Grant)](https://www.keycloak.org/docs/26.6.4/release_notes/)
- [Keycloak 26.8 — token exchange delegation for AI agents (Skycloak)](https://skycloak.io/blog/keycloak-26-8-token-exchange-delegation-ai-agents/)
- [Keycloak — Identity Assertion JWT Authorization Grant (experimental)](https://www.keycloak.org/nightly/securing-apps/identity-assertion-jwt-authorization-grant)
- [LiteLLM — JWT configuration reference](https://docs.litellm.ai/docs/proxy/jwt_auth_reference)
- [LiteLLM — MCP Permission Management](https://docs.litellm.ai/docs/mcp_control)
- [LiteLLM — Grant MCP access to keys and teams](https://docs.litellm.ai/docs/mcp_grant_access)
- [LiteLLM — Tool Permission Guardrail](https://docs.litellm.ai/docs/proxy/guardrails/tool_permission)
- [LiteLLM — MCP Guardrails](https://docs.litellm.ai/docs/mcp_guardrail)
- [LiteLLM — MCP Zero Trust (JWT Signer)](https://docs.litellm.ai/docs/mcp_zero_trust)
- [LiteLLM — Production Best Practices](https://docs.litellm.ai/docs/proxy/prod)
- [LiteLLM — SAP Generative AI Hub](https://docs.litellm.ai/docs/providers/sap)
- [Cerbos — LiteLLM and MCP at the gateway](https://www.cerbos.dev/blog/secure-ai-agents-mcp-tools-at-the-gateway-lite-llm-cerbos)
- [GitLab — OIDC with ID tokens in CI/CD jobs](https://docs.gitlab.com/ee/ci/secrets/id_token_authentication.html)
- [NetIQ Identity Manager — REST driver](https://www.netiq.com/documentation/identity-manager-47-drivers/generic_rest/toclink.html)
- [NetIQ Identity Manager — JDBC driver](https://www.netiq.com/documentation/identity-manager-48-drivers/jdbc/data/netiq-identity-manager-driver-for-jdbc.html)
- [EasyVista Service Manager — API connector](https://learn.microsoft.com/en-us/connectors/easyvistaservicemana)
- [Salesforce — OAuth 2.0 token exchange handler](https://developer.salesforce.com/docs/atlas.en-us.apexcode.meta/apexcode/token_exchange_handler.htm)
- [SAP — Cloud Connector for principal propagation](https://learning.sap.com/learning-journeys/Setting-Up-SAP-Build-Work-Zone-standard-edition-and-SAP-Mobile-Start-with-SAP-S-4HANA/setting-up-cloud-connector-for-principal-propagation)
- [Veeva Vault — Configuring OAuth 2.0 / OpenID Connect profiles](https://platform.veevavault.help/en/lr/43329/)
- [Veeva Vault API — Client ID](https://general.veevavault.dev/vault-api/references/client-id/)
- [Veeva Vault API — Download Daily API Usage (log not designed for auditing)](https://limited.veevavault.dev/vault-api/api-reference/26.2/logs/download-daily-api-usage/)
- [Workday — Configure external agents (Agent System of Record)](https://doc.workday.com/admin-guide/en-us/workday-ai/agents/agent-system-of-record/external-agents/configure-external-agents.html)
- [Workday — Setup considerations, Agent System of Record](https://doc.workday.com/admin-guide/en-us/workday-ai/agents/agent-system-of-record/agent-management/setup-considerations--agent-system-of-record.html)
- [Legisway — API integrations](https://wolterskluwer.com/en/solutions/legisway/integrations)
- [Legisway — packages and API access](https://www.wolterskluwer.com/en/solutions/legisway/pricing-plans)
- SynerTrade API availability — sources disagree: [GetApp listing](https://www.getapp.com/operations-management-software/a/synertrade-accelerate/), [Makini connector page](https://www.makini.io/integrations/synertrade-procurement)
- [Analysis of the LiteLLM compromise (JFrog)](https://research.jfrog.com/post/litellm-compromised-teampcp/)
- [LiteLLM — MCP OAuth passthrough and oauth\_delegate](https://docs.litellm.ai/docs/mcp_oauth_passthrough)
