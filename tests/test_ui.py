import unittest
from unittest import mock

from ats_resume_checker import ui


class UiHelperTests(unittest.TestCase):
    def test_parse_keywords_dedupes_and_falls_back_to_defaults(self):
        self.assertEqual(ui.parse_keywords("Python\nRAG\nPython\n\nAWS"), ["Python", "RAG", "AWS"])
        self.assertIn("Python", ui.parse_keywords(""))

    def test_analyze_uploaded_resume_uses_pdf_tools_and_checks(self):
        tex_bytes = rb"""
        \input{glyphtounicode}
        \pdfgentounicode=1
        \section{Summary}
        \section{Technical Skills}
        \section{Professional Experience}
        \section{Education}
        \section{Projects}
        Python RAG AWS Docker
        """
        extracted = """
        Ada Lovelace
        ada@example.com | +1 555-555-5555 | linkedin.com/in/ada | github.com/ada
        Summary
        Technical Skills
        Professional Experience
        Education
        Projects
        Python RAG AWS Docker
        """ * 5

        with mock.patch.object(ui, "extract_pdf_text", return_value=extracted), mock.patch.object(
            ui, "read_pdf_info", return_value={"pages": 2, "encrypted": "no", "javascript": "no"}
        ):
            analysis = ui.analyze_uploaded_resume(tex_bytes, b"%PDF-1.7", keywords=["Python", "RAG"])

        self.assertEqual(analysis.extracted_text, extracted)
        self.assertEqual(analysis.pdf_info["pages"], 2)
        self.assertIn("Python", analysis.report.keywords["found"])

    def test_status_counts_and_top_fixes(self):
        report = mock.Mock()
        report.checks = [
            mock.Mock(status="pass", fix=""),
            mock.Mock(status="warn", fix="Fix layout"),
            mock.Mock(status="warn", fix="Fix layout"),
            mock.Mock(status="fail", fix="Add email"),
        ]

        self.assertEqual(ui.summarize_status_counts(report), {"pass": 1, "warn": 2, "fail": 1})
        self.assertEqual(ui.top_fixes(report), ["Fix layout", "Add email"])
