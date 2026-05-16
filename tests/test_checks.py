import unittest

from ats_resume_checker.checks import run_checks


GOOD_TEX = r"""
\input{glyphtounicode}
\pdfgentounicode=1
\section{Summary}
\section{Technical Skills}
\section{Professional Experience}
\section{Education}
\section{Projects}
Python LLMs RAG LangChain LangGraph FastAPI PostgreSQL Docker AWS MLOps computer vision document intelligence semantic search model deployment
"""


GOOD_TEXT = """
Ada Lovelace
ada@example.com | +1 555-555-5555 | LinkedIn: linkedin.com/in/ada | GitHub: github.com/ada

Summary
Technical Skills
Professional Experience
Education
Projects

Python LLMs RAG LangChain LangGraph FastAPI PostgreSQL Docker AWS MLOps computer vision document intelligence semantic search model deployment
"""


class ChecksTests(unittest.TestCase):
    def test_run_checks_passes_clean_resume_signals(self):
        report = run_checks(GOOD_TEX, GOOD_TEXT, {"pages": 2, "encrypted": "no", "javascript": "no"})

        self.assertGreaterEqual(report.score, 80)
        self.assertTrue(any(check.id == "contact.email" and check.status == "pass" for check in report.checks))
        self.assertTrue(any(check.id == "section.experience" and check.status == "pass" for check in report.checks))
        self.assertIn("Python", report.keywords["found"])

    def test_run_checks_flags_missing_email_and_too_many_pages(self):
        report = run_checks(r"\section{Summary}", "Not much text", {"pages": 4, "encrypted": "yes"})

        failures = {check.id for check in report.checks if check.status == "fail"}

        self.assertIn("contact.email", failures)
        self.assertIn("parse.text_volume", failures)
        self.assertIn("parse.encrypted", failures)
