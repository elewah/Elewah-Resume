import unittest

from ats_resume_checker.latex import extract_sections, normalize_latex_text


class LatexTests(unittest.TestCase):
    def test_normalize_latex_text_extracts_common_resume_text(self):
        source = r"""
        \section{Technical Skills}
        \textbf{Languages:} Python, C/C++
        \href{https://github.com/example}{github.com/example}
        \item Built RAG systems with 95\% accuracy.
        """

        text = normalize_latex_text(source)

        self.assertIn("Technical Skills", text)
        self.assertIn("Languages:", text)
        self.assertIn("Python", text)
        self.assertIn("github.com/example", text)
        self.assertIn("95%", text)

    def test_extract_sections_from_source(self):
        source = r"\section{Summary}\section{Professional Experience}\section{Education}"

        self.assertEqual(extract_sections(source), ["Summary", "Professional Experience", "Education"])
