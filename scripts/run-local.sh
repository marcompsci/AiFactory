#!/usr/bin/env bash
# Run AI Civilization on this computer: API on :8000, web app on :3000.
#   bash scripts/run-local.sh
# Reads .env (API) and apps/web/.env.local (web). Ctrl-C stops both.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p .data
# everything shown here is also kept in .data/server.log (the last run), for troubleshooting
exec > >(tee .data/server.log) 2>&1

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
export AICIV_LOCAL_MODE=1   # running on your own computer: a stale browser tab here never triggers the sign-in lockout

LAN_IP=""
LAN_NAME=""
BIND="${AICIV_HOST:-127.0.0.1}"
if [ "${AICIV_HOST:-127.0.0.1}" = "0.0.0.0" ]; then
  BIND="::"   # IPv6 and IPv4: an iPhone Personal Hotspot is often IPv6-only
  export AICIV_ALLOW_LAN_ORIGINS=1   # the city page opened from your phone (http://<this Mac>:3000) may call the API
  # the Mac's Bonjour name works on any network, IPv4 or IPv6 (the phone finds it by itself)
  LAN_NAME=$(scutil --get LocalHostName 2>/dev/null || true)
  [ -n "$LAN_NAME" ] && LAN_NAME="$LAN_NAME.local"
  IFACE=$(route -n get default 2>/dev/null | awk '/interface:/{print $2}' || true)
  for i in $IFACE en0 en1 en2 en3 en4 en5; do
    LAN_IP=$(ipconfig getifaddr "$i" 2>/dev/null || true)
    [ -n "$LAN_IP" ] && break
  done
  [ -z "$LAN_IP" ] && LAN_IP=$( (ifconfig 2>/dev/null || true) | awk '/inet / && $2 != "127.0.0.1" {print $2; exit}')
  case "$LAN_IP" in 192.0.0.*) LAN_IP="" ;; esac   # 192.0.0.x is an IPv6 hotspot's translation address: unreachable from the phone
  [ -z "$LAN_IP$LAN_NAME" ] && echo "!! Couldn't find this Mac's network address. Is Wi-Fi on? The phone needs it." >&2
  for h in $LAN_IP $LAN_NAME; do
    LOWER=$(printf '%s' "$h" | tr 'A-Z' 'a-z')
    export AICIV_ALLOWED_ORIGINS="${AICIV_ALLOWED_ORIGINS:-http://localhost:3000},http://$LOWER:3000"
  done
fi

echo "==> Starting the API on http://localhost:8000 and the app on http://localhost:3000"
# AICIV_HOST=0.0.0.0 lets the iPhone app reach this Mac on your Wi-Fi (sign-in must be configured; plain HTTP on a
# trusted network only — use Tailscale or a tunnel with HTTPS anywhere else).
.venv/bin/python -m uvicorn services.api.main:app --host "$BIND" --port 8000 --proxy-headers &
API=$!
(cd apps/web && npx next start -H "$BIND" -p 3000) &
WEB=$!
ANNOUNCE=""
if [ -n "$LAN_NAME" ] && command -v dns-sd >/dev/null 2>&1; then
  # let the iPhone app find this Mac by itself (Bonjour); it reads the name and ports from the announcement
  dns-sd -R "AI Civilization (${LAN_NAME%.local})" _aiciv._tcp local 8000 host="$LAN_NAME" api=8000 web=3000 >/dev/null 2>&1 &
  ANNOUNCE=$!
fi
trap 'kill $API $WEB $ANNOUNCE 2>/dev/null' EXIT INT TERM
sleep 4
open http://localhost:3000 2>/dev/null || true
if [ -n "$LAN_NAME$LAN_IP" ]; then
  echo
  echo "==> iPhone app: open it; it finds this Mac by itself. (Or type ${LAN_NAME:-$LAN_IP} in More > Settings.)"
  [ -n "$LAN_NAME" ] && [ -n "$LAN_IP" ] && echo "    (or $LAN_IP on this Wi-Fi)"
  echo "    The city address fills in by itself. Phone and Mac must share the network (Wi-Fi or the phone's hotspot)."
fi
wait
