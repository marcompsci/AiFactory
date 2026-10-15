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

echo "==> Installing and building the web app (first run takes a few minutes)"
npm install --no-audit --no-fund --loglevel=error
(cd apps/web && npx next build >/dev/null)

set -a; [ -f .env ] && . ./.env; set +a

echo "==> Starting the API on http://localhost:8000 and the app on http://localhost:3000"
.venv/bin/python -m uvicorn services.api.main:app --host 127.0.0.1 --port 8000 &
API=$!
(cd apps/web && npx next start -p 3000) &
WEB=$!
trap 'kill $API $WEB 2>/dev/null' EXIT INT TERM
sleep 4
open http://localhost:3000 2>/dev/null || true
wait
