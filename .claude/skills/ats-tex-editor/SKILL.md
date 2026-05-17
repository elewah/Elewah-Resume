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

## General rules

- Never change factual content: employer names, job titles, dates, degrees, or skill descriptions.
- Make surgical, targeted edits — prefer preamble additions over document restructuring.
- Always verify the edit compiles (`compile_latex()`) and re-run `run_checks()` to confirm improvement.
- Fix `fail` checks first (−15 pts each), then `warn` checks (−5 pts each).

## Fix patterns by check ID

### `parse.unicode_mapping` — WARN

Add these two lines to the preamble, immediately before `\begin{document}`:

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
`\usepackage{fontawesome}` line and replacing `\faIcon{...}` calls with text labels eliminates
the warning without losing information.

---

### `layout.package.paracol` / `layout.package.multicol` — WARN

Two-column layouts scramble the ATS reading order. Convert to single-column:

1. Remove `\usepackage{paracol}` (or `multicol`) from the preamble.
2. Move sidebar content (skills, contact info) into the main column using `\section` + `\begin{itemize}` blocks.
3. Place all sections sequentially: Summary → Skills → Experience → Education → Projects.

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

Then re-run the ATS check:

```python
from ats_resume_checker.checks import run_checks
from ats_resume_checker.pdf_tools import extract_pdf_text, read_pdf_info

extracted = extract_pdf_text(pdf_path)
pdf_info = read_pdf_info(pdf_path)
report = run_checks(tex_source, extracted, pdf_info)
print(report.score)
```

## AI agent workflow

The AI agent in `ats_resume_checker/agent.py` automates this loop:

```
read_tex → compile_and_check → write_tex (with fix) → compile_and_check → repeat
```

Trigger it from the Streamlit UI ("Run AI Agent" button) or call `run_improvement_agent()` directly.
The agent respects the same rules as manual editing and uses the fix patterns above.
