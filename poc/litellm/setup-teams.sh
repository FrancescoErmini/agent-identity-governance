#!/bin/sh
# One LiteLLM team per Keycloak client: the gateway admits a token only if its azp has a team.
# Idempotent: an existing team is left as it is.
set -eu
URL=${LITELLM_URL:-http://litellm:4000}

new_team() {   # $1 team_id = Keycloak client_id, $2 JSON with the rest
  code=$(curl -s -o /tmp/out -w '%{http_code}' "$URL/team/info?team_id=$1" -H "Authorization: Bearer $LITELLM_MASTER_KEY")
  if [ "$code" = 200 ]; then echo "team $1 exists"; return; fi
  curl -sf -X POST "$URL/team/new" -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
    -H "Content-Type: application/json" -d "{\"team_id\": \"$1\", \"team_alias\": \"$1\", $2}" >/dev/null
  echo "team $1 created"
}

# Scripted checks only (dev): a person calling the gateway directly, no agent in between.
new_team demo-cli '"models": ["claude-sonnet", "demo-mock"]'
