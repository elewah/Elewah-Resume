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

    def test_run_checks_keeps_full_extracted_text(self):
        long_text = GOOD_TEXT + "\n" + ("full extracted text sentinel " * 200)

        report = run_checks(GOOD_TEX, long_text, {"pages": 2, "encrypted": "no", "javascript": "no"})

        self.assertEqual(report.extracted_text, long_text.strip())
        self.assertIn("full extracted text sentinel", report.extracted_text)


class PdfOnlyModeTests(unittest.TestCase):
    """run_checks(tex_source="") activates PDF-only mode."""

    _PDF_INFO = {"pages": 1, "encrypted": "no", "javascript": "no"}

    def test_pdf_only_skips_unicode_mapping_check(self):
        report = run_checks("", GOOD_TEXT, self._PDF_INFO)
        check_ids = {c.id for c in report.checks}
        self.assertNotIn("parse.unicode_mapping", check_ids)

    def test_pdf_only_skips_layout_package_checks(self):
        tex_with_packages = r"\usepackage{fontawesome5}\usepackage{paracol}" + GOOD_TEX
        report = run_checks("", GOOD_TEXT, self._PDF_INFO)
        check_ids = {c.id for c in report.checks}
        self.assertFalse(
            any(cid.startswith("layout.package.") for cid in check_ids),
            f"Unexpected layout.package.* checks in PDF-only mode: {check_ids}",
        )

    def test_pdf_only_still_checks_contact_fields(self):
        report = run_checks("", GOOD_TEXT, self._PDF_INFO)
        check_ids = {c.id for c in report.checks}
        self.assertIn("contact.email", check_ids)
        self.assertIn("contact.phone", check_ids)

    def test_pdf_only_still_checks_sections(self):
        report = run_checks("", GOOD_TEXT, self._PDF_INFO)
        check_ids = {c.id for c in report.checks}
        self.assertIn("section.experience", check_ids)
        self.assertIn("section.education", check_ids)

    def test_pdf_only_still_checks_keywords(self):
        report = run_checks("", GOOD_TEXT, self._PDF_INFO)
        check_ids = {c.id for c in report.checks}
        self.assertIn("keywords.coverage", check_ids)

    def test_pdf_only_section_check_has_no_source_comparison_note(self):
        """When tex_source is empty, section warnings must not mention 'source'."""
        poor_text = "Ada Lovelace\nada@example.com\n" + ("filler " * 100)
        report = run_checks("", poor_text, self._PDF_INFO)
        for check in report.checks:
            if check.id.startswith("section.") and check.status == "warn":
                self.assertNotIn("source", check.message.lower(),
                                  f"Section check message leaked source comparison: {check.message}")

    def test_pdf_only_score_does_not_penalise_skipped_checks(self):
        """PDF-only mode should not penalise for skipped LaTeX checks."""
        report_with_source = run_checks(GOOD_TEX, GOOD_TEXT, self._PDF_INFO)
        report_pdf_only = run_checks("", GOOD_TEXT, self._PDF_INFO)
        # PDF-only can be equal or higher (never lower) since checks are skipped, not failed
        self.assertGreaterEqual(report_pdf_only.score, report_with_source.score - 5,
                                 "PDF-only score should not be significantly lower than LaTeX mode score")
