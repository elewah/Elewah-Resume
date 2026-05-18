import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ats_resume_checker import cli


_GOOD_EXTRACTED = (
    """
    Ada Lovelace
    ada@example.com | +1 555-555-5555 | linkedin.com/in/ada | github.com/ada
    Summary
    Technical Skills
    Professional Experience
    Education
    Projects
    Python LLMs RAG LangChain LangGraph FastAPI PostgreSQL Docker AWS MLOps
    computer vision document intelligence semantic search model deployment
    """
    * 5
)

_GOOD_PDF_INFO = {"pages": 1, "encrypted": "no", "javascript": "no"}


class CliTests(unittest.TestCase):
    def test_cli_no_compile_uses_existing_pdf_and_writes_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            tex_path = tmp_path / "resume.tex"
            pdf_path = tmp_path / "resume.pdf"
            md_path = tmp_path / "report.md"
            json_path = tmp_path / "report.json"
            tex_path.write_text(
                r"""
                \input{glyphtounicode}
                \pdfgentounicode=1
                \section{Summary}
                \section{Technical Skills}
                \section{Professional Experience}
                \section{Education}
                \section{Projects}
                Python LLMs RAG LangChain LangGraph FastAPI PostgreSQL Docker AWS MLOps computer vision document intelligence semantic search model deployment
                """,
                encoding="utf-8",
            )
            pdf_path.write_bytes(b"%PDF-1.7")

            with mock.patch.object(cli, "extract_pdf_text", return_value=_GOOD_EXTRACTED), mock.patch.object(
                cli, "read_pdf_info", return_value={"pages": 2, "encrypted": "no", "javascript": "no"}
            ), contextlib.redirect_stdout(io.StringIO()):
                exit_code = cli.main(
                    [
                        str(tex_path),
                        "--pdf",
                        str(pdf_path),
                        "--no-compile",
                        "--out",
                        str(md_path),
                        "--json",
                        str(json_path),
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertTrue(md_path.exists())
            self.assertTrue(json_path.exists())

    # ------------------------------------------------------------------
    # PDF-only mode
    # ------------------------------------------------------------------

    def test_pdf_only_mode_runs_without_tex_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "resume.pdf"
            pdf_path.write_bytes(b"%PDF-1.7")

            with mock.patch.object(cli, "extract_pdf_text", return_value=_GOOD_EXTRACTED), \
                 mock.patch.object(cli, "read_pdf_info", return_value=_GOOD_PDF_INFO), \
                 contextlib.redirect_stdout(io.StringIO()):
                exit_code = cli.main(["--pdf-only", str(pdf_path)])

            self.assertEqual(exit_code, 0)

    def test_pdf_only_mode_skips_source_checks(self):
        """parse.unicode_mapping and layout.package.* must not appear in PDF-only output."""
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "resume.pdf"
            pdf_path.write_bytes(b"%PDF-1.7")

            with mock.patch.object(cli, "extract_pdf_text", return_value=_GOOD_EXTRACTED), \
                 mock.patch.object(cli, "read_pdf_info", return_value=_GOOD_PDF_INFO):
                # Capture the JSON report to inspect check IDs
                json_path = Path(tmp) / "report.json"
                with contextlib.redirect_stdout(io.StringIO()):
                    cli.main(["--pdf-only", str(pdf_path), "--json", str(json_path)])

            import json
            report = json.loads(json_path.read_text())
            check_ids = {c["id"] for c in report["checks"]}

            self.assertNotIn("parse.unicode_mapping", check_ids)
            self.assertFalse(any(cid.startswith("layout.package.") for cid in check_ids))

    def test_pdf_only_mode_missing_pdf_returns_error(self):
        out = io.StringIO()
        with contextlib.redirect_stderr(out):
            exit_code = cli.main(["--pdf-only", "/nonexistent/resume.pdf"])
        self.assertEqual(exit_code, 2)

    def test_pdf_only_mode_no_source_argument_returns_error(self):
        out = io.StringIO()
        with contextlib.redirect_stderr(out):
            exit_code = cli.main(["--pdf-only"])
        self.assertEqual(exit_code, 2)

    def test_latex_mode_missing_tex_returns_error(self):
        out = io.StringIO()
        with contextlib.redirect_stderr(out):
            exit_code = cli.main(["/nonexistent/resume.tex"])
        self.assertEqual(exit_code, 2)
