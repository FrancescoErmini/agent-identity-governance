#!/bin/sh
# Kill switch (act 7): block or unblock an agent at the gateway.
#   ./scripts/kill-switch.sh block   [agent-crm-assistant]
#   ./scripts/kill-switch.sh unblock [agent-crm-assistant]
# Blocking the agent's LiteLLM team stops its next model or tool call, whoever it acts for.
# Keycloak is untouched: the agent can still get tokens, but nothing it does passes the gateway.
set -eu
cd "$(dirname "$0")/.."
ACTION=${1:?usage: kill-switch.sh block|unblock [agent]}
AGENT=${2:-agent-crm-assistant}
KEY=$(grep '^LITELLM_MASTER_KEY=' .env | cut -d= -f2-)
case "$ACTION" in block|unblock) ;; *) echo "usage: kill-switch.sh block|unblock [agent]" >&2; exit 2 ;; esac
curl -sf -X POST "http://localhost:4000/team/$ACTION" -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" -d "{\"team_id\": \"$AGENT\"}" >/dev/null
echo "$AGENT: ${ACTION}ed at the gateway"
