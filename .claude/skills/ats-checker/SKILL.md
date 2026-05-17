---
name: ats-checker
description: >
  Use this skill when the user asks to run, interpret, troubleshoot, or act on results from
  the ATS resume checker. Invoke it whenever the conversation involves "ats-check", "ATS score",
  "check my resume for ATS compliance", "interpret ats-check output", "what does this check mean",
  or any question about how the checker works, what checks exist, or how scoring is calculated.
  Also use it when the user wants to understand why a check passed, warned, or failed.
---

# ATS Checker

## Running the checker

```sh
ats-check main.tex                                        # compile + analyze
ats-check main.tex --pdf main.pdf --no-compile            # skip compilation, use existing PDF
ats-check main.tex --out report.md --json report.json     # write reports to files
ats-check main.tex --max-pages 1 --keyword python --keyword kubernetes
```

The CLI compiles the `.tex` file (unless `--no-compile`), extracts text from the PDF using
Poppler's `pdftotext`, reads metadata via `pdfinfo`, then runs all checks.

**Exit codes:** 0 = all pass/warn, 1 = has failures, 2 = error (missing file, build failure, missing tools)

## Scoring model

- Base score: **100**
- Each `warn`: **−5 points**
- Each `fail`: **−15 points**
- Minimum: **0**

## All check IDs

### Contact checks
| ID | What is checked |
|----|----------------|
| `contact.name` | First non-empty extracted line looks like a name (2–5 capitalized words) |
| `contact.email` | Email regex match in extracted PDF text |
| `contact.phone` | Phone pattern (10+ digits, optional separators) in extracted text |
| `contact.links` | LinkedIn / GitHub / URL keyword in extracted text |

### Section checks (one per group)
| ID | Expected headings |
|----|------------------|
| `section.summary` | "summary", "professional summary", "profile" |
| `section.skills` | "skills", "technical skills", "technologies" |
| `section.experience` | "experience", "professional experience", "work experience", "employment" |
| `section.education` | "education" |
| `section.projects` | "projects", "selected projects" |

**PASS**: heading appears in extracted PDF text.
**WARN**: heading is in `.tex` source but missing from extracted text — indicates a PDF layout or encoding problem.

### Parseability checks
| ID | Threshold | Status |
|----|-----------|--------|
| `parse.text_volume` | Extracted text ≥ 500 chars | FAIL if under |
| `parse.glyphs` | Suspicious character ratio < 1% | WARN if over |
| `parse.unicode_mapping` | `glyphtounicode` + `pdfgentounicode` in `.tex` | WARN if missing |
| `parse.encrypted` | PDF is not encrypted | FAIL if encrypted |
| `parse.javascript` | No JavaScript embedded | WARN if present |
| `parse.page_count` | Pages ≤ `max_pages` (default 2) | WARN if over |

### Layout checks
| ID | Trigger |
|----|--------|
| `layout.package.fontawesome` | `fontawesome` package loaded |
| `layout.package.fontawesome5` | `fontawesome5` package loaded |
| `layout.package.paracol` | `paracol` package loaded |
| `layout.package.multicol` | `multicol` package loaded |
| `layout.package.tabularx` | `tabularx` package loaded |
| `layout.package.tikz` | `tikz` package loaded |
| `layout.heading_split` | Adjacent single-word lines suggesting a split heading |

All layout checks produce **WARN** (−5 pts each).

### Keyword check
| ID | Condition | Status |
|----|-----------|--------|
| `keywords.coverage` | ≥ 10 target keywords in extracted text | PASS |
| `keywords.coverage` | 6–9 keywords found | WARN |
| `keywords.coverage` | < 6 keywords found | FAIL |

Default keywords: python, javascript, typescript, react, node, sql, docker, kubernetes,
ci/cd, aws, gcp, azure, machine learning, deep learning, tensorflow, pytorch, data,
api, rest, graphql, git, agile, scrum, leadership, communication.

## AtsReport structure (JSON)

```json
{
  "score": 85,
  "checks": [
    {"id": "parse.unicode_mapping", "title": "Unicode mapping", "status": "warn",
     "message": "glyphtounicode not found", "fix": "Add \\input{glyphtounicode}"}
  ],
  "source_sections": ["Experience", "Education"],
  "extracted_sections": ["Experience", "Education"],
  "keywords": {
    "found": ["python", "docker"],
    "missing": ["kubernetes"],
    "source_only": []
  },
  "pdf_info": {"pages": 1, "encrypted": "no"},
  "extracted_text": "..."
}
```

## Data flow

```
cli.py / ui.py → compile_latex() → extract_pdf_text() + read_pdf_info()
               → run_checks(tex_source, extracted_text, pdf_info)
               → AtsReport → render_console() / render_markdown() / write_json()
```

Central function: `run_checks()` in `ats_resume_checker/checks.py`.
