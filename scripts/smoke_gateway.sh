#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

pushd "$root_dir/whatsapp-gateway" >/dev/null
npm install
node_modules/.bin/puppeteer browsers install chrome >/tmp/puppeteer-install.log 2>&1 || true

export PORT="${PORT:-3999}"
export API_KEY="${API_KEY:-smoke-key}"
export BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"
export WPP_TOKEN_FOLDER="${WPP_TOKEN_FOLDER:-/tmp/wpp-smoke}"
if [ -z "${PUPPETEER_EXECUTABLE_PATH:-}" ]; then
  chrome_path=$(ls -1 node_modules/.cache/puppeteer/chrome/mac_arm-*/chrome-*/Chromium.app/Contents/MacOS/Chromium 2>/dev/null | head -n 1 || true)
  if [ -n "$chrome_path" ]; then
    export PUPPETEER_EXECUTABLE_PATH="$chrome_path"
  else
    export PUPPETEER_EXECUTABLE_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
  fi
fi

node src/index.js >/tmp/gateway-smoke.log 2>&1 &
pid=$!

for i in {1..20}; do
  if curl -s "http://127.0.0.1:${PORT}/health" >/dev/null; then
    echo "gateway up"
    kill "$pid"
    wait "$pid" || true
    popd >/dev/null
    exit 0
  fi
  sleep 1
done

echo "gateway failed to start"
tail -n 20 /tmp/gateway-smoke.log || true
kill "$pid" || true
wait "$pid" || true
popd >/dev/null
exit 1
