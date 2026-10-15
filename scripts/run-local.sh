#!/usr/bin/env bash
# Run AI Civilization on this computer: API on :8000, web app on :3000.
#   bash scripts/run-local.sh
# Reads .env (API) and apps/web/.env.local (web). Ctrl-C stops both.
set -euo pipefail
cd "$(dirname "$0")/.."

PY=""
for c in python3.13 python3.12 /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.12 "$HOME/.homebrew/bin/python3.13" "$HOME/.homebrew/bin/python3.12" python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo "Python 3.12 or newer is needed. Install it with:  brew install python@3.12   then run this again." >&2
  exit 1
fi
command -v npm >/dev/null || { echo "Node.js is needed. Install it with:  brew install node   then run this again." >&2; exit 1; }

echo "==> Python: $($PY --version)  Node: $(node --version)"
[ -d .venv ] || "$PY" -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

mkdir -p .data
echo "==> Installing and building the web app (first run takes a few minutes)"
npm install --no-audit --no-fund --loglevel=error
(cd apps/web && npx next build > ../../.data/web-build.log 2>&1) || { echo "Web build failed:" >&2; tail -30 .data/web-build.log >&2; exit 1; }

set -a; [ -f .env ] && . ./.env; set +a

LAN_IP=""
if [ "${AICIV_HOST:-127.0.0.1}" = "0.0.0.0" ]; then
  # the interface that carries the default route (Wi-Fi or Ethernet), then the usual suspects
  IFACE=$(route -n get default 2>/dev/null | awk '/interface:/{print $2}' || true)
  for i in $IFACE en0 en1 en2 en3 en4 en5; do
    LAN_IP=$(ipconfig getifaddr "$i" 2>/dev/null || true)
    [ -n "$LAN_IP" ] && break
  done
  [ -z "$LAN_IP" ] && LAN_IP=$( (hostname -I 2>/dev/null || true) | awk '{print $1}')
  [ -z "$LAN_IP" ] && echo "!! Couldn't find this Mac's network address. Is Wi-Fi on? The phone needs it." >&2
  if [ -n "$LAN_IP" ]; then
    # the city opened on your phone (http://<this Mac>:3000) calls the API from that origin
    export AICIV_ALLOWED_ORIGINS="${AICIV_ALLOWED_ORIGINS:-http://localhost:3000},http://$LAN_IP:3000"
  fi
fi

echo "==> Starting the API on http://localhost:8000 and the app on http://localhost:3000"
# AICIV_HOST=0.0.0.0 lets the iPhone app reach this Mac on your Wi-Fi (sign-in must be configured; plain HTTP on a
# trusted network only — use Tailscale or a tunnel with HTTPS anywhere else).
.venv/bin/python -m uvicorn services.api.main:app --host "${AICIV_HOST:-127.0.0.1}" --port 8000 --proxy-headers &
API=$!
(cd apps/web && npx next start -H "${AICIV_HOST:-127.0.0.1}" -p 3000) &
WEB=$!
trap 'kill $API $WEB 2>/dev/null' EXIT INT TERM
sleep 4
open http://localhost:3000 2>/dev/null || true
if [ -n "$LAN_IP" ]; then
  echo
  echo "==> iPhone app: More > Settings > API address:  http://$LAN_IP:8000   (or just $LAN_IP)"
  echo "    City address fills in as http://$LAN_IP:3000. Phone and Mac must be on the same Wi-Fi."
fi
wait
