"""AI agent that iteratively improves a LaTeX resume for ATS compliance.

Uses the Claude Agent SDK (claude-agent-sdk). The agent gets a temp directory
containing resume.tex and resume.pdf, and uses built-in Read/Edit/Write/Bash
tools to fix ATS issues — running ats-check, latexmk, and pdftoppm as shell
commands rather than through custom tool implementations.

Requires:
  pip install -e ".[agent]"   # installs claude-agent-sdk
  ANTHROPIC_API_KEY env var
"""

from __future__ import annotations

import asyncio
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .checks import AtsReport, run_checks
from .pdf_to_png import pdf_pages_to_png
from .pdf_tools import PdfToolError, extract_pdf_text, read_pdf_info

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are an expert LaTeX resume editor specializing in ATS (Applicant Tracking System) compliance.

Your goal is to improve the resume's ATS score by editing resume.tex to fix failing and warning checks. Do not change the candidate's actual content, credentials, or claims.

## Workflow
1. Run the ATS checker to see current issues:
     ats-check resume.tex --no-compile --pdf resume.pdf --json report.json
   Then read report.json to see score, failing checks, and suggested fixes.

2. Read resume.tex to understand the source.

3. Fix the highest-impact issues first: "fail" checks cost 15 pts each, "warn" checks cost 5 pts each.
   Use the Edit tool for targeted changes. Use Write if you need to rewrite a section.

4. After editing, recompile:
     latexmk -pdf -interaction=nonstopmode resume.tex

5. Re-check to confirm improvement:
     ats-check resume.tex --no-compile --pdf resume.pdf

6. Repeat until the score is maximized or you cannot improve further.

7. Visual check (optional but recommended):
     pdftoppm -png -r 150 resume.pdf page

If ats-check is not on PATH, use: python -m ats_resume_checker.cli <args>

## Rules
- NEVER change factual content: employer names, job titles, dates, degrees, skills, descriptions.
- NEVER add skills or experience the candidate did not already include.
- You MAY add LaTeX preamble directives, reformat structure, fix packages, rename section headings.
- If a LaTeX build fails, read the error output, fix the syntax, and retry immediately.
- Make targeted edits — avoid rewriting the entire document unless truly necessary.

## Common ATS Fixes by Check ID

**parse.unicode_mapping** (WARN → PASS)
Add to preamble before \\begin{document}:
  \\input{glyphtounicode}
  \\pdfgentounicode=1

**contact.email** (FAIL)
Ensure email appears as selectable text:
  \\href{mailto:user@example.com}{user@example.com}

**layout.package.fontawesome / fontawesome5** (WARN)
Replace icon-only decorations with plain text labels ("LinkedIn:" instead of \\faLinkedin).

**layout.package.paracol / multicol** (WARN)
Convert two-column layout to single-column using \\section + itemize blocks.

**layout.package.tabularx / tabular** (WARN)
Replace skill grid tables with \\begin{itemize} lists or comma-separated inline text.

**section.*** (WARN/FAIL)
Use \\section{Conventional Name}: Summary, Technical Skills, Professional Experience, Education, Projects.

**keywords.coverage** (WARN/FAIL)
Move keywords from source_only into plain extractable bullet text, not inside \\href anchors or nested macros.
"""

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class AgentResult:
    final_score: int
    initial_score: int
    improved_tex: str
    final_report: AtsReport | None
    png_pages: list[bytes]
    progress_messages: list[str]
    error: str | None = None


# ---------------------------------------------------------------------------
# Async core
# ---------------------------------------------------------------------------


async def _run_agent_async(
    tex_bytes: bytes,
    pdf_bytes: bytes,
    max_turns: int,
    model: str,
    max_pages: int,
    keywords: list[str],
    api_key: str | None = None,
) -> AgentResult:
    try:
        from claude_agent_sdk import query, ClaudeAgentOptions, AssistantMessage
        from claude_agent_sdk.types import TextBlock
    except ImportError as exc:
        raise RuntimeError(
            "claude-agent-sdk is not installed. Run: pip install -e '.[agent]'"
        ) from exc

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        tex_path = tmp_path / "resume.tex"
        pdf_path = tmp_path / "resume.pdf"
        tex_path.write_bytes(tex_bytes)
        pdf_path.write_bytes(pdf_bytes)

        # Compute initial score before the agent touches anything.
        initial_tex = tex_bytes.decode("utf-8")
        extracted = extract_pdf_text(pdf_path)
        pdf_info = read_pdf_info(pdf_path)
        initial_report = run_checks(
            initial_tex, extracted, pdf_info, max_pages=max_pages, keywords=keywords
        )

        # Only pass env when an explicit API key is provided; otherwise let the
        # claude CLI use its own authentication (claude.ai subscription, etc.).
        extra_env: dict[str, str] = {"ANTHROPIC_API_KEY": api_key} if api_key else {}

        options = ClaudeAgentOptions(
            system_prompt=_SYSTEM_PROMPT,
            allowed_tools=["Read", "Edit", "Write", "Bash"],
            permission_mode="acceptEdits",
            cwd=str(tmp_path),
            model=model,
            max_turns=max_turns,
            **({"env": extra_env} if extra_env else {}),
        )

        failing = [c.id for c in initial_report.checks if c.status == "fail"]
        warning = [c.id for c in initial_report.checks if c.status == "warn"]
        prompt = (
            f"resume.tex currently scores {initial_report.score}/100.\n"
            f"Failing checks (−15 pts each): {failing}\n"
            f"Warning checks (−5 pts each): {warning}\n\n"
            "Improve the score by editing resume.tex. Follow the workflow in your instructions.\n"
            "The compiled PDF is already at resume.pdf — use --no-compile for the first ats-check.\n"
            "Do not change any factual content (employer names, dates, credentials, skills)."
        )

        progress_messages: list[str] = []
        try:
            async for message in query(prompt=prompt, options=options):
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            progress_messages.append(block.text)
        except Exception as sdk_exc:
            # "error result: success" is a known SDK pattern: the claude CLI exits
            # non-zero after a completed run. Check whether progress_messages contain
            # a billing error before treating this as a graceful recovery.
            if "error result: success" not in str(sdk_exc):
                raise
            combined = " ".join(progress_messages).lower()
            if any(kw in combined for kw in ("credit balance", "insufficient credit", "billing", "out of credit")):
                raise RuntimeError(
                    "Claude Code has insufficient credits to run the agent. "
                    "Options:\n"
                    "• Add credits at console.anthropic.com\n"
                    "• Enter an Anthropic API key in the UI to use API credits instead"
                ) from sdk_exc
            # No billing signal — the CLI exited non-zero after a genuinely completed
            # run (a known behaviour in some Claude Code versions). File changes are on
            # disk so we collect results normally.
            progress_messages.append(
                "_Note: the agent completed but the CLI reported a non-zero exit. "
                "Results below reflect the final state of the resume._"
            )

        # Read final state from disk after the agent has finished.
        final_tex = tex_path.read_text(encoding="utf-8") if tex_path.exists() else initial_tex

        final_report: AtsReport | None = None
        if pdf_path.exists():
            try:
                final_extracted = extract_pdf_text(pdf_path)
                final_pdf_info = read_pdf_info(pdf_path)
                final_report = run_checks(
                    final_tex, final_extracted, final_pdf_info,
                    max_pages=max_pages, keywords=keywords,
                )
            except Exception:
                pass

        png_pages: list[bytes] = []
        if pdf_path.exists():
            try:
                png_pages = pdf_pages_to_png(pdf_path)
            except PdfToolError:
                pass

        return AgentResult(
            final_score=final_report.score if final_report else initial_report.score,
            initial_score=initial_report.score,
            improved_tex=final_tex,
            final_report=final_report or initial_report,
            png_pages=png_pages,
            progress_messages=progress_messages,
        )


# ---------------------------------------------------------------------------
# Public API (sync wrapper around the async core)
# ---------------------------------------------------------------------------


def run_improvement_agent(
    tex_bytes: bytes,
    pdf_bytes: bytes,
    max_iterations: int = 3,
    model: str = "claude-sonnet-4-6",
    max_pages: int = 2,
    keywords: list[str] | None = None,
    api_key: str | None = None,
) -> AgentResult:
    """Run the Claude Agent SDK resume improvement agent synchronously.

    By default the claude CLI uses its own authentication (claude.ai login,
    ANTHROPIC_API_KEY env var, etc.). Pass api_key to explicitly use Anthropic
    API credits instead of claude.ai subscription credits.

    Spawns a daemon thread so asyncio.run() always gets a clean event loop,
    which is safe regardless of whether Streamlit has its own loop running.
    """
    # Each iteration is roughly 8 SDK turns (read → check → edit → compile → recheck…)
    max_turns = max_iterations * 8 + 5

    result_holder: dict[str, Any] = {}
    error_holder: dict[str, Any] = {}

    def _thread() -> None:
        try:
            result_holder["v"] = asyncio.run(
                _run_agent_async(
                    tex_bytes=tex_bytes,
                    pdf_bytes=pdf_bytes,
                    max_turns=max_turns,
                    model=model,
                    max_pages=max_pages,
                    keywords=keywords or [],
                    api_key=api_key,
                )
            )
        except Exception as exc:
            error_holder["v"] = exc

    t = threading.Thread(target=_thread, daemon=True)
    t.start()
    t.join()

    if "v" in error_holder:
        raise error_holder["v"]
    return result_holder["v"]
