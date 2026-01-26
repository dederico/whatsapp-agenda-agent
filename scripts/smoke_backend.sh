#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

pushd "$root_dir/backend" >/dev/null
python -m pip install -r requirements.txt

export PORT="${PORT:-8001}"
export ENV=dev
export API_KEY_INTERNAL=smoke
export DATABASE_URL="${DATABASE_URL:-sqlite:///./smoke.db}"
export WHATSAPP_GATEWAY_URL="${WHATSAPP_GATEWAY_URL:-http://localhost:3001}"
export WHATSAPP_GATEWAY_API_KEY="${WHATSAPP_GATEWAY_API_KEY:-smoke}"
export OWNER_WHATSAPP_NUMBER="${OWNER_WHATSAPP_NUMBER:-0000000000}"

uvicorn app.main:app --host 127.0.0.1 --port "$PORT" >/tmp/uvicorn-smoke.log 2>&1 &
pid=$!

for i in {1..20}; do
  if curl -s "http://127.0.0.1:${PORT}/health" >/dev/null; then
    echo "backend up"
    kill "$pid"
    wait "$pid" || true
    popd >/dev/null
    exit 0
  fi
  sleep 1
done

echo "backend failed to start"
kill "$pid" || true
wait "$pid" || true
popd >/dev/null
exit 1
