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
from collections.abc import Callable
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
    base_url: str | None = None,
    aws_access_key_id: str | None = None,
    aws_secret_access_key: str | None = None,
    aws_profile: str | None = None,
    aws_region: str = "us-east-1",
    message_callback: Callable[[str], None] | None = None,
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

        extra_env: dict[str, str] = {}
        if api_key:
            extra_env["ANTHROPIC_API_KEY"] = api_key
        if base_url:
            extra_env["ANTHROPIC_BASE_URL"] = base_url.rstrip("/")
            # LM Studio doesn't validate the key but the claude CLI requires a non-empty value.
            extra_env.setdefault("ANTHROPIC_API_KEY", "lm-studio")
        if aws_profile:
            extra_env["CLAUDE_CODE_USE_BEDROCK"] = "1"
            extra_env["AWS_PROFILE"] = aws_profile
            extra_env["AWS_REGION"] = aws_region
            extra_env["AWS_DEFAULT_REGION"] = aws_region
        elif aws_access_key_id and aws_secret_access_key:
            extra_env["CLAUDE_CODE_USE_BEDROCK"] = "1"
            extra_env["AWS_ACCESS_KEY_ID"] = aws_access_key_id
            extra_env["AWS_SECRET_ACCESS_KEY"] = aws_secret_access_key
            extra_env["AWS_REGION"] = aws_region
            extra_env["AWS_DEFAULT_REGION"] = aws_region

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
                            if message_callback is not None:
                                message_callback(block.text)
        except Exception as sdk_exc:
            # Two known non-fatal patterns where the CLI exits non-zero but changes
            # are already on disk:
            #   "error result: success"    — CLI exits 1 after a completed run
            #   "maximum number of turns"  — turn budget exhausted mid-run
            exc_str = str(sdk_exc)
            is_recoverable = (
                "error result: success" in exc_str
                or "maximum number of turns" in exc_str
            )
            if not is_recoverable:
                raise
            combined = " ".join(progress_messages).lower()
            if any(kw in combined for kw in ("credit balance", "insufficient credit", "billing", "out of credit")):
                raise RuntimeError(
                    "Claude Code has insufficient credits to run the agent. "
                    "Options:\n"
                    "• Add credits at console.anthropic.com\n"
                    "• Enter an Anthropic API key in the UI to use API credits instead"
                ) from sdk_exc
            # Recoverable exit — changes are on disk, collect results normally.
            if "maximum number of turns" in exc_str:
                progress_messages.append(
                    "_Note: the agent reached its turn limit. Results below reflect the "
                    "partial improvements made before the limit was hit. Increase 'Max iterations' to allow more work._"
                )
            else:
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
    base_url: str | None = None,
    aws_access_key_id: str | None = None,
    aws_secret_access_key: str | None = None,
    aws_profile: str | None = None,
    aws_region: str = "us-east-1",
    message_callback: Callable[[str], None] | None = None,
) -> AgentResult:
    """Run the Claude Agent SDK resume improvement agent synchronously.

    Provider selection (mutually exclusive):
    - Default: claude CLI uses its own auth (claude.ai subscription)
    - api_key set: Anthropic API credits
    - base_url set: local model via LM Studio (http://127.0.0.1:1234)
    - aws_access_key_id + aws_secret_access_key set: AWS Bedrock

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
                    base_url=base_url,
                    aws_access_key_id=aws_access_key_id,
                    aws_secret_access_key=aws_secret_access_key,
                    aws_profile=aws_profile,
                    aws_region=aws_region,
                    message_callback=message_callback,
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
