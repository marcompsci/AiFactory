#!/usr/bin/env bash
# Runs pytest and turns failures into GitHub annotations (GitHub shows at most 10 per step, so they are batched).
set -uo pipefail
python -m pytest -o addopts="" -q -rfE -p no:cacheprovider "$@" 2>&1 | tee pytest.log
status=${PIPESTATUS[0]}
if [ "$status" -ne 0 ]; then
  failed=$(grep -E "^(FAILED|ERROR) " pytest.log | head -40 | sed 's/%/%25/g' | awk '{printf "%s%%0A", $0}')
  errors=$(grep -E "^E +" pytest.log | head -40 | sed 's/%/%25/g' | awk '{printf "%s%%0A", $0}')
  echo "::error title=pytest failures::${failed}"
  [ -n "$errors" ] && echo "::error title=pytest error lines::${errors}"
fi
exit $status
