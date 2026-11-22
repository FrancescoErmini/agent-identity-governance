# Wave 0 demo run 20261122T090350Z

**13/13 checks passed.** Luca's sub: `830b713f-0803-4565-8fdb-971500b453b6`; agent-dq acts as `service-account-agent-dq`.

## Act 1 · Luca logs in to demo-crm through Keycloak and sees only his territory

- ✅ roles and territory in the JWT drive the app (NORTH only)
- ✅ Luca consented: may_act names agent-crm-assistant

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

## LiteLLM log for Luca's sub

Every row: the person (`user` = Luca's sub) and the agent (`team_id`). Calls refused before admission (the kill switch) leave no row here.

| time | call | team (agent) | tool or model | status |
| --- | --- | --- | --- | --- |
| 2026-11-22T09:03:50.027000Z | list_mcp_tools | agent-crm-assistant | MCP: list_tools | success |
| 2026-11-22T09:03:49.916000Z | call_mcp_tool | agent-crm-assistant | demo_crm/get_account_summary | success |
| 2026-11-22T09:03:49.658000Z | /mcp/demo_crm | agent-crm-assistant |  | failure |
| 2026-11-22T09:03:49.360000Z | call_mcp_tool | agent-crm-assistant | demo_crm/draft_visit_note | failure |
| 2026-11-22T09:03:49.118000Z | call_mcp_tool | agent-crm-assistant | demo_crm/create_reminder | failure |
| 2026-11-22T09:03:48.091000Z | list_mcp_tools | agent-crm-assistant | MCP: list_tools | success |
| 2026-11-22T09:03:47.998000Z | call_mcp_tool | agent-crm-assistant | demo_crm/get_team_report | success |
| 2026-11-22T09:03:47.715000Z | list_mcp_tools | agent-crm-assistant | MCP: list_tools | success |
| 2026-11-22T09:03:47.650000Z | call_mcp_tool | agent-crm-assistant | demo_crm/draft_visit_note | success |
| 2026-11-22T09:03:47.561000Z | list_mcp_tools | agent-crm-assistant | MCP: list_tools | success |
| 2026-11-22T09:03:47.452000Z | call_mcp_tool | agent-crm-assistant | demo_crm/get_account_summary | success |
| 2026-11-22T09:01:20.067000Z | list_mcp_tools | agent-crm-assistant | MCP: list_tools | success |
| 2026-11-22T09:01:19.976000Z | call_mcp_tool | agent-crm-assistant | demo_crm/draft_visit_note | success |
| 2026-11-22T09:01:19.857000Z | list_mcp_tools | agent-crm-assistant | MCP: list_tools | success |
| 2026-11-22T09:01:19.747000Z | call_mcp_tool | agent-crm-assistant | demo_crm/get_account_summary | success |
| 2026-11-22T09:01:19.479000Z | /mcp/demo_crm | agent-crm-assistant |  | failure |
| 2026-11-22T09:01:19.166000Z | call_mcp_tool | agent-crm-assistant | demo_crm/draft_visit_note | failure |
| 2026-11-22T09:01:18.884000Z | call_mcp_tool | agent-crm-assistant | demo_crm/create_reminder | failure |
| 2026-11-22T09:01:17.798000Z | list_mcp_tools | agent-crm-assistant | MCP: list_tools | success |
| 2026-11-22T09:01:17.707000Z | call_mcp_tool | agent-crm-assistant | demo_crm/get_team_report | success |
| 2026-11-22T09:01:17.391000Z | list_mcp_tools | agent-crm-assistant | MCP: list_tools | success |
| 2026-11-22T09:01:17.319000Z | call_mcp_tool | agent-crm-assistant | demo_crm/draft_visit_note | success |
| 2026-11-22T09:01:17.053000Z | list_mcp_tools | agent-crm-assistant | MCP: list_tools | success |
| 2026-11-22T09:01:16.633000Z | call_mcp_tool | agent-crm-assistant | demo_crm/get_account_summary | success |

Files: `acts.json`, `litellm-log-luca.json`, `demo-crm-notes-luca.json`, `demo-crm-reminders-by-agent-dq.json`.
