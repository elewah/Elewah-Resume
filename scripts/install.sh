#!/usr/bin/env sh
set -eu

PROJECT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
VENV_DIR="${VENV_DIR:-$PROJECT_DIR/.venv}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

printf 'ATS Resume Checker installer\n'
printf 'Project: %s\n' "$PROJECT_DIR"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  printf 'Error: %s was not found. Install Python 3.9+ and rerun this script.\n' "$PYTHON_BIN" >&2
  exit 1
fi

if [ ! -d "$VENV_DIR" ]; then
  printf 'Creating virtual environment: %s\n' "$VENV_DIR"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1091
. "$VENV_DIR/bin/activate"

printf 'Upgrading pip and installing package with UI dependencies...\n'
python -m pip install --upgrade pip
python -m pip install -e "$PROJECT_DIR[ui]"

printf '\nChecking external PDF tools...\n'
if command -v pdftotext >/dev/null 2>&1; then
  printf 'OK: pdftotext found at %s\n' "$(command -v pdftotext)"
else
  printf 'Warning: pdftotext was not found. Install Poppler before analyzing PDFs.\n' >&2
fi

if command -v pdfinfo >/dev/null 2>&1; then
  printf 'OK: pdfinfo found at %s\n' "$(command -v pdfinfo)"
else
  printf 'Warning: pdfinfo was not found. Install Poppler before analyzing PDFs.\n' >&2
fi

printf '\nInstall complete.\n'
printf 'Start the UI with:\n'
printf '  ./scripts/start-ui.sh\n'
printf '\nRun the CLI with:\n'
printf '  . .venv/bin/activate && ats-check main.tex --pdf elewah_resume.pdf --no-compile\n'
