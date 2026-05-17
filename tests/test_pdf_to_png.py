import unittest
from pathlib import Path
from unittest import mock

from ats_resume_checker.pdf_to_png import pdf_pages_to_png
from ats_resume_checker.pdf_tools import PdfToolError


class PdfToPngTests(unittest.TestCase):
    def _make_fake_pdftoppm(self, page_contents: list[bytes]):
        """Return a side_effect callable that writes fake PNG files to the temp dir."""

        def fake_run(cmd, **kwargs):
            prefix = Path(cmd[-1])
            for i, data in enumerate(page_contents, start=1):
                (prefix.parent / f"page-{i}.png").write_bytes(data)
            return mock.Mock(returncode=0, stderr=b"")

        return fake_run

    @mock.patch("ats_resume_checker.pdf_to_png.shutil.which", return_value="/usr/bin/pdftoppm")
    @mock.patch("ats_resume_checker.pdf_to_png.subprocess.run")
    def test_returns_png_bytes_per_page(self, mock_run, _mock_which):
        page1 = b"FAKEPNG1"
        page2 = b"FAKEPNG2"
        mock_run.side_effect = self._make_fake_pdftoppm([page1, page2])

        result = pdf_pages_to_png(Path("resume.pdf"), dpi=150)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], page1)
        self.assertEqual(result[1], page2)

    @mock.patch("ats_resume_checker.pdf_to_png.shutil.which", return_value="/usr/bin/pdftoppm")
    @mock.patch("ats_resume_checker.pdf_to_png.subprocess.run")
    def test_passes_dpi_to_command(self, mock_run, _mock_which):
        mock_run.side_effect = self._make_fake_pdftoppm([b"PNG"])

        pdf_pages_to_png(Path("resume.pdf"), dpi=200)

        cmd = mock_run.call_args[0][0]
        self.assertIn("-r", cmd)
        self.assertIn("200", cmd)

    @mock.patch("ats_resume_checker.pdf_to_png.shutil.which", return_value=None)
    def test_raises_when_pdftoppm_missing(self, _mock_which):
        with self.assertRaises(PdfToolError) as ctx:
            pdf_pages_to_png(Path("resume.pdf"))
        self.assertIn("pdftoppm", str(ctx.exception))

    @mock.patch("ats_resume_checker.pdf_to_png.shutil.which", return_value="/usr/bin/pdftoppm")
    @mock.patch("ats_resume_checker.pdf_to_png.subprocess.run")
    def test_raises_on_nonzero_return(self, mock_run, _mock_which):
        mock_run.return_value = mock.Mock(returncode=1, stderr=b"some poppler error")

        with self.assertRaises(PdfToolError) as ctx:
            pdf_pages_to_png(Path("resume.pdf"))
        self.assertIn("some poppler error", str(ctx.exception))

    @mock.patch("ats_resume_checker.pdf_to_png.shutil.which", return_value="/usr/bin/pdftoppm")
    @mock.patch("ats_resume_checker.pdf_to_png.subprocess.run")
    def test_single_page(self, mock_run, _mock_which):
        mock_run.side_effect = self._make_fake_pdftoppm([b"SINGLEPAGE"])

        result = pdf_pages_to_png(Path("resume.pdf"))

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], b"SINGLEPAGE")
