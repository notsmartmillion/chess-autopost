#!/usr/bin/env bash
# Daily chess autopost runner (Linux/macOS/docker).
# Cron example (7:00 daily):
#   0 7 * * * /path/to/chess-autopost/services/orchestrator/run_daily.sh >> /path/to/chess-autopost/outputs/logs/cron.log 2>&1
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || PY="$ROOT/.venv/Scripts/python.exe"  # Windows git-bash fallback
if [ ! -x "$PY" ]; then
  echo "venv missing — create it first:"
  echo "  python3 -m venv .venv && .venv/bin/pip install -e ./apps/analyzer[dev] pyttsx3 pydub requests python-dateutil"
  exit 1
fi

mkdir -p "$ROOT/outputs/logs"
LOG="$ROOT/outputs/logs/daily_$(date +%F_%H%M%S).log"

"$PY" "$ROOT/services/orchestrator/flow.py" 2>&1 | tee "$LOG"
