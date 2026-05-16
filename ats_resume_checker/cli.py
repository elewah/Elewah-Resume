"""Command-line interface for ats-resume-checker."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .checks import DEFAULT_KEYWORDS, run_checks
from .latex import BuildError, compile_latex
from .pdf_tools import PdfToolError, extract_pdf_text, read_pdf_info
from .report import has_failures, render_console, write_json, write_markdown


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ats-check",
        description="Check a LaTeX resume PDF for ATS-friendly text extraction.",
    )
    parser.add_argument("tex", type=Path, help="Path to the LaTeX source file.")
    parser.add_argument("--pdf", type=Path, help="Existing PDF to analyze.")
    parser.add_argument("--out", type=Path, help="Write a Markdown report to this path.")
    parser.add_argument("--json", type=Path, help="Write a JSON report to this path.")
    parser.add_argument("--no-compile", action="store_true", help="Do not compile LaTeX; analyze --pdf or <tex>.pdf.")
    parser.add_argument("--max-pages", type=int, default=2, help="Maximum desired page count. Default: 2.")
    parser.add_argument(
        "--keyword",
        action="append",
        dest="keywords",
        help="Target keyword to check. Can be repeated. Defaults to the built-in AI/ML list.",
    )
    parser.add_argument("--compiler", help="Force a LaTeX compiler command, such as latexmk or pdflatex.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    tex_path = args.tex.resolve()
    if not tex_path.exists():
        print(f"Error: LaTeX source not found: {tex_path}", file=sys.stderr)
        return 2

    try:
        tex_source = tex_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        print(f"Error: Could not read {tex_path} as UTF-8.", file=sys.stderr)
        return 2

    try:
        pdf_path = _resolve_pdf(args, tex_path)
        extracted_text = extract_pdf_text(pdf_path)
        pdf_info = read_pdf_info(pdf_path)
    except (BuildError, PdfToolError, FileNotFoundError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    keywords = args.keywords if args.keywords else DEFAULT_KEYWORDS
    report = run_checks(tex_source, extracted_text, pdf_info, max_pages=args.max_pages, keywords=keywords)

    print(render_console(report))
    if args.out:
        write_markdown(report, args.out)
        print(f"\nMarkdown report written to {args.out}")
    if args.json:
        write_json(report, args.json)
        print(f"JSON report written to {args.json}")

    return 1 if has_failures(report) else 0


def _resolve_pdf(args: argparse.Namespace, tex_path: Path) -> Path:
    if args.no_compile:
        pdf_path = args.pdf.resolve() if args.pdf else tex_path.with_suffix(".pdf")
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")
        return pdf_path

    if args.pdf and args.pdf.exists():
        return args.pdf.resolve()

    return compile_latex(tex_path, compiler=args.compiler)


if __name__ == "__main__":
    raise SystemExit(main())
