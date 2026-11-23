# Wave 0 demo run 20261123T073515Z

**15/15 checks passed.** Luca's sub: `314148f1-78d0-44da-a551-b70f74573585`; agent-dq acts as `service-account-agent-dq`.

## Act 1 · Luca logs in to demo-crm through Keycloak and sees only his territory

- ✅ roles and territory in the JWT drive the app (NORTH only)
- ✅ Luca consented: may_act names agent-crm-assistant

## AS-IS · Luca writes a visit note by hand; the audit names Luca, no agent

- ✅ the note is final at once, created_by luca, no agent
- ✅ audit: luca by hand, from the demo-crm UI; JWT verified, azp demo-crm, no act

## Act 2 · The assistant drafts a visit note for Luca; it waits for his confirmation

- ✅ note stored as draft, created_by luca, via_agent agent-crm-assistant
- ✅ Luca confirms it himself: the note becomes final

## Act 3 · Luca, also area manager, asks for the team report; the app refuses the assistant

- ✅ demo-crm refuses: the delegated token carries only rep

## Act 4 · The scheduler starts agent-dq; reminders appear tagged as autonomous

- ✅ reminders created by agent-dq with its own identity

## Act 5 · The assistant tries a tool outside its list, then a final note; LiteLLM refuses both

- ✅ create_reminder refused by the gateway (not on the assistant's list)
- ✅ draft_visit_note with status final refused by the gateway guardrail

## Act 6 · The same final note sent straight to the API, bypassing the gateway

- ✅ demo-crm stores it only as a draft: two independent layers

## Act 7 · The assistant is blocked in LiteLLM; its next call fails. The log shows sub and agent

- ✅ kill switch: team agent-crm-assistant blocked
- ✅ the assistant's next call is refused at the gateway
- ✅ after unblocking, it works again
- ✅ every tool call in the LiteLLM log carries luca's sub and the agent's team

## Audit trail in demo-crm (changes and refusals)

One row per call, with the JWT that reached the API. Full rows, with every claim, in `audit-demo-crm.json`; the JWTs LiteLLM checked are in `audit-gateway-jwts.json`.

| time | who | action | record | outcome | from | JWT sub · azp · act |
| --- | --- | --- | --- | --- | --- | --- |
| 07:35:11 | luca (by hand) | POST /notes | note:1 (final) | allowed | demo-crm UI | luca · demo-crm · - |
| 07:35:13 | luca through agent-crm-assistant | POST /notes | note:2 (draft) | allowed | MCP server, via LiteLLM | luca · agent-crm-assistant · agent-crm-assistant |
| 07:35:13 | luca (by hand) | POST /notes/2/confirm | note:2 | allowed | test script | luca · demo-crm · - |
| 07:35:13 | luca through agent-crm-assistant | GET /reports/team |  | refused | MCP server, via LiteLLM | luca · agent-crm-assistant · agent-crm-assistant |
| 07:35:13 | agent-dq (autonomous) | POST /reminders | reminder:1 for giulia | allowed | MCP server, via LiteLLM | service-account-agent-dq · agent-dq · - |
| 07:35:14 | agent-dq (autonomous) | POST /reminders | reminder:2 for giulia | allowed | MCP server, via LiteLLM | service-account-agent-dq · agent-dq · - |
| 07:35:14 | luca through agent-crm-assistant | POST /notes | note:3 (draft) | allowed | crm-assistant, direct | luca · agent-crm-assistant · agent-crm-assistant |
| 07:35:15 | luca through agent-crm-assistant | POST /notes | note:4 (draft) | allowed | MCP server, via LiteLLM | luca · agent-crm-assistant · agent-crm-assistant |

## LiteLLM log for Luca's sub

Every row: the person (`user` = Luca's sub) and the agent (`team_id`). Calls refused before admission (the kill switch) leave no row here.

| time | call | team (agent) | tool or model | status |
| --- | --- | --- | --- | --- |
| 2026-11-23T07:35:14.426000Z | call_mcp_tool | agent-crm-assistant | demo_crm/create_reminder | failure |
| 2026-11-23T07:35:13.487000Z | list_mcp_tools | agent-crm-assistant | MCP: list_tools | success |
| 2026-11-23T07:35:13.352000Z | call_mcp_tool | agent-crm-assistant | demo_crm/get_team_report | success |
| 2026-11-23T07:35:13.063000Z | list_mcp_tools | agent-crm-assistant | MCP: list_tools | success |
| 2026-11-23T07:35:12.998000Z | call_mcp_tool | agent-crm-assistant | demo_crm/draft_visit_note | success |
| 2026-11-23T07:35:12.803000Z | list_mcp_tools | agent-crm-assistant | MCP: list_tools | success |
| 2026-11-23T07:35:12.539000Z | call_mcp_tool | agent-crm-assistant | demo_crm/get_account_summary | success |

Files: `acts.json`, `litellm-log-luca.json`, `demo-crm-notes-luca.json`, `audit-demo-crm.json`, `audit-gateway-jwts.json`, `demo-crm-reminders-by-agent-dq.json`.
