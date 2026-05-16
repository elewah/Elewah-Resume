import unittest

from ats_resume_checker.pdf_tools import parse_pdfinfo


class PdfToolsTests(unittest.TestCase):
    def test_parse_pdfinfo_converts_pages_to_int(self):
        output = """
    Title:           Example Resume
    Author:          Ada Lovelace
    Pages:           2
    Encrypted:       no
    JavaScript:      no
    """

        info = parse_pdfinfo(output)

        self.assertEqual(info["title"], "Example Resume")
        self.assertEqual(info["author"], "Ada Lovelace")
        self.assertEqual(info["pages"], 2)
        self.assertEqual(info["encrypted"], "no")
