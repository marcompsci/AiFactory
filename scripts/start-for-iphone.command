#!/bin/bash
# Double-click in Finder: (re)starts AI Civilization so your iPhone can reach it over Wi-Fi.
# Stops an earlier AI Civilization API/web server on ports 8000/3000 first (only those, nothing else).
cd "$(dirname "$0")/.." || exit 1
ours=""
for port in 8000 3000; do
  for pid in $(lsof -ti "tcp:$port" -sTCP:LISTEN 2>/dev/null); do
    cmd=$(ps -o command= -p "$pid" 2>/dev/null)
    case "$cmd" in
      *uvicorn*services.api.main*|*next-server*|*"next start"*|*node*next*)
        echo "Stopping the earlier server on port $port (pid $pid)"; kill "$pid"; ours="$ours $pid" ;;
      *) echo "Port $port is used by something else ($cmd); not touching it." ;;
    esac
  done
done
# Wait for those servers to really exit: an old API that is still finishing (an open phone connection keeps it
# alive) would keep writing events while the new one starts. After 15 s, force-stop only the ones we checked above.
for pid in $ours; do
  for _ in $(seq 1 30); do kill -0 "$pid" 2>/dev/null || break; sleep 0.5; done
  if kill -0 "$pid" 2>/dev/null; then echo "The earlier server (pid $pid) didn't stop; forcing it."; kill -9 "$pid" 2>/dev/null; fi
done
sleep 1
git pull -q --ff-only 2>/dev/null && echo "Updated to the latest version."
AICIV_HOST=0.0.0.0 exec bash scripts/run-local.sh
