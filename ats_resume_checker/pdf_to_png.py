"""Convert PDF pages to PNG images using Poppler's pdftoppm."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from .pdf_tools import PdfToolError


def pdf_pages_to_png(pdf_path: Path, dpi: int = 150) -> list[bytes]:
    """Convert each page of pdf_path to a PNG and return the bytes.

    Returns a list of PNG bytes, one entry per page, in page order.
    Raises PdfToolError if pdftoppm is missing or fails.
    """
    tool = shutil.which("pdftoppm")
    if tool is None:
        raise PdfToolError(
            "pdftoppm not found. Install Poppler to convert PDF pages to images."
        )

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        prefix = tmp_path / "page"
        result = subprocess.run(
            [tool, "-png", "-r", str(dpi), str(pdf_path), str(prefix)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if result.returncode != 0:
            raise PdfToolError(
                result.stderr.decode(errors="replace").strip() or "pdftoppm failed."
            )

        # Sort by integer page number so zero-padded names (page-01, page-10) order correctly.
        png_files = sorted(
            tmp_path.glob("page-*.png"),
            key=lambda p: int(p.stem.split("-")[-1]),
        )
        return [f.read_bytes() for f in png_files]
