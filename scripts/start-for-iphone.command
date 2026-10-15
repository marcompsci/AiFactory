#!/bin/bash
# Double-click in Finder: (re)starts AI Civilization so your iPhone can reach it over Wi-Fi.
# Stops an earlier AI Civilization API/web server on ports 8000/3000 first (only those, nothing else).
cd "$(dirname "$0")/.." || exit 1
for port in 8000 3000; do
  for pid in $(lsof -ti "tcp:$port" -sTCP:LISTEN 2>/dev/null); do
    cmd=$(ps -o command= -p "$pid" 2>/dev/null)
    case "$cmd" in
      *uvicorn*services.api.main*|*next-server*|*"next start"*|*node*next*) echo "Stopping the earlier server on port $port (pid $pid)"; kill "$pid" ;;
      *) echo "Port $port is used by something else ($cmd); not touching it." ;;
    esac
  done
done
sleep 2
git pull -q --ff-only 2>/dev/null && echo "Updated to the latest version."
AICIV_HOST=0.0.0.0 exec bash scripts/run-local.sh
