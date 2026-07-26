---
name: resume-writer
description: >
  Use this skill when the user wants to create a brand-new resume in this repo's ATS-friendly
  LaTeX structure (main.tex + preamble.tex + sections/*.tex) and doesn't already have a .tex
  file to start from. Triggers on "I don't have a LaTeX resume, can you make one", "write my
  resume in LaTeX", "convert my Word/PDF resume to LaTeX", "start a new resume from scratch",
  "scaffold my resume files", or when the ATS checker/Streamlit AI agent has no .tex file to
  work with and one needs to be generated first. Also use when the user pastes resume text,
  describes their work history in chat, or uploads an existing .docx/.pdf resume to convert.
  Never invents content — only uses what the user actually provides, asking for anything
  missing rather than fabricating it.
---

# Resume Writer

Scaffolds a brand-new resume in this repo's multi-file LaTeX structure — `main.tex` (a thin
`\input` shell) + `preamble.tex` (styling/macros) + `sections/*.tex` (content) — for a user who
doesn't have a `.tex` file yet. See `CLAUDE.md`'s "Resume source layout" for why this repo is
split this way: it keeps an editing agent from ever needing to touch the dense LaTeX macros
just to change a bullet point. This skill extends that same protection to the *generation*
step — you never write the preamble from memory, you copy a proven template.

## Step 1: Gather the candidate's real content

Figure out what the user has and get it into plain text:

- **Pasted or typed text, or described in chat** — use directly.
- **An uploaded `.docx`** — use the `docx` skill's documented extraction method:
  `pandoc --track-changes=all document.docx -o output.md`, then read the Markdown.
- **An uploaded `.pdf`** — extract text with `pdftotext` (already a project dependency,
  wrapped by `ats_resume_checker.pdf_tools.extract_pdf_text`).

Then sort what you have into: contact info (name + whichever of location/email/phone/
portfolio/LinkedIn/GitHub/other links they have), a summary (optional), skills, experience (per
job: employer, title, location, dates, a few bullet achievements), education (per degree:
institution, degree, field, dates, optional GPA/honors), and projects (optional).

**Never invent an employer, title, date, degree, or achievement the user didn't give you.**
This is the same rule already stated in `ats-tex-editor`'s general rules and in the Streamlit
AI agent's system prompt (`ats_resume_checker/agent.py`) — a resume's factual claims are the
one thing that must always trace back to something the candidate actually said. If a detail is
missing or a date is vague, ask; don't guess and don't leave a placeholder in the final output.
It's fine — expected, even — for a first pass to have gaps you need to check with the user
before generating the files.

## Step 2: Generate the files

Work out the target directory first (default: the current directory). If a `main.tex` already
exists there, confirm with the user before overwriting it.

**`preamble.tex` — copy, don't retype.** This file is dense (`titlesec` config, custom
`onecolentry`/`twocolentry`/`threecolentry`/`highlights`/`header` environments, the
`glyphtounicode`/`pdfgentounicode` Unicode-mapping hack) and getting any of it wrong either
breaks the build or silently reintroduces an ATS problem. Copy the bundled template directly —
e.g. `cp <this-skill-dir>/assets/preamble.tex <target>/preamble.tex` — then replace the single
`<<FULL_NAME>>` token (it appears twice, in `pdftitle`/`pdfauthor`) with the candidate's real
name. Do not otherwise edit this file, and never write it from memory.

**`sections/*.tex` — follow the pattern, write the real content.** `assets/sections/` has one
example per section (`header.example.tex`, `summary.example.tex`, `skills.example.tex`,
`experience.example.tex`, `education.example.tex`, `projects.example.tex`), each showing the
correct environment usage with obviously-fake placeholder content. Read the example for the
section you're writing, then produce the real file with the same structure and the candidate's
actual content. Only create files for sections that have real content — skip
`sections/summary.tex` or `sections/projects.tex` entirely if the user has nothing for them.

A few structural notes the examples encode:
- `header.example.tex`'s contact line is `\mbox{...}` segments joined by
  `\kern 0.25 cm%\n|%\n\kern 0.25 cm%` separators. If the candidate doesn't have one of those
  items (say, no portfolio site), drop both its `\mbox{...}` line *and* the separator pair next
  to it — leaving an separator with nothing on one side produces a stray "`|`" in the header.
- `education.example.tex` shows a `highlights` block for GPA/honors, but that's optional — the
  repo's own `sections/education.tex` has entries with just the `twocolentry` line and no
  `highlights` block at all when there's nothing else to add.
- `experience.example.tex` and `projects.example.tex` show one entry each; repeat the
  `twocolentry`/`onecolentry` block per job or project, most recent first.

**`main.tex` — thin shell, only the sections that exist.** Write:

```latex
\input{preamble}

\begin{document}
\input{sections/header}
\input{sections/summary}
\input{sections/skills}
\input{sections/experience}
\input{sections/education}
\input{sections/projects}
\end{document}
```

but only include the `\input{sections/...}` lines for files you actually created, in this
order (header → summary → skills → experience → education → projects) — `header`, `skills`,
and `experience`/`education` are effectively always present; `summary` and `projects` are the
two that are commonly skipped.

## Step 3: Verify

Compile and check exactly as you would for an existing resume — don't duplicate those
instructions here, follow the `ats-checker` skill (`ats-check <target>/main.tex`) and the
`pdf-visual-check` skill (render to PNG, look for overlap/truncation). If anything is flagged,
fix it the way `ats-tex-editor` describes — but only formatting, never content. A freshly
generated resume from this template should score well immediately, since the bundled preamble
is already the ATS-safe version; a low score here usually means a section file deviated from
the environment patterns above, not that the template itself needs fixing.

## Step 4: Hand off

Tell the user the resume is ready, where the files are, and what to do next: `ats-checker` to
interpret the score, `ats-tex-editor` for further ATS fixes, and — now that a `.tex` file
exists — the Streamlit "Run AI Agent" button for automated iteration.
