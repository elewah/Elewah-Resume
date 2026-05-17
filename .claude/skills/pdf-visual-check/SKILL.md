---
name: pdf-visual-check
description: >
  Use this skill when the user wants to visually inspect a compiled resume PDF, check for text
  overlap or layout problems, convert PDF pages to PNG images, verify the resume still looks
  human-readable after ATS edits, or whenever the conversation involves "check PDF visually",
  "convert PDF to PNG", "verify resume layout", "check for text overlap", "does my resume look correct",
  or "pdf visual verification". Also invoke when the AI agent's pdf_to_png tool output needs
  interpretation — i.e., what visual defects to look for in the rendered pages.
---

# PDF Visual Check

ATS text-extraction checks verify that a resume is machine-parseable. Visual checks verify it
is still human-readable. Run both after every round of ATS-driven edits.

## Converting PDF to PNG

```python
from pathlib import Path
from ats_resume_checker.pdf_to_png import pdf_pages_to_png
from ats_resume_checker.pdf_tools import PdfToolError

try:
    pages = pdf_pages_to_png(Path("main.pdf"), dpi=150)
    # pages[0] is bytes of page 1 PNG, pages[1] is page 2, etc.
    print(f"{len(pages)} page(s), first page: {len(pages[0])} bytes")
except PdfToolError as exc:
    print(f"Error: {exc}")
```

Resolution guide:
- `dpi=150` — default, good for quick inspection
- `dpi=200` — higher fidelity, useful for spotting small text issues
- `dpi=300` — print-quality, needed for fine detail

Requires `pdftoppm` from Poppler (`brew install poppler` on macOS).

## Displaying pages in Streamlit

```python
import streamlit as st
for i, png_bytes in enumerate(pages):
    st.image(png_bytes, caption=f"Page {i + 1}", use_container_width=True)
```

## Saving pages to disk (for manual inspection)

```python
for i, png_bytes in enumerate(pages, start=1):
    Path(f"resume_page_{i}.png").write_bytes(png_bytes)
```

## Visual inspection checklist

### Text overlap and clipping
- Lines of text bleeding into each other vertically (line-height too tight after removing multi-column layout)
- Text cut off at the page margin (left, right, or bottom edge)
- Header/footer overlapping the body content

### Section heading clarity
- Each section heading should visually stand out (bold, larger font, or a horizontal rule)
- Consistent spacing above each new section
- No heading that runs directly into the previous section's last bullet

### Contact block (top of page)
- Name prominent at the top
- Email, phone, and links visible and not truncated
- No icon-shaped empty boxes or question marks (indicates a missing glyph — the `parse.unicode_mapping` fix may also help here)

### Column layout artifacts
Two-column resumes may look fine visually but still have ATS reading-order problems. Check:
- Enough whitespace between columns so they do not appear to merge
- No text from a right-column section visually overlapping a left-column entry

### Bullet alignment
- Bullets flush with consistent indentation throughout
- Hanging indent uniform across all `\item` entries
- No bullets that appear to float at a different x-position than their siblings

### Font rendering
- Text crisp and anti-aliased at 150 DPI
- Consistent font weight within `\textbf{...}` spans — no partial-bold lines
- No "staircase" artifact on diagonal lines (indicates a font substitution or rasterization issue)

### Page utilization
- No excessive white space at the bottom of the last page (suggests content was removed without rebalancing)
- Margins consistent on all four sides
- No content extending past the nominal page boundary

## Integration with the AI agent

In the agentic loop (`ats_resume_checker/agent.py`), the `pdf_to_png` tool is called after
`compile_and_check` to give the model visual confirmation that layout edits did not break
readability. The tool returns PNG bytes stored in `AgentResult.png_pages`, which the Streamlit
UI renders in the "Visual PDF Preview" section of the agent results panel.

If the agent's PNG preview shows a visual defect that the ATS checks did not catch, report it
as a new check or fix it manually in the `.tex` source and recompile.
