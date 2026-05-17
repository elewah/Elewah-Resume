#!/usr/bin/env sh
set -eu

PROJECT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
VENV_DIR="${VENV_DIR:-$PROJECT_DIR/.venv}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

printf 'ATS Resume Checker installer\n'
printf 'Project: %s\n' "$PROJECT_DIR"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  printf 'Error: %s was not found. Install Python 3.10+ and rerun this script.\n' "$PYTHON_BIN" >&2
  exit 1
fi

# claude-agent-sdk requires Python 3.10+. Check the chosen interpreter first.
PYTHON_VERSION=$("$PYTHON_BIN" -c 'import sys; print("%d.%d" % sys.version_info[:2])')
PYTHON_MAJOR=$("$PYTHON_BIN" -c 'import sys; print(sys.version_info[0])')
PYTHON_MINOR=$("$PYTHON_BIN" -c 'import sys; print(sys.version_info[1])')
if [ "$PYTHON_MAJOR" -lt 3 ] || { [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 10 ]; }; then
  printf 'Error: Python 3.10+ is required (claude-agent-sdk), but %s is Python %s.\n' \
    "$PYTHON_BIN" "$PYTHON_VERSION" >&2
  printf 'Set a newer interpreter and rerun: PYTHON_BIN=python3.11 ./scripts/install.sh\n' >&2
  exit 1
fi
printf 'Python %s OK\n' "$PYTHON_VERSION"

# If an existing venv was built with Python < 3.10, remove it and recreate.
if [ -d "$VENV_DIR" ]; then
  VENV_VERSION=$("$VENV_DIR/bin/python" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo "0.0")
  VENV_MINOR=$("$VENV_DIR/bin/python" -c 'import sys; print(sys.version_info[1])' 2>/dev/null || echo "0")
  if [ "$VENV_MINOR" -lt 10 ]; then
    printf 'Existing venv uses Python %s (< 3.10). Removing and recreating with %s...\n' \
      "$VENV_VERSION" "$PYTHON_BIN"
    rm -rf "$VENV_DIR"
  fi
fi

if [ ! -d "$VENV_DIR" ]; then
  printf 'Creating virtual environment: %s\n' "$VENV_DIR"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1091
. "$VENV_DIR/bin/activate"

printf 'Upgrading pip and installing package with UI and AI agent dependencies...\n'
python -m pip install --upgrade pip
python -m pip install -e "$PROJECT_DIR[ui,agent]"

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

if command -v pdftoppm >/dev/null 2>&1; then
  printf 'OK: pdftoppm found at %s\n' "$(command -v pdftoppm)"
else
  printf 'Warning: pdftoppm was not found. Install Poppler for PDF visual previews in the AI agent.\n' >&2
fi

printf '\nInstall complete.\n'
printf 'Start the UI with:\n'
printf '  ./scripts/start-ui.sh\n'
printf '\nRun the CLI with:\n'
printf '  . .venv/bin/activate && ats-check main.tex --pdf elewah_resume.pdf --no-compile\n'
printf '\nTo use the AI Resume Improvement agent, set your Anthropic API key:\n'
printf '  export ANTHROPIC_API_KEY=sk-ant-...\n'
