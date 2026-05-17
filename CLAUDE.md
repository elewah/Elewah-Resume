# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

Two things live here together:

1. **`main.tex`** — the LaTeX source for Abdelrahman Elewah's personal resume. CI compiles it with `latexmk` and commits the resulting `elewah_resume.pdf` automatically.
2. **`ats_resume_checker/`** — a Python package (CLI + Streamlit UI) that checks whether a LaTeX resume produces an ATS-friendly PDF.

## Commands

### Resume PDF

Compile locally (requires `latexmk` or `pdflatex`):
```sh
latexmk -pdf -interaction=nonstopmode main.tex
```

### ATS checker — install

```sh
./scripts/install.sh          # installs the package into .venv
python3 -m pip install -e ".[dev]"   # include test deps
python3 -m pip install -e ".[ui]"    # include Streamlit
```

### ATS checker — run

```sh
ats-check main.tex                          # compile + check
ats-check main.tex --pdf main.pdf --no-compile   # skip compile
ats-check main.tex --out report.md --json report.json
```

### Tests

```sh
python3 -m unittest discover -s tests       # run all tests
python3 -m unittest tests.test_checks       # run a single module
```

### Streamlit UI

```sh
./scripts/start-ui.sh      # or: streamlit run app.py
```

The UI does not compile LaTeX; it expects both a `.tex` and a `.pdf` to be uploaded.

## Architecture

```
ats_resume_checker/
  latex.py       # LaTeX → plain text: strip_comments, extract_sections, normalize_latex_text, compile_latex
  pdf_tools.py   # Poppler wrappers: extract_pdf_text (pdftotext), read_pdf_info (pdfinfo)
  checks.py      # All ATS heuristics: run_checks → AtsReport; scoring (warn −5, fail −15)
  report.py      # Render console/Markdown/JSON from AtsReport
  cli.py         # argparse entry point (ats-check); exit codes 0/1/2
  ui.py          # Streamlit helper used by app.py
app.py           # Streamlit app (upload-only, calls ui.py)
```

Data flows: `cli.py` → `latex.compile_latex` → `pdf_tools` → `checks.run_checks` → `report`.

`checks.run_checks` takes three inputs: the raw `.tex` source, extracted PDF text, and `pdfinfo` dict. It is the central function; everything else is either feeding it or rendering its output.

## CI

`.github/workflows/latex.yml` runs on push/PR to `main`. It installs `texlive-full`, compiles `main.tex`, renames the output to `elewah_resume.pdf`, and commits it back with `[skip ci]`. The `main.pdf` artifact in the repo is the local working copy; `elewah_resume.pdf` is the CI-published artifact.

## External dependencies

- **Poppler** (`pdftotext`, `pdfinfo`) — required at runtime for all PDF analysis. Install with `brew install poppler` on macOS.
- **latexmk** or **pdflatex** — optional; only needed when compiling `.tex` locally.
