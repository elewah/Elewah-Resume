import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ats_resume_checker import cli


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

            extracted = """
            Ada Lovelace
            ada@example.com | +1 555-555-5555 | linkedin.com/in/ada | github.com/ada
            Summary
            Technical Skills
            Professional Experience
            Education
            Projects
            Python LLMs RAG LangChain LangGraph FastAPI PostgreSQL Docker AWS MLOps computer vision document intelligence semantic search model deployment
            """ * 5

            with mock.patch.object(cli, "extract_pdf_text", return_value=extracted), mock.patch.object(
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
