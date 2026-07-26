"""Shared helpers for the Streamlit UI."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .checks import DEFAULT_KEYWORDS, AtsReport, run_checks
from .latex import resolve_includes
from .pdf_tools import extract_pdf_text, read_pdf_info

# Basenames that this repo's resume convention places under sections/ (see
# CLAUDE.md's "Resume source layout" and .claude/skills/ats-tex-editor's file
# map). A browser's multi-file picker only reports each file's basename, not
# its folder — so a plain "experience.tex" upload needs to be placed back at
# "sections/experience.tex" for \input{sections/experience} in main.tex to
# resolve against the reconstructed temp directory.
SECTION_FILENAMES = frozenset(
    {"header.tex", "summary.tex", "skills.tex", "experience.tex", "education.tex", "projects.tex"}
)


def map_uploaded_tex_files(files: Iterable[tuple[str, bytes]]) -> dict[str, bytes]:
    """Map a flat list of (basename, content) uploads to their relative repo paths.

    Basenames matching :data:`SECTION_FILENAMES` are placed under ``sections/``;
    everything else (``main.tex``, ``preamble.tex``, or a legacy single-file
    upload under any other name) stays at the root. Takes plain
    ``(name, bytes)`` tuples rather than Streamlit's ``UploadedFile`` objects
    so it's usable without a Streamlit runtime, e.g. from tests.
    """
    mapped: dict[str, bytes] = {}
    for name, content in files:
        basename = Path(name).name
        rel_path = f"sections/{basename}" if basename in SECTION_FILENAMES else basename
        mapped[rel_path] = content
    return mapped


@dataclass
class UploadedAnalysis:
    report: AtsReport
    extracted_text: str
    pdf_info: dict


def analyze_uploaded_resume(
    tex_files: dict[str, bytes] | None,
    pdf_bytes: bytes,
    max_pages: int = 2,
    keywords: Iterable[str] | None = None,
    jd_keywords: list[str] | None = None,
) -> UploadedAnalysis:
    """Analyze an uploaded resume using temporary files for PDF tools.

    Pass ``tex_files=None`` (or ``{}``) to run in **PDF-only mode**: LaTeX
    source checks (``parse.unicode_mapping``, ``layout.package.*``) are
    skipped automatically.

    ``tex_files`` maps relative path -> file content, e.g.
    ``{"main.tex": b"...", "preamble.tex": b"...", "sections/experience.tex": b"..."}``
    — build it from a flat upload list with :func:`map_uploaded_tex_files`.
    All files are written into a temp directory preserving that relative
    layout, then ``\\input{}``/``\\include{}`` references are resolved from
    whichever file is named ``main.tex`` (or, for a single-file upload, that
    one file) via ``latex.resolve_includes`` — the same resolution the CLI
    uses — so source-based checks see the fully assembled resume text rather
    than just the entry file's ``\\input`` lines.

    Pass ``jd_keywords`` (from ``jd_tools.extract_keywords``) to add a
    ``keywords.jd_match`` check against the specific job description.
    """
    selected_keywords = list(keywords) if keywords is not None else DEFAULT_KEYWORDS

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        pdf_path = tmp_path / "resume.pdf"
        pdf_path.write_bytes(pdf_bytes)

        if tex_files:
            tex_root = tmp_path / "tex_src"
            tex_root.mkdir()
            for rel_path, content in tex_files.items():
                target = tex_root / rel_path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
            entry_name = "main.tex" if "main.tex" in tex_files else next(iter(tex_files))
            tex_source = resolve_includes(tex_root / entry_name)
        else:
            tex_source = ""

        extracted_text = extract_pdf_text(pdf_path)
        pdf_info = read_pdf_info(pdf_path)
        report = run_checks(
            tex_source,
            extracted_text,
            pdf_info,
            max_pages=max_pages,
            keywords=selected_keywords,
            jd_keywords=jd_keywords or [],
        )

    return UploadedAnalysis(report=report, extracted_text=extracted_text, pdf_info=pdf_info)


def parse_keywords(raw_keywords: str) -> list[str]:
    """Parse one-keyword-per-line UI input."""
    keywords = []
    for line in raw_keywords.splitlines():
        cleaned = line.strip()
        if cleaned and cleaned not in keywords:
            keywords.append(cleaned)
    return keywords or list(DEFAULT_KEYWORDS)


def summarize_status_counts(report: AtsReport) -> dict[str, int]:
    counts = {"pass": 0, "warn": 0, "fail": 0}
    for check in report.checks:
        if check.status in counts:
            counts[check.status] += 1
    return counts


def top_fixes(report: AtsReport, limit: int = 5) -> list[str]:
    fixes = []
    seen = set()
    for check in report.checks:
        if check.status not in {"fail", "warn"} or not check.fix or check.fix in seen:
            continue
        seen.add(check.fix)
        fixes.append(check.fix)
        if len(fixes) == limit:
            break
    return fixes
