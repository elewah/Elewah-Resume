"""Wrappers around Poppler PDF tools used for ATS extraction checks."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any


class PdfToolError(RuntimeError):
    """Raised when pdftotext/pdfinfo is missing or fails."""


def extract_pdf_text(pdf_path: Path) -> str:
    tool = shutil.which("pdftotext")
    if tool is None:
        raise PdfToolError("pdftotext not found. Install Poppler to analyze PDF extraction.")
    result = subprocess.run(
        [tool, str(pdf_path), "-"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise PdfToolError(result.stderr.strip() or "pdftotext failed.")
    return result.stdout


def read_pdf_info(pdf_path: Path) -> dict[str, Any]:
    tool = shutil.which("pdfinfo")
    if tool is None:
        raise PdfToolError("pdfinfo not found. Install Poppler to inspect PDF metadata.")
    result = subprocess.run(
        [tool, str(pdf_path)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise PdfToolError(result.stderr.strip() or "pdfinfo failed.")
    return parse_pdfinfo(result.stdout)


def parse_pdfinfo(output: str) -> dict[str, Any]:
    info: dict[str, Any] = {}
    for line in output.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        normalized_key = key.strip().lower().replace(" ", "_")
        cleaned_value = value.strip()
        if normalized_key == "pages":
            try:
                info[normalized_key] = int(cleaned_value)
            except ValueError:
                info[normalized_key] = cleaned_value
        else:
            info[normalized_key] = cleaned_value
    return info
