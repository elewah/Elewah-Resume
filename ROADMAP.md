# ATS Resume Checker — Roadmap

This document tracks the four high-impact improvements planned for the ATS Resume Checker,
expanding it from a LaTeX-only personal tool into a general-purpose ATS checker any job seeker can use.

---

## Improvement 1 — PDF-Only Mode

**Status:** In progress  
**Impact:** Opens the tool to every job seeker, not just LaTeX users.

### Problem

The current `ats-check` CLI and Streamlit UI require both a `.tex` source file and a compiled `.pdf`.
The majority of job seekers write resumes in Word, Canva, Google Docs, or Notion and export to PDF.
They have no LaTeX source to upload.

### Solution

Add a PDF-only analysis path throughout the stack:

- **CLI:** `ats-check --pdf-only resume.pdf` — the `.tex` argument becomes optional.
- **Streamlit UI:** when only a PDF is uploaded (no `.tex`), automatically run in PDF-only mode.
- **`run_checks`:** accept `tex_source=""` and skip checks that require LaTeX source:
  - `parse.unicode_mapping` — requires preamble inspection; skipped.
  - `layout.package.*` — requires `\usepackage` scanning; skipped.
  - Section source-vs-PDF comparison note — suppressed (no source to compare against).
  - All contact, parseability, keyword, and section-detection checks still run normally.

### What is skipped vs. still checked

| Check group | PDF-only behavior |
|---|---|
| `contact.*` | Fully checked |
| `section.*` | Detected from PDF text (source comparison note suppressed) |
| `parse.text_volume`, `parse.glyphs`, `parse.encrypted`, `parse.javascript`, `parse.page_count` | Fully checked |
| `parse.unicode_mapping` | Skipped (requires `.tex`) |
| `layout.package.*` | Skipped (requires `.tex`) |
| `keywords.coverage` | Fully checked |

### Files changed

- `ats_resume_checker/checks.py` — `run_checks(tex_source="")` detection, conditional checks.
- `ats_resume_checker/cli.py` — `tex` positional made optional, `--pdf-only` flag added.
- `ats_resume_checker/ui.py` — `tex_bytes: bytes | None` in `analyze_uploaded_resume`.
- `app.py` — `.tex` upload made optional; PDF-only banner shown when running without source.
- `tests/test_checks.py`, `tests/test_cli.py` — PDF-only coverage.

---

## Improvement 2 — Job Description Matching

**Status:** Planned  
**Impact:** Transforms the tool from a format checker into a real job-targeting assistant.

### Problem

The current keyword list is hardcoded to a fixed AI/ML stack. Real users need to paste a job
description and find out how well their resume matches *that specific role*, not a generic list.

### Solution

Add a JD matching layer on top of the existing keyword check:

- **CLI:** `--jd path/to/jd.txt` or `--jd-url https://jobs.example.com/...` to supply the job description.
- **Streamlit UI:** a "Job Description" text area (paste the JD text) and optional URL field.
- **`jd_tools.py` (new):** extract candidate keywords/phrases from JD text using frequency + noun-phrase heuristics. No LLM required for the basic version; an LLM-powered extraction mode can be added later.
- **`checks.py`:** new `keywords.jd_match` check that scores overlap between resume extracted text and JD keywords, plus a gap list (in-JD, not-in-resume).
- **Report:** add a "JD Match" section showing matched terms, missing terms, and a match percentage.

### Key design decisions

- JD keywords *supplement* the default keyword list rather than replace it, so users get both a
  general ATS score and a role-specific match score.
- The JD parser strips HTML if a URL is supplied, then applies stopword filtering and extracts
  technical noun phrases (multi-word terms like "CI/CD pipeline" or "cross-functional teams").

### Files to add/change

- `ats_resume_checker/jd_tools.py` (new) — JD text cleaning, keyword extraction.
- `ats_resume_checker/checks.py` — new `keywords.jd_match` check.
- `ats_resume_checker/cli.py` — `--jd` and `--jd-url` flags.
- `app.py` — JD text area + optional URL input in sidebar.
- `tests/test_jd_tools.py` (new).

---

## Improvement 3 — Word (.docx) Input

**Status:** Planned  
**Impact:** Adds support for the most common resume format worldwide.

### Problem

Word documents are the dominant resume format. Currently there is no way to check a `.docx`
resume without first converting it to PDF manually outside the tool.

### Solution

Accept `.docx` uploads directly:

1. **Text extraction:** use `python-docx` to extract paragraph text and table cell text from the `.docx`.
2. **PDF conversion:** convert `.docx → .pdf` via LibreOffice headless (`soffice --headless --convert-to pdf`).
   This is the same conversion the `docx` skill uses.
3. **ATS checks:** run the full check suite on the converted PDF — identical to the PDF-only path.
4. **Source-level checks for .docx:** a new `docx_tools.py` module will inspect the document structure
   (heading styles, table usage, text boxes) and produce docx-specific layout warnings analogous to
   the LaTeX `layout.package.*` checks.

### docx-specific checks to add

| Check ID | What it detects |
|---|---|
| `layout.docx.text_box` | Text boxes are often skipped by ATS parsers |
| `layout.docx.header_footer_content` | Contact info in Word headers/footers is usually not extracted |
| `layout.docx.table_layout` | Tables used for two-column layouts scramble reading order |
| `layout.docx.inline_shape` | Inline images/shapes may hide keywords |

### Files to add/change

- `ats_resume_checker/docx_tools.py` (new) — extract text, detect risky structures, convert to PDF.
- `ats_resume_checker/checks.py` — `run_checks_docx()` wrapper calling `docx_tools` + existing checks.
- `ats_resume_checker/cli.py` — accept `.docx` as first argument, auto-detect format.
- `app.py` — add `.docx` to accepted upload types.
- `tests/test_docx_tools.py` (new).

---

## Improvement 4 — Docx Agent Iteration Loop

**Status:** Planned (depends on Improvement 3)  
**Impact:** Extends the AI improvement agent to Word users — the same automated fix-and-rescore loop
LaTeX users already have, but for `.docx` files.

### The current LaTeX agent loop

```
read resume.tex
  → run ats-check (score, failing checks)
    → edit resume.tex (targeted LaTeX fix)
      → latexmk → new resume.pdf
        → re-check → new score
          → repeat until score is maximised
```

The `.tex` file is the editable source. `latexmk` is the "compiler". Everything downstream
(`pdftotext`, `run_checks`) is format-agnostic.

### The docx agent loop (same structure, different source format)

```
read resume.docx
  → convert to PDF (LibreOffice) → run ats-check (score, failing checks)
    → edit resume.docx (python-docx fix via docx skill)
      → re-convert to PDF (LibreOffice)
        → re-check → new score
          → repeat until score is maximised
```

The `.docx` file is the editable source. LibreOffice replaces `latexmk`. Everything downstream
is unchanged.

### What the agent edits in a .docx

Using the `docx` skill (unpack XML → edit → repack), the agent makes the same classes of fixes
as it does for LaTeX, translated to Word document concepts:

| LaTeX fix | .docx equivalent |
|---|---|
| Rename `\section{...}` to conventional name | Change paragraph style to `Heading 1` with conventional text |
| Remove `\usepackage{fontawesome}` icon-only elements | Delete icon-only text runs, keep plain text labels |
| Convert `tabularx` skill grid to `itemize` | Replace skill grid `<w:tbl>` with `<w:p>` bullet paragraphs |
| Add `\href{...}{email@example.com}` visible text | Ensure email appears as a plain `<w:t>` run, not hidden in a hyperlink with empty display text |
| Add `glyphtounicode` (LaTeX-only, no .docx equivalent) | — skipped — |

### Agent system prompt changes

The `agent.py` system prompt will gain a docx-specific section (activated when `format="docx"`):

- Replace "run latexmk" with "run `soffice --headless --convert-to pdf`".
- Replace LaTeX fix patterns with `docx` skill XML patterns.
- Same scoring rules, same iteration budget, same "never change factual content" constraint.

### Implementation approach

`agent.py` will gain a `format: Literal["latex", "docx"] = "latex"` parameter. The async core
`_run_agent_async` branches on `format` to choose the correct system prompt section and compile step.
All ATS checking code is shared — format selection only affects the edit→compile half of the loop.

### Files to add/change

- `ats_resume_checker/agent.py` — `format` param, docx system prompt, docx compile step.
- `ats_resume_checker/docx_tools.py` — `convert_docx_to_pdf()` function (LibreOffice wrapper).
- `app.py` — "Run AI Agent" available for `.docx` uploads once Improvement 3 is in place.
- `.claude/skills/ats-tex-editor/SKILL.md` — renamed or supplemented with docx fix patterns.
