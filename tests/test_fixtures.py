"""Integration tests using compiled fixture PDFs as a validation dataset.

Each fixture in tests/fixtures/ is a LaTeX resume with documented intentional
ATS issues. These tests run run_checks() against the fixture PDF (and .tex
source) and assert that the checker catches exactly the expected issues —
no false positives, no missed detections.

Fixtures are pre-compiled PDFs committed alongside their .tex sources.
The tests do NOT recompile; they call ats_resume_checker.checks.run_checks()
directly using Poppler to extract text, the same path the CLI and UI take.

Running the suite requires Poppler (pdftotext, pdfinfo) to be installed.
Skip markers are applied automatically if Poppler is unavailable.
"""

from __future__ import annotations

import unittest
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def _poppler_available() -> bool:
    import shutil
    return bool(shutil.which("pdftotext") and shutil.which("pdfinfo"))


def _load_fixture(tex_name: str, pdf_name: str | None = None):
    """Return (tex_source, extracted_text, pdf_info) for a fixture."""
    from ats_resume_checker.pdf_tools import extract_pdf_text, read_pdf_info
    pdf_name = pdf_name or tex_name.replace(".tex", ".pdf")
    tex_path = FIXTURES / tex_name
    pdf_path = FIXTURES / pdf_name
    tex_source = tex_path.read_text(encoding="utf-8") if tex_path.exists() else ""
    extracted = extract_pdf_text(pdf_path)
    pdf_info = read_pdf_info(pdf_path)
    return tex_source, extracted, pdf_info


@unittest.skipUnless(_poppler_available(), "Poppler (pdftotext/pdfinfo) not installed")
class FixtureCleanTests(unittest.TestCase):
    """sample_clean — baseline: 100/100, all PASS.

    Verifies the checker does not produce false positives on a well-formed,
    single-column resume with all contact fields, standard sections, unicode
    hints, and good keyword coverage.
    """

    @classmethod
    def setUpClass(cls):
        from ats_resume_checker.checks import run_checks
        tex, text, info = _load_fixture("sample_clean.tex")
        cls.report = run_checks(tex, text, info)
        cls.ids = {c.id: c for c in cls.report.checks}

    def test_score_is_100(self):
        self.assertEqual(self.report.score, 100)

    def test_no_failures(self):
        failures = [c.id for c in self.report.checks if c.status == "fail"]
        self.assertEqual(failures, [], f"Unexpected failures: {failures}")

    def test_no_warnings(self):
        warnings = [c.id for c in self.report.checks if c.status == "warn"]
        self.assertEqual(warnings, [], f"Unexpected warnings: {warnings}")

    def test_all_contact_fields_pass(self):
        for cid in ("contact.name", "contact.email", "contact.phone", "contact.links"):
            self.assertEqual(self.ids[cid].status, "pass", f"{cid} should be PASS")

    def test_all_sections_pass(self):
        for cid in ("section.summary", "section.skills", "section.experience",
                    "section.education", "section.projects"):
            self.assertEqual(self.ids[cid].status, "pass", f"{cid} should be PASS")

    def test_unicode_mapping_pass(self):
        self.assertEqual(self.ids["parse.unicode_mapping"].status, "pass")

    # ── PDF-only mode ────────────────────────────────────────────────
    def test_pdf_only_also_scores_100(self):
        from ats_resume_checker.checks import run_checks
        _, text, info = _load_fixture("sample_clean.tex")
        report = run_checks("", text, info)
        self.assertEqual(report.score, 100)

    def test_pdf_only_skips_unicode_check(self):
        from ats_resume_checker.checks import run_checks
        _, text, info = _load_fixture("sample_clean.tex")
        report = run_checks("", text, info)
        ids = {c.id for c in report.checks}
        self.assertNotIn("parse.unicode_mapping", ids)


@unittest.skipUnless(_poppler_available(), "Poppler not installed")
class FixtureHiddenEmailNoUnicodeTests(unittest.TestCase):
    """sample_hidden_email_no_unicode — email hidden in href + no unicode hints.

    Expected:
      FAIL  contact.email          (href has no visible text)
      WARN  parse.unicode_mapping  (glyphtounicode commented out — not active)
    """

    @classmethod
    def setUpClass(cls):
        from ats_resume_checker.checks import run_checks
        tex, text, info = _load_fixture("sample_hidden_email_no_unicode.tex")
        cls.report = run_checks(tex, text, info)
        cls.ids = {c.id: c for c in cls.report.checks}

    def test_contact_email_fails(self):
        self.assertEqual(self.ids["contact.email"].status, "fail",
                         "Email hidden in empty href should FAIL")

    def test_unicode_mapping_warns(self):
        self.assertEqual(self.ids["parse.unicode_mapping"].status, "warn",
                         "Commented-out glyphtounicode must not be a false-positive PASS")

    def test_no_other_failures(self):
        unexpected = [c.id for c in self.report.checks
                      if c.status == "fail" and c.id != "contact.email"]
        self.assertEqual(unexpected, [], f"Unexpected extra failures: {unexpected}")

    def test_score_reflects_one_fail_one_warn(self):
        # 100 − 15 (email fail) − 5 (unicode warn) = 75, minus any keyword warns
        self.assertLessEqual(self.report.score, 80)

    def test_pdf_only_has_no_unicode_check(self):
        from ats_resume_checker.checks import run_checks
        _, text, info = _load_fixture("sample_hidden_email_no_unicode.tex")
        report = run_checks("", text, info)
        ids = {c.id for c in report.checks}
        self.assertNotIn("parse.unicode_mapping", ids,
                         "PDF-only mode must not include parse.unicode_mapping")

    def test_pdf_only_still_catches_hidden_email(self):
        from ats_resume_checker.checks import run_checks
        _, text, info = _load_fixture("sample_hidden_email_no_unicode.tex")
        report = run_checks("", text, info)
        ids = {c.id: c for c in report.checks}
        self.assertEqual(ids["contact.email"].status, "fail",
                         "Hidden email must still FAIL in PDF-only mode")


@unittest.skipUnless(_poppler_available(), "Poppler not installed")
class FixtureTwoColumnParacolTests(unittest.TestCase):
    """sample_two_column_paracol — paracol layout + non-standard section names.

    Expected:
      WARN  layout.package.paracol
      WARN  section.summary, section.skills, section.experience, section.education
    """

    @classmethod
    def setUpClass(cls):
        from ats_resume_checker.checks import run_checks
        tex, text, info = _load_fixture("sample_two_column_paracol.tex")
        cls.report_latex = run_checks(tex, text, info)
        cls.report_pdf = run_checks("", text, info)

    def test_paracol_package_warns(self):
        ids = {c.id: c for c in self.report_latex.checks}
        self.assertEqual(ids["layout.package.paracol"].status, "warn")

    def test_non_standard_sections_warn(self):
        ids = {c.id: c for c in self.report_latex.checks}
        for cid in ("section.summary", "section.skills",
                    "section.experience", "section.education"):
            self.assertEqual(ids[cid].status, "warn",
                             f"{cid} should WARN (non-standard heading)")

    def test_pdf_only_skips_paracol_check(self):
        ids = {c.id for c in self.report_pdf.checks}
        self.assertNotIn("layout.package.paracol", ids,
                         "PDF-only mode must skip layout.package.paracol")

    def test_pdf_only_scores_higher_than_latex(self):
        """PDF-only skips paracol warn → score must be >= LaTeX score."""
        self.assertGreaterEqual(self.report_pdf.score, self.report_latex.score)

    def test_pdf_only_still_warns_on_missing_sections(self):
        ids = {c.id: c for c in self.report_pdf.checks}
        for cid in ("section.summary", "section.skills", "section.experience"):
            self.assertEqual(ids[cid].status, "warn",
                             f"{cid} should still WARN in PDF-only mode")


@unittest.skipUnless(_poppler_available(), "Poppler not installed")
class FixtureTableSkillsFontawesomeTests(unittest.TestCase):
    """sample_table_skills_fontawesome — fontawesome5 icons + tabularx skills grid.

    Expected:
      WARN  layout.package.fontawesome5
      WARN  layout.package.tabularx
    """

    @classmethod
    def setUpClass(cls):
        from ats_resume_checker.checks import run_checks
        tex, text, info = _load_fixture("sample_table_skills_fontawesome.tex")
        cls.report_latex = run_checks(tex, text, info)
        cls.report_pdf = run_checks("", text, info)

    def test_fontawesome5_warns(self):
        ids = {c.id: c for c in self.report_latex.checks}
        self.assertEqual(ids["layout.package.fontawesome5"].status, "warn")

    def test_tabularx_warns(self):
        ids = {c.id: c for c in self.report_latex.checks}
        self.assertEqual(ids["layout.package.tabularx"].status, "warn")

    def test_no_failures(self):
        failures = [c.id for c in self.report_latex.checks if c.status == "fail"]
        self.assertEqual(failures, [], f"Unexpected failures: {failures}")

    def test_pdf_only_skips_both_package_checks(self):
        ids = {c.id for c in self.report_pdf.checks}
        self.assertNotIn("layout.package.fontawesome5", ids)
        self.assertNotIn("layout.package.tabularx", ids)

    def test_pdf_only_scores_10_pts_higher(self):
        """Two WARN checks skipped → PDF-only score should be exactly 10 pts higher
        (unless other checks also differ, in which case it is at least 10 pts higher)."""
        delta = self.report_pdf.score - self.report_latex.score
        self.assertGreaterEqual(delta, 10,
                                f"Expected ≥10 pt gain in PDF-only, got {delta}")


@unittest.skipUnless(_poppler_available(), "Poppler not installed")
class FixtureMissingContactSectionsTests(unittest.TestCase):
    """sample_missing_contact_sections — missing contact, thin sections, no keywords.

    Expected FAILs   : contact.email, keywords.coverage, parse.text_volume
    Expected WARNs   : contact.name, contact.phone, contact.links,
                       section.summary, section.skills, section.projects
    """

    @classmethod
    def setUpClass(cls):
        from ats_resume_checker.checks import run_checks
        tex, text, info = _load_fixture("sample_missing_contact_sections.tex")
        cls.report = run_checks(tex, text, info)
        cls.ids = {c.id: c for c in cls.report.checks}

    def test_email_fails(self):
        self.assertEqual(self.ids["contact.email"].status, "fail")

    def test_keywords_fails(self):
        self.assertEqual(self.ids["keywords.coverage"].status, "fail")

    def test_text_volume_fails(self):
        self.assertEqual(self.ids["parse.text_volume"].status, "fail",
                         "Sparse resume should have < 500 chars extracted")

    def test_contact_name_warns(self):
        self.assertEqual(self.ids["contact.name"].status, "warn",
                         "Single-word name should not be recognised")

    def test_contact_phone_warns_with_correct_message(self):
        check = self.ids["contact.phone"]
        self.assertEqual(check.status, "warn")
        self.assertIn("No phone", check.message,
                      "WARN message should say 'No phone', not the pass phrasing")

    def test_contact_links_warns_with_correct_message(self):
        check = self.ids["contact.links"]
        self.assertEqual(check.status, "warn")
        self.assertIn("No LinkedIn", check.message,
                      "WARN message should say 'No LinkedIn', not the pass phrasing")

    def test_missing_sections_warn(self):
        for cid in ("section.summary", "section.skills", "section.projects"):
            self.assertEqual(self.ids[cid].status, "warn", f"{cid} should WARN")

    def test_score_is_very_low(self):
        self.assertLessEqual(self.report.score, 25,
                             "Resume with 3 FAILs + many WARNs should score ≤25")

    def test_pdf_only_scores_equal_or_higher(self):
        """PDF-only skips parse.unicode_mapping (which WARNs on this fixture because
        glyphtounicode is commented out) → PDF-only score is 5 pts higher than LaTeX."""
        from ats_resume_checker.checks import run_checks
        _, text, info = _load_fixture("sample_missing_contact_sections.tex")
        report_pdf = run_checks("", text, info)
        self.assertGreaterEqual(report_pdf.score, self.report.score,
                                "PDF-only must never score lower than LaTeX mode")
        # The only skipped check is parse.unicode_mapping (WARN = -5 pts)
        self.assertEqual(report_pdf.score - self.report.score, 5,
                         "Exactly one WARN skipped → exactly +5 pts in PDF-only")


@unittest.skipUnless(_poppler_available(), "Poppler not installed")
class FixtureSummaryTests(unittest.TestCase):
    """Cross-fixture sanity checks."""

    def _report(self, name):
        from ats_resume_checker.checks import run_checks
        tex, text, info = _load_fixture(f"{name}.tex")
        return run_checks(tex, text, info)

    def test_clean_beats_all_others(self):
        clean_score = self._report("sample_clean").score
        for name in ("sample_hidden_email_no_unicode",
                     "sample_two_column_paracol",
                     "sample_table_skills_fontawesome",
                     "sample_missing_contact_sections"):
            self.assertGreaterEqual(clean_score, self._report(name).score,
                                    f"clean should score >= {name}")

    def test_missing_contact_has_lowest_score(self):
        missing = self._report("sample_missing_contact_sections").score
        for name in ("sample_clean",
                     "sample_hidden_email_no_unicode",
                     "sample_two_column_paracol",
                     "sample_table_skills_fontawesome"):
            self.assertLessEqual(missing, self._report(name).score,
                                 f"missing_contact should score <= {name}")
