---
name: ats-tex-editor
description: >
  Use this skill when the user wants to fix ATS check failures or warnings by editing LaTeX source,
  improve their resume's ATS score, understand what LaTeX changes will fix a specific check ID,
  or when the conversation involves "fix ATS issues in the tex", "edit the LaTeX to improve ATS",
  "how do I fix parse.unicode_mapping", "remove risky packages", "fix section headings for ATS",
  or any request to improve a resume's text extractability or ATS compliance through source edits.
  Also invoke for the AI agent workflow when iterating on the .tex file.
---

# ATS LaTeX Editor

## File map

`main.tex` is a thin shell (`\input{preamble}` + one `\input{sections/...}` per
section) — the actual content lives elsewhere. Open only the file that matches
the edit; don't load the whole document for a content change.

| Editing...                          | Open this file            |
|--------------------------------------|----------------------------|
| Name, contact line, links            | `sections/header.tex`      |
| Summary paragraph                    | `sections/summary.tex`     |
| Technical skills list                | `sections/skills.tex`      |
| Job bullets, employer/title/dates    | `sections/experience.tex`  |
| Degrees, schools, transcripts        | `sections/education.tex`   |
| Project entries                      | `sections/projects.tex`    |
| Packages, colors, macros, spacing    | `preamble.tex`             |

This mapping is also documented in the repo's `CLAUDE.md`.

## General rules

- Never change factual content: employer names, job titles, dates, degrees, or skill descriptions.
- Make surgical, targeted edits scoped to the one file above that matches the change — prefer preamble.tex additions over restructuring section files, and never touch preamble.tex for a content-only edit.
- Always verify the edit compiles (`compile_latex()`) and re-run `run_checks()` to confirm improvement.
- Fix `fail` checks first (−15 pts each), then `warn` checks (−5 pts each).

## Fix patterns by check ID

### `parse.unicode_mapping` — WARN

Add these two lines to `preamble.tex` (a `\usepackage`/macro file, not resume content), immediately before `\begin{document}`:

```latex
\input{glyphtounicode}
\pdfgentounicode=1
```

This tells pdflatex to embed Unicode mappings so ATS parsers can extract text correctly.

---

### `contact.email` — FAIL

The email must appear as selectable text in the extracted output, not just as an href anchor with no visible content.

```latex
% BAD: email hidden inside href anchor-only
\href{mailto:user@example.com}{}

% GOOD: href with readable text
\href{mailto:user@example.com}{user@example.com}

% ALSO GOOD: plain text
user@example.com
```

---

### `contact.links` — WARN/FAIL

LinkedIn, GitHub, or a URL must appear in plain extracted text:

```latex
% Ensure the URL is the visible text, not hidden inside a macro
\href{https://linkedin.com/in/yourname}{linkedin.com/in/yourname}
\href{https://github.com/yourname}{github.com/yourname}
```

---

### `layout.package.fontawesome` / `layout.package.fontawesome5` — WARN

Icon-only elements using FontAwesome are not extracted as text. Replace with plain text labels:

```latex
% BAD: icon with no extractable text equivalent
\faLinkedin\ \href{https://linkedin.com/in/name}{}

% GOOD: plain text label
LinkedIn: \href{https://linkedin.com/in/name}{linkedin.com/in/name}
```

If the package is used only for decorative icons alongside readable text links, removing the
`\usepackage{fontawesome}` line from `preamble.tex` and replacing `\faIcon{...}` calls (wherever
they're used, e.g. `sections/header.tex`) with text labels eliminates the warning without
losing information.

---

### `layout.package.paracol` / `layout.package.multicol` — WARN

Two-column layouts scramble the ATS reading order. Convert to single-column:

1. Remove `\usepackage{paracol}` (or `multicol`) from `preamble.tex`.
2. Move sidebar content (skills, contact info) into the main column using `\section` + `\begin{itemize}` blocks, in the matching `sections/*.tex` file (see File map above).
3. Place all sections sequentially: Summary → Skills → Experience → Education → Projects (i.e. the `\input` order already set in `main.tex`).

---

### `layout.package.tabularx` / `layout.package.tabular` — WARN

Table cells are often not extracted in reading order. Replace skill grids with lists:

```latex
% BAD: skill grid in a tabular
\begin{tabular}{ll}
Python & Docker \\
SQL    & Kubernetes \\
\end{tabular}

% GOOD: comma-separated or bulleted list
\begin{itemize}
  \item Python, SQL, Docker, Kubernetes
\end{itemize}
```

---

### `section.*` — WARN (heading in source but missing from PDF extraction)

This usually means the section heading is rendered but not extractable. Common causes:
- Using `\section*{...}` — the star variant may be excluded from some extractors; try `\section{...}`.
- The heading text is set using a font/color command that breaks glyph mapping.
- Ensure the heading name matches one of the expected variants (case-insensitive):
  - Summary / Professional Summary / Profile
  - Skills / Technical Skills / Technologies
  - Experience / Professional Experience / Work Experience / Employment
  - Education
  - Projects / Selected Projects

---

### `keywords.coverage` — WARN/FAIL

Keywords that appear in `source_only` are in the `.tex` source but not in the extracted PDF text.
They are being swallowed by a macro. Move them into plain text:

```latex
% BAD: keyword inside href anchor-only text (not extracted)
\href{https://pytorch.org}{}

% GOOD: keyword in visible bullet text
\item Built models with \href{https://pytorch.org}{PyTorch} and TensorFlow
```

Also ensure skills listed in the source appear as plain `\item` text in a skills section,
not only inside `\textbf{...}` nested inside complex column macros.

---

## Compilation

```python
from pathlib import Path
from ats_resume_checker.latex import compile_latex, BuildError

try:
    pdf_path = compile_latex(Path("main.tex"))   # auto-detects latexmk or pdflatex
except BuildError as exc:
    print(exc)   # contains LaTeX log on failure
```

Then re-run the ATS check. Use `resolve_includes` (not `Path.read_text()`) to build `tex_source` —
`main.tex` is just `\input` lines, so reading it directly would make source-based checks
(`parse.unicode_mapping`, `layout.package.*`, section/keyword diagnostics) see almost nothing:

```python
from ats_resume_checker.latex import resolve_includes
from ats_resume_checker.checks import run_checks
from ats_resume_checker.pdf_tools import extract_pdf_text, read_pdf_info

tex_source = resolve_includes(Path("main.tex"))
extracted = extract_pdf_text(pdf_path)
pdf_info = read_pdf_info(pdf_path)
report = run_checks(tex_source, extracted, pdf_info)
print(report.score)
```

The `ats-check` CLI already does this internally, so `ats-check main.tex` works correctly
without any extra steps — the above is only needed when calling `run_checks` directly.

## AI agent workflow

The AI agent in `ats_resume_checker/agent.py` automates this loop:

```
read_tex → compile_and_check → write_tex (with fix) → compile_and_check → repeat
```

Trigger it from the Streamlit UI ("Run AI Agent" button) or call `run_improvement_agent()` directly.
The agent respects the same rules as manual editing and uses the fix patterns above.

`run_improvement_agent()` takes `tex_files: dict[str, bytes]` (relative path → content, e.g.
`{"main.tex": ..., "preamble.tex": ..., "sections/experience.tex": ...}` — build it from a
Streamlit multi-upload via `ui.map_uploaded_tex_files`), not a single blob: the full set is
written into the agent's sandbox preserving that layout, and its system prompt is generated
per-run (`agent._build_system_prompt`) with the same file map shown above, so it edits the one
relevant file instead of rewriting `main.tex`. `AgentResult.final_tex_files` returns the actual
per-file result alongside `improved_tex` (a flattened, single-file convenience copy).
