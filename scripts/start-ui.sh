#!/usr/bin/env sh
set -eu

PROJECT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
VENV_DIR="${VENV_DIR:-$PROJECT_DIR/.venv}"
PORT="${PORT:-8501}"
ADDRESS="${ADDRESS:-localhost}"

if [ -d "$VENV_DIR" ]; then
  # shellcheck disable=SC1091
  . "$VENV_DIR/bin/activate"
fi

if ! python -c "import streamlit" >/dev/null 2>&1; then
  printf 'Error: Streamlit is not installed.\n' >&2
  printf 'Run ./scripts/install.sh first, or install with: python3 -m pip install -e ".[ui]"\n' >&2
  exit 1
fi

cd "$PROJECT_DIR"

printf 'Starting ATS Resume Checker UI at http://%s:%s\n' "$ADDRESS" "$PORT"
python -m streamlit run app.py \
  --server.address "$ADDRESS" \
  --server.port "$PORT"
