# ATS Resume Checker

ATS Resume Checker is a small Python CLI for checking whether a LaTeX resume produces an ATS-friendly PDF. It treats the `.tex` file as the source of truth, compiles the PDF when possible, extracts text with `pdftotext`, inspects metadata with `pdfinfo`, and reports practical issues that can hurt parsing.

The score is a heuristic, not a guarantee from any applicant tracking system.

## Features

- Compile LaTeX resumes with `latexmk` or `pdflatex`.
- Analyze an existing PDF with `--pdf` and `--no-compile`.
- Extract PDF text with Poppler `pdftotext`.
- Inspect page count, encryption, JavaScript, and metadata with `pdfinfo`.
- Detect common ATS issues:
  - missing contact fields
  - missing conventional sections
  - icon/glyph extraction problems
  - risky LaTeX layout packages
  - missing Unicode extraction hints
  - page count warnings
  - AI/ML keyword coverage
- Write console, Markdown, and JSON reports.

## Requirements

- Python 3.9+
- Poppler tools:
  - `pdftotext`
  - `pdfinfo`
- Optional LaTeX compiler:
  - `latexmk` preferred
  - `pdflatex` fallback

On macOS, Poppler can usually be installed with:

```sh
brew install poppler
```

## Install

From this repository:

```sh
python3 -m pip install -e .
```

For development:

```sh
python3 -m pip install -e ".[dev]"
```

Run the tests with the standard library:

```sh
python3 -m unittest discover -s tests
```

## Usage

Compile and analyze a LaTeX resume:

```sh
ats-check main.tex
```

Analyze an existing PDF:

```sh
ats-check main.tex --pdf main.pdf --no-compile
```

Write Markdown and JSON reports:

```sh
ats-check main.tex --out ats-report.md --json ats-report.json
```

Customize page count:

```sh
ats-check main.tex --max-pages 2
```

Customize keywords:

```sh
ats-check main.tex --keyword Python --keyword RAG --keyword "model deployment"
```

## Example Output

```text
ATS Resume Check: 85/100

Checks:
- [PASS] Email extraction: Email address is extractable.
- [PASS] PDF text extraction: Extracted 7312 characters.
- [WARN] Layout package: paracol: Multi-column layouts can reorder text in some parsers.

Top fixes:
- Verify pdftotext reading order and replace visual-only elements with plain text where possible.
```

## Exit Codes

- `0`: report completed with no critical failures
- `1`: report completed and found critical ATS failures
- `2`: setup/build/extraction error, such as missing files or missing external tools

## Limitations

This tool does not emulate a specific ATS vendor. It checks the same practical signals recruiters and ATS parsers often depend on: selectable text, readable contact fields, conventional sections, sane metadata, and keyword extraction.

For best results, always inspect the extracted text preview in the report.
