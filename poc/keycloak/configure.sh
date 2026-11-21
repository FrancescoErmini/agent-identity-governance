#!/bin/bash
# Settings the realm import can't hold without replacing Keycloak's built-in scopes.
# Idempotent: safe to run on every `docker compose up`.
set -euo pipefail
KCADM=/opt/keycloak/bin/kcadm.sh
REALM=ai-demo

$KCADM config credentials --server http://sso.demo.local:8080 --realm master \
  --user admin --password "$KC_ADMIN_PASSWORD" >/dev/null

id_of_client() { $KCADM get clients -r $REALM -q clientId="$1" --fields id --format csv --noquotes; }
id_of_scope()  {   # the image has no awk: plain bash
  local id name
  while IFS=, read -r id name; do [ "$name" = "$1" ] && echo "$id"; done \
    < <($KCADM get client-scopes -r $REALM --fields id,name --format csv --noquotes)
  return 0
}

# Scope crm:ai: what an agent may carry towards demo-crm. It adds the two audiences and
# admits only the rep role, so the area-manager role can never reach an agent token.
SCOPE=$(id_of_scope 'crm:ai')
if [ -z "$SCOPE" ]; then
  $KCADM create client-scopes -r $REALM -f - <<'JSON' >/dev/null
{"name": "crm:ai", "protocol": "openid-connect",
 "description": "What an AI agent may use on demo-crm: rep role only",
 "attributes": {"include.in.token.scope": "true", "display.on.consent.screen": "false"},
 "protocolMappers": [
   {"name": "aud-demo-crm", "protocol": "openid-connect", "protocolMapper": "oidc-audience-mapper",
    "config": {"included.client.audience": "demo-crm", "access.token.claim": "true", "id.token.claim": "false", "introspection.token.claim": "true"}},
   {"name": "aud-litellm-proxy", "protocol": "openid-connect", "protocolMapper": "oidc-audience-mapper",
    "config": {"included.client.audience": "litellm-proxy", "access.token.claim": "true", "id.token.claim": "false", "introspection.token.claim": "true"}}]}
JSON
  SCOPE=$(id_of_scope 'crm:ai')
  echo "created client scope crm:ai"
fi
CRM=$(id_of_client demo-crm)
REP=$($KCADM get clients/$CRM/roles/rep -r $REALM --fields id --format csv --noquotes)
$KCADM create client-scopes/$SCOPE/scope-mappings/clients/$CRM -r $REALM \
  -b "[{\"id\": \"$REP\", \"name\": \"rep\"}]" >/dev/null
echo "crm:ai -> demo-crm role rep only"
echo "keycloak configured"
