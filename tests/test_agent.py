import sys
import unittest
from unittest import mock

from ats_resume_checker.agent import AgentResult, AgentEvent
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
        jd_match=None,
        pdf_info={"pages": 1},
        extracted_text="Jane Doe jane@example.com Experience Software Engineer",
    )


def _make_sdk_mock():
    """Return (mock_sdk, mock_types) injectable into sys.modules.

    Append messages to ``mock_sdk.messages`` before running the agent to
    simulate content blocks from the SDK.  Using a shared mutable list ensures
    that isinstance() checks in the agent loop work because the blocks are
    instances of the exact same class objects stored on mock_sdk/mock_types.
    """
    # Real classes so isinstance() checks work in the agent loop.
    AssistantMessage = type("AssistantMessage", (), {"usage": None})
    ResultMessage = type("ResultMessage", (), {
        "total_cost_usd": None, "usage": None, "num_turns": 0, "duration_ms": 0,
    })
    TextBlock = type("TextBlock", (), {"text": ""})
    ToolUseBlock = type("ToolUseBlock", (), {"id": "", "name": "", "input": {}})
    ToolResultBlock = type("ToolResultBlock", (), {"tool_use_id": "", "content": None, "is_error": None})

    messages_holder: list = []

    async def _fake_query(*, prompt, options):
        for m in messages_holder:
            yield m
        return

    mock_sdk = mock.MagicMock()
    mock_sdk.query = _fake_query
    mock_sdk.ClaudeAgentOptions = mock.MagicMock(return_value=mock.MagicMock())
    mock_sdk.AssistantMessage = AssistantMessage
    mock_sdk.ResultMessage = ResultMessage
    mock_sdk.ToolUseBlock = ToolUseBlock
    mock_sdk.ToolResultBlock = ToolResultBlock
    mock_sdk.messages = messages_holder  # tests append to this list

    mock_types = mock.MagicMock()
    mock_types.TextBlock = TextBlock

    return mock_sdk, mock_types


def _make_assistant_msg(mock_sdk, blocks, usage=None):
    """Build a fake AssistantMessage with the given content blocks."""
    msg = object.__new__(mock_sdk.AssistantMessage)
    msg.content = blocks
    msg.usage = usage
    return msg


def _make_text_block(mock_types, text):
    blk = object.__new__(mock_types.TextBlock)
    blk.text = text
    return blk


def _make_tool_use_block(mock_sdk, name, inp, bid="id1"):
    blk = object.__new__(mock_sdk.ToolUseBlock)
    blk.id = bid
    blk.name = name
    blk.input = inp
    return blk


def _make_tool_result_block(mock_sdk, content, tool_use_id="id1", is_error=False):
    blk = object.__new__(mock_sdk.ToolResultBlock)
    blk.tool_use_id = tool_use_id
    blk.content = content
    blk.is_error = is_error
    return blk


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

    def test_events_list_populated_with_text_event(self):
        """AgentResult.events should contain a 'text' AgentEvent for each text block."""
        mock_sdk, mock_types = _make_sdk_mock()
        text_blk = _make_text_block(mock_types, "I will fix the unicode mapping.")
        mock_sdk.messages.append(_make_assistant_msg(mock_sdk, [text_blk]))
        result = _run_agent(mock_sdk, mock_types)
        self.assertTrue(any(e.kind == "text" for e in result.events))
        self.assertTrue(any("unicode" in e.content for e in result.events))

    def test_events_list_has_tool_call_event(self):
        """AgentResult.events should capture ToolUseBlock as a 'tool_call' event."""
        mock_sdk, mock_types = _make_sdk_mock()
        tool_blk = _make_tool_use_block(mock_sdk, "Bash", {"command": "latexmk -pdf resume.tex"})
        mock_sdk.messages.append(_make_assistant_msg(mock_sdk, [tool_blk]))
        result = _run_agent(mock_sdk, mock_types)
        tool_events = [e for e in result.events if e.kind == "tool_call"]
        self.assertTrue(len(tool_events) >= 1)
        self.assertEqual(tool_events[0].data["tool"], "Bash")
        self.assertIn("latexmk", tool_events[0].content)

    def test_events_list_has_tool_result_event(self):
        """AgentResult.events should capture ToolResultBlock as a 'tool_result' event."""
        mock_sdk, mock_types = _make_sdk_mock()
        result_blk = _make_tool_result_block(mock_sdk, "Compilation successful.", tool_use_id="id1")
        mock_sdk.messages.append(_make_assistant_msg(mock_sdk, [result_blk]))
        result = _run_agent(mock_sdk, mock_types)
        result_events = [e for e in result.events if e.kind == "tool_result"]
        self.assertTrue(len(result_events) >= 1)
        self.assertIn("successful", result_events[0].content)

    def test_session_dir_is_set(self):
        """AgentResult.session_dir should be a non-empty string pointing to a real directory."""
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            mock_sdk, mock_types = _make_sdk_mock()
            result = _run_agent(mock_sdk, mock_types, session_base=tmp)
        self.assertIsNotNone(result.session_dir)
        self.assertIsInstance(result.session_dir, str)
        # Directory was created inside tmp (now cleaned up) — just check it's a non-empty string
        self.assertTrue(len(result.session_dir) > 0)

    def test_message_callback_receives_agent_events(self):
        """message_callback should be called with AgentEvent objects for tool calls."""
        mock_sdk, mock_types = _make_sdk_mock()
        tool_blk = _make_tool_use_block(mock_sdk, "Read", {"file_path": "resume.tex"})
        mock_sdk.messages.append(_make_assistant_msg(mock_sdk, [tool_blk]))
        received = []
        _run_agent(mock_sdk, mock_types, message_callback=received.append)
        tool_events = [m for m in received if hasattr(m, "kind") and m.kind == "tool_call"]
        self.assertTrue(len(tool_events) >= 1)
        self.assertEqual(tool_events[0].data["tool"], "Read")
