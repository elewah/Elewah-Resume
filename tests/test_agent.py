import sys
import unittest
from unittest import mock

from ats_resume_checker.agent import AgentResult
import ats_resume_checker.agent as _agent_mod


FAKE_TEX = r"""
\documentclass{article}
\begin{document}
Jane Doe
jane@example.com
\section{Experience}
Software Engineer at Acme, 2020--2024
\end{document}
"""

FAKE_PDF_BYTES = b"%PDF-1.4 fake pdf content"


def _make_fake_report(score: int = 85):
    from ats_resume_checker.checks import AtsReport, CheckResult

    return AtsReport(
        score=score,
        checks=[
            CheckResult(
                id="parse.unicode_mapping",
                title="Unicode mapping",
                status="warn",
                message="glyphtounicode not found",
                fix=r"Add \input{glyphtounicode}",
            )
        ],
        source_sections=["Experience"],
        extracted_sections=["Experience"],
        keywords={"found": ["python"], "missing": [], "source_only": []},
        pdf_info={"pages": 1},
        extracted_text="Jane Doe jane@example.com Experience Software Engineer",
    )


def _make_sdk_mock():
    """Return (mock_sdk, mock_types) injectable into sys.modules."""

    async def _fake_query(*, prompt, options):
        # Yields nothing — agent completes immediately with no messages
        return
        yield

    mock_sdk = mock.MagicMock()
    mock_sdk.query = _fake_query
    mock_sdk.ClaudeAgentOptions = mock.MagicMock(return_value=mock.MagicMock())
    # Real class so isinstance(message, AssistantMessage) works as expected
    mock_sdk.AssistantMessage = type("AssistantMessage", (), {})

    mock_types = mock.MagicMock()
    mock_types.TextBlock = type("TextBlock", (), {"text": ""})

    return mock_sdk, mock_types


def _run_agent(mock_sdk, mock_types, tex=FAKE_TEX, pdf=FAKE_PDF_BYTES,
               fake_report=None, **kwargs):
    """Run run_improvement_agent with all external dependencies mocked.

    No api_key parameter — authentication is handled by the claude CLI.
    """
    fake_report = fake_report or _make_fake_report()
    with mock.patch.dict(sys.modules, {
        "claude_agent_sdk": mock_sdk,
        "claude_agent_sdk.types": mock_types,
    }):
        # Patch names directly in the already-imported agent module namespace.
        with (
            mock.patch.object(_agent_mod, "extract_pdf_text", return_value="text"),
            mock.patch.object(_agent_mod, "read_pdf_info", return_value={"pages": 1}),
            mock.patch.object(_agent_mod, "run_checks", return_value=fake_report),
            mock.patch.object(_agent_mod, "pdf_pages_to_png", return_value=[b"PNG"]),
        ):
            return _agent_mod.run_improvement_agent(
                tex_bytes=tex.encode() if isinstance(tex, str) else tex,
                pdf_bytes=pdf,
                **kwargs,
            )


class AgentSdkTests(unittest.TestCase):

    def test_returns_agent_result(self):
        mock_sdk, mock_types = _make_sdk_mock()
        result = _run_agent(mock_sdk, mock_types, max_iterations=1)
        self.assertIsInstance(result, AgentResult)

    def test_initial_score_from_run_checks(self):
        mock_sdk, mock_types = _make_sdk_mock()
        result = _run_agent(mock_sdk, mock_types, fake_report=_make_fake_report(score=70))
        self.assertEqual(result.initial_score, 70)

    def test_empty_progress_messages_when_no_text_output(self):
        mock_sdk, mock_types = _make_sdk_mock()
        result = _run_agent(mock_sdk, mock_types)
        self.assertEqual(result.progress_messages, [])

    def test_png_pages_collected(self):
        mock_sdk, mock_types = _make_sdk_mock()
        result = _run_agent(mock_sdk, mock_types)
        self.assertEqual(result.png_pages, [b"PNG"])

    def test_improved_tex_in_result(self):
        mock_sdk, mock_types = _make_sdk_mock()
        result = _run_agent(mock_sdk, mock_types, tex=FAKE_TEX)
        self.assertIsInstance(result.improved_tex, str)
        self.assertIn("documentclass", result.improved_tex)

    def test_max_turns_scales_with_iterations(self):
        """max_turns passed to ClaudeAgentOptions should be max_iterations*8+5."""
        captured: dict = {}

        def capturing_options(**kwargs):
            captured.update(kwargs)
            return mock.MagicMock()

        mock_sdk, mock_types = _make_sdk_mock()
        mock_sdk.ClaudeAgentOptions = mock.MagicMock(side_effect=capturing_options)

        _run_agent(mock_sdk, mock_types, max_iterations=3)

        self.assertIn("max_turns", captured)
        self.assertEqual(captured["max_turns"], 29)  # 3 * 8 + 5

    def test_no_env_override_in_options(self):
        """ClaudeAgentOptions should not receive an env dict — auth is left to the CLI."""
        captured: dict = {}

        def capturing_options(**kwargs):
            captured.update(kwargs)
            return mock.MagicMock()

        mock_sdk, mock_types = _make_sdk_mock()
        mock_sdk.ClaudeAgentOptions = mock.MagicMock(side_effect=capturing_options)

        _run_agent(mock_sdk, mock_types)

        self.assertNotIn("env", captured)

    def test_error_result_success_is_recovered(self):
        """'error result: success' from the CLI should be caught and treated as a completed run."""

        async def _query_raises(**kwargs):
            yield  # yield nothing — simulate no AssistantMessage
            raise Exception("Claude Code returned an error result: success")

        mock_sdk, mock_types = _make_sdk_mock()
        mock_sdk.query = _query_raises

        result = _run_agent(mock_sdk, mock_types)

        # Should succeed (not raise), and the note should be in progress_messages
        self.assertIsInstance(result, AgentResult)
        self.assertTrue(any("non-zero exit" in m for m in result.progress_messages))

    def test_other_sdk_errors_are_reraise(self):
        """Non-'success' SDK errors should propagate as normal exceptions."""

        async def _query_raises(**kwargs):
            yield
            raise RuntimeError("Connection refused")

        mock_sdk, mock_types = _make_sdk_mock()
        mock_sdk.query = _query_raises

        with self.assertRaises(RuntimeError):
            _run_agent(mock_sdk, mock_types)

    def test_missing_claude_agent_sdk_raises(self):
        """Should raise RuntimeError or ImportError when sdk is missing."""
        with mock.patch.dict(sys.modules, {"claude_agent_sdk": None, "claude_agent_sdk.types": None}):
            with (
                mock.patch.object(_agent_mod, "extract_pdf_text", return_value=""),
                mock.patch.object(_agent_mod, "read_pdf_info", return_value={}),
                mock.patch.object(_agent_mod, "run_checks", return_value=_make_fake_report()),
            ):
                with self.assertRaises((RuntimeError, ImportError, TypeError)):
                    _agent_mod.run_improvement_agent(
                        tex_bytes=b"x",
                        pdf_bytes=b"y",
                    )
