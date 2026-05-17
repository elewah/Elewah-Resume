"""Shared helpers for the Streamlit UI."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .checks import DEFAULT_KEYWORDS, AtsReport, run_checks
from .pdf_tools import extract_pdf_text, read_pdf_info


@dataclass
class UploadedAnalysis:
    report: AtsReport
    extracted_text: str
    pdf_info: dict


def analyze_uploaded_resume(
    tex_bytes: bytes,
    pdf_bytes: bytes,
    max_pages: int = 2,
    keywords: Iterable[str] | None = None,
) -> UploadedAnalysis:
    """Analyze uploaded LaTeX/PDF bytes using temporary files for PDF tools."""
    tex_source = tex_bytes.decode("utf-8")
    selected_keywords = list(keywords) if keywords is not None else DEFAULT_KEYWORDS

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        pdf_path = tmp_path / "resume.pdf"
        pdf_path.write_bytes(pdf_bytes)

        extracted_text = extract_pdf_text(pdf_path)
        pdf_info = read_pdf_info(pdf_path)
        report = run_checks(tex_source, extracted_text, pdf_info, max_pages=max_pages, keywords=selected_keywords)

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
