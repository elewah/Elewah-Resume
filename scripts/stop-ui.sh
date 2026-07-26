#!/usr/bin/env sh
set -eu

PORT="${PORT:-8501}"

PIDS=""
if command -v lsof >/dev/null 2>&1; then
  PIDS="$(lsof -ti "tcp:$PORT" 2>/dev/null || true)"
fi

if [ -z "$PIDS" ] && command -v pgrep >/dev/null 2>&1; then
  PIDS="$(pgrep -f 'streamlit run app\.py' 2>/dev/null || true)"
fi

if [ -z "$PIDS" ]; then
  printf 'No running ATS Resume Checker UI found on port %s.\n' "$PORT"
  exit 0
fi

printf 'Stopping ATS Resume Checker UI (pid: %s)\n' "$(echo "$PIDS" | tr '\n' ' ' | sed 's/[[:space:]]*$//')"
# shellcheck disable=SC2086
kill $PIDS
