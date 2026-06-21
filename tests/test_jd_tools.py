"""Tests for jd_tools and the keywords.jd_match check."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from ats_resume_checker.jd_tools import _strip_html, extract_keywords, fetch_jd_from_url
from ats_resume_checker.checks import run_checks


# ---------------------------------------------------------------------------
# _strip_html
# ---------------------------------------------------------------------------

class StripHtmlTests(unittest.TestCase):
    def test_strips_tags(self):
        result = _strip_html("<p>Hello <b>world</b></p>")
        self.assertIn("Hello", result)
        self.assertIn("world", result)
        self.assertNotIn("<p>", result)

    def test_plain_text_unchanged(self):
        text = "Python Docker Kubernetes"
        self.assertEqual(_strip_html(text), text)

    def test_ignores_script_content(self):
        result = _strip_html("<script>alert('xss')</script><p>keep this</p>")
        self.assertNotIn("alert", result)
        self.assertIn("keep this", result)


# ---------------------------------------------------------------------------
# extract_keywords
# ---------------------------------------------------------------------------

SAMPLE_JD = """
We are looking for a Senior Software Engineer with experience in Python and
machine learning. The ideal candidate will have strong Python skills, experience
with Docker, Kubernetes, and CI/CD pipelines. Experience with machine learning
frameworks such as PyTorch or TensorFlow is required. Knowledge of Python testing
frameworks (pytest) and Docker containers is a plus.
"""


class ExtractKeywordsTests(unittest.TestCase):
    def test_empty_string_returns_empty_list(self):
        self.assertEqual(extract_keywords(""), [])

    def test_whitespace_only_returns_empty_list(self):
        self.assertEqual(extract_keywords("   \n  "), [])

    def test_returns_list(self):
        result = extract_keywords(SAMPLE_JD)
        self.assertIsInstance(result, list)

    def test_detects_repeated_term(self):
        result = extract_keywords(SAMPLE_JD)
        lower = [kw.lower() for kw in result]
        self.assertIn("python", lower, "Python appears many times and should be extracted")

    def test_detects_multi_word_bigram(self):
        result = extract_keywords(SAMPLE_JD)
        lower = [kw.lower() for kw in result]
        self.assertIn("machine learning", lower, "machine learning bigram should be extracted")

    def test_no_single_char_tokens(self):
        result = extract_keywords(SAMPLE_JD)
        for kw in result:
            self.assertGreater(len(kw), 1)

    def test_no_pure_stopwords(self):
        result = extract_keywords(SAMPLE_JD)
        lower_singles = [kw.lower() for kw in result if " " not in kw]
        stopwords = {"the", "and", "or", "with", "for", "is", "are", "in", "of"}
        for sw in stopwords:
            self.assertNotIn(sw, lower_singles)

    def test_deduplicated(self):
        result = extract_keywords(SAMPLE_JD)
        lower = [kw.lower() for kw in result]
        self.assertEqual(len(lower), len(set(lower)), "Keywords should be deduplicated")

    def test_html_job_description(self):
        html_jd = "<h1>Job Title</h1><p>We need Python expertise and Docker skills. Python and Docker are required.</p>"
        result = extract_keywords(html_jd)
        lower = [kw.lower() for kw in result]
        self.assertIn("python", lower)
        self.assertIn("docker", lower)


# ---------------------------------------------------------------------------
# fetch_jd_from_url
# ---------------------------------------------------------------------------

class FetchJdFromUrlTests(unittest.TestCase):
    def test_strips_html_from_fetched_content(self):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"<html><body><p>Python Docker</p></body></html>"
        mock_resp.headers.get_content_charset.return_value = "utf-8"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("ats_resume_checker.jd_tools.urlopen", return_value=mock_resp):
            result = fetch_jd_from_url("http://example.com/job")

        self.assertIn("Python", result)
        self.assertIn("Docker", result)
        self.assertNotIn("<p>", result)

    def test_raises_value_error_on_network_failure(self):
        with patch("ats_resume_checker.jd_tools.urlopen", side_effect=OSError("connection refused")):
            with self.assertRaises(ValueError):
                fetch_jd_from_url("http://example.com/job")


# ---------------------------------------------------------------------------
# keywords.jd_match check integration
# ---------------------------------------------------------------------------

_MINIMAL_PDF_INFO: dict = {"pages": 1, "encrypted": "no", "javascript": "no"}
_RESUME_TEXT = """
Abdelrahman Elewah  abdelrahman@example.com  +1 555 123 4567  github.com/elewah

Experience
Software Engineer at Acme Corp
Built Python microservices using Docker and Kubernetes. Developed CI/CD pipelines with GitHub Actions.
Worked on machine learning models using PyTorch.

Skills
Python, Docker, Kubernetes, PyTorch, SQL, AWS

Education
B.Sc. Computer Science
"""


class JdMatchCheckTests(unittest.TestCase):
    def test_jd_match_check_absent_when_no_jd_keywords(self):
        report = run_checks("", _RESUME_TEXT, _MINIMAL_PDF_INFO)
        check_ids = [c.id for c in report.checks]
        self.assertNotIn("keywords.jd_match", check_ids)

    def test_jd_match_check_absent_when_empty_list(self):
        report = run_checks("", _RESUME_TEXT, _MINIMAL_PDF_INFO, jd_keywords=[])
        check_ids = [c.id for c in report.checks]
        self.assertNotIn("keywords.jd_match", check_ids)

    def test_jd_match_check_present_when_jd_keywords_provided(self):
        report = run_checks("", _RESUME_TEXT, _MINIMAL_PDF_INFO, jd_keywords=["Python", "Docker"])
        check_ids = [c.id for c in report.checks]
        self.assertIn("keywords.jd_match", check_ids)

    def test_jd_match_pass_when_high_coverage(self):
        jd_kws = ["Python", "Docker", "Kubernetes"]
        report = run_checks("", _RESUME_TEXT, _MINIMAL_PDF_INFO, jd_keywords=jd_kws)
        jd_check = next(c for c in report.checks if c.id == "keywords.jd_match")
        self.assertEqual(jd_check.status, "pass")

    def test_jd_match_fail_when_low_coverage(self):
        jd_kws = ["Java", "Scala", "Hadoop", "Spark", "Hive", "Kafka", "Ruby", "Go", "Rust"]
        report = run_checks("", _RESUME_TEXT, _MINIMAL_PDF_INFO, jd_keywords=jd_kws)
        jd_check = next(c for c in report.checks if c.id == "keywords.jd_match")
        self.assertEqual(jd_check.status, "fail")

    def test_jd_match_warn_when_medium_coverage(self):
        # 3 present, 3 absent → 50% → boundary, should be pass; use 1/4 → warn
        jd_kws = ["Python", "Java", "Scala", "Hadoop"]  # 1/4 = 25% → warn
        report = run_checks("", _RESUME_TEXT, _MINIMAL_PDF_INFO, jd_keywords=jd_kws)
        jd_check = next(c for c in report.checks if c.id == "keywords.jd_match")
        self.assertIn(jd_check.status, {"warn", "fail"})

    def test_jd_match_score_penalised_on_fail(self):
        jd_kws = ["Java", "Scala", "Hadoop", "Spark", "Hive", "Kafka", "Ruby", "Go", "Rust"]
        report_with = run_checks("", _RESUME_TEXT, _MINIMAL_PDF_INFO, jd_keywords=jd_kws)
        report_without = run_checks("", _RESUME_TEXT, _MINIMAL_PDF_INFO)
        self.assertLess(report_with.score, report_without.score)

    def test_jd_match_result_stored_on_report(self):
        jd_kws = ["Python", "Docker"]
        report = run_checks("", _RESUME_TEXT, _MINIMAL_PDF_INFO, jd_keywords=jd_kws)
        self.assertIsNotNone(report.jd_match)
        self.assertIn("matched", report.jd_match)
        self.assertIn("missing", report.jd_match)
        self.assertIn("match_pct", report.jd_match)

    def test_jd_match_result_none_when_no_jd_keywords(self):
        report = run_checks("", _RESUME_TEXT, _MINIMAL_PDF_INFO)
        self.assertIsNone(report.jd_match)


if __name__ == "__main__":
    unittest.main()
