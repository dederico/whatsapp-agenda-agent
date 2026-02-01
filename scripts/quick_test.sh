#!/usr/bin/env bash
set -euo pipefail

API_BASE="${API_BASE:-https://agente-agenda-calendario-api.onrender.com}"
GATEWAY_BASE="${GATEWAY_BASE:-https://agente-agenda-calendario.onrender.com}"
OWNER_NUMBER="${OWNER_NUMBER:-}"
API_KEY="${API_KEY:-}"

echo "API_BASE=$API_BASE"
echo "GATEWAY_BASE=$GATEWAY_BASE"
echo "OWNER_NUMBER=${OWNER_NUMBER:-<unset>}"
echo "API_KEY=${API_KEY:-<unset>}"
echo

echo "== OAuth status =="
curl -sS "$API_BASE/oauth/status" || true
echo

echo "== Backend status (latest events) =="
curl -sS "$API_BASE/status" || true
echo

echo "== Force Gmail poll (POST) =="
curl -sS -X POST "$API_BASE/gmail/poll" || true
echo

if [[ -n "$API_KEY" && -n "$OWNER_NUMBER" ]]; then
  echo "== Direct gateway send test =="
  curl -sS -X POST "$GATEWAY_BASE/send" \
    -H "x-api-key: $API_KEY" \
    -H "content-type: application/json" \
    -d "{\"to_number\":\"$OWNER_NUMBER\",\"text\":\"test directo $(date +%H:%M:%S)\"}" || true
  echo
else
  echo "== Direct gateway send test skipped (set API_KEY and OWNER_NUMBER) =="
fi
