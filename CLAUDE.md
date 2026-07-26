# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

Two things live here together:

1. **`main.tex`** — the LaTeX source for Abdelrahman Elewah's personal resume. CI compiles it with `latexmk` and commits the resulting `elewah_resume.pdf` automatically. `main.tex` itself is a thin entry point (`\input{preamble}` + one `\input{sections/...}` per resume section, see "Resume source layout" below) — it's split into multiple files so an AI agent editing resume content only ever needs to load the one small file relevant to the edit, not the whole document.
2. **`ats_resume_checker/`** — a Python package (CLI + Streamlit UI) that checks whether a LaTeX resume produces an ATS-friendly PDF.

## Resume source layout

`main.tex` is deliberately kept as just an `\input` shell so CI/tooling that hardcodes the filename (`latex.yml`, `README.md`, `scripts/install.sh`) doesn't need to change. The actual content lives in:

```
preamble.tex          # document class, packages, colors, custom environments/macros — styling only, no resume content
sections/
  header.tex          # name + contact line + links
  summary.tex          # Summary section
  skills.tex           # Technical Skills section
  experience.tex        # Professional Experience section (all job entries)
  education.tex         # Education section
  projects.tex           # Projects section
```

When editing resume **content**, open only the matching `sections/*.tex` file — it's small (a few dozen lines) and has no macro definitions to accidentally disturb. Only touch `preamble.tex` for styling/layout/macro changes. This mapping is also documented in `.claude/skills/ats-tex-editor/SKILL.md` for the AI editing workflow.

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
./scripts/stop-ui.sh       # stops whatever's listening on $PORT (default 8501)
```

The UI does not compile LaTeX; it expects a `.pdf` and, for source-based checks, `.tex` file(s) to
be uploaded. If the resume is split (`main.tex` + `preamble.tex` + `sections/*.tex`), select all of
them together in the file picker — `ui.map_uploaded_tex_files` places each upload back under
`sections/` by basename convention before `latex.resolve_includes` assembles the full text, so
source-based checks and the "Run AI Agent" editor both see (and can edit) the complete resume, not
just `main.tex`'s `\input` lines. A single self-contained `.tex` file still works as before.

## Architecture

```
ats_resume_checker/
  latex.py       # LaTeX → plain text: strip_comments, extract_sections, normalize_latex_text, resolve_includes, compile_latex
  pdf_tools.py   # Poppler wrappers: extract_pdf_text (pdftotext), read_pdf_info (pdfinfo)
  checks.py      # All ATS heuristics: run_checks → AtsReport; scoring (warn −5, fail −15)
  report.py      # Render console/Markdown/JSON from AtsReport
  cli.py         # argparse entry point (ats-check); exit codes 0/1/2
  ui.py          # Streamlit helper used by app.py
app.py           # Streamlit app (upload-only, calls ui.py)
```

Data flows: `cli.py` → `latex.resolve_includes` (source-based checks) + `latex.compile_latex` → `pdf_tools` → `checks.run_checks` → `report`.

`checks.run_checks` takes three inputs: the raw `.tex` source, extracted PDF text, and `pdfinfo` dict. It is the central function; everything else is either feeding it or rendering its output.

`resolve_includes` exists because `main.tex` is split across multiple files (see "Resume source layout" above): it recursively inlines `\input{}`/`\include{}` targets that resolve to a real project file, so source-based checks (`parse.unicode_mapping`, `layout.package.*`, section/keyword diagnostics) see the fully assembled resume text, not just `main.tex`'s six `\input` lines. Both `cli.py` and the Streamlit path (`ui.analyze_uploaded_resume`) use it, as does the "Run AI Agent" workspace (`agent.py`) — the agent's sandbox is materialized with the full uploaded file set (preserving the `sections/` layout), and its system prompt is generated per-run (`agent._build_system_prompt`) with a file map so it edits the one relevant file instead of rewriting `main.tex`.

## CI

`.github/workflows/latex.yml` runs on push/PR to `main`. It installs `texlive-full`, compiles `main.tex`, renames the output to `elewah_resume.pdf`, and commits it back with `[skip ci]`. The `main.pdf` artifact in the repo is the local working copy; `elewah_resume.pdf` is the CI-published artifact.

## External dependencies

- **Poppler** (`pdftotext`, `pdfinfo`) — required at runtime for all PDF analysis. Install with `brew install poppler` on macOS.
- **latexmk** or **pdflatex** — optional; only needed when compiling `.tex` locally.
