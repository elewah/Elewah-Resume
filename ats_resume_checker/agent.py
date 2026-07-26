"""AI agent that iteratively improves a LaTeX resume for ATS compliance.

Uses the Claude Agent SDK (claude-agent-sdk). The agent gets a workspace directory
containing every uploaded .tex file (e.g. main.tex + preamble.tex + sections/*.tex,
preserving that relative layout so \\input{}/\\include{} resolves) plus the PDF,
and uses built-in Read/Edit/Write/Bash tools to fix ATS issues — running ats-check,
latexmk, and pdftoppm as shell commands rather than through custom tool
implementations. Whichever uploaded file is named main.tex is treated as the
compile entry point; for a legacy single-file upload, that one file is the entry
point instead.

If no .tex files are uploaded at all ("generation mode" — tex_files={}), there's
nothing to edit, so the workspace is seeded differently: the uploaded PDF is kept
as original_resume.pdf (a stable reference — not overwritten by the agent's own
compile), its extracted text as original_resume_text.txt, and the actual
.claude/skills/resume-writer/ skill directory is copied in as resume_writer_skill/
so the sandboxed agent can read and follow it — skills aren't otherwise
discoverable inside this SDK sandbox the way they are in a real Claude Code
session. The system prompt tells it to run that skill first, then fall into the
normal compile/check/refine loop below once main.tex exists.

Requires:
  pip install -e ".[agent]"   # installs claude-agent-sdk
  ANTHROPIC_API_KEY env var
"""

from __future__ import annotations

import asyncio
import json
import shutil
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .checks import AtsReport, run_checks
from .latex import resolve_includes
from .pdf_to_png import pdf_pages_to_png
from .pdf_tools import PdfToolError, extract_pdf_text, read_pdf_info

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SECTION_FILE_HINTS = {
    "header.tex": "name, contact line, links",
    "summary.tex": "Summary section",
    "skills.tex": "Technical Skills section",
    "experience.tex": "Professional Experience section (job bullets)",
    "education.tex": "Education section",
    "projects.tex": "Projects section",
}


def _describe_file(rel_path: str) -> str:
    basename = Path(rel_path).name
    if basename in _SECTION_FILE_HINTS:
        return f"{rel_path} — {_SECTION_FILE_HINTS[basename]}"
    if basename == "preamble.tex":
        return f"{rel_path} — packages, colors, macros, spacing (styling only, no resume content)"
    return rel_path


def _file_map_section(entry_tex: str, other_files: list[str]) -> str:
    """Describe the split-file layout to the agent, or "" for a single-file upload."""
    if not other_files:
        return ""
    listing = "\n".join(f"- {_describe_file(f)}" for f in sorted(other_files))
    return (
        f"\n## File map\n"
        f"{entry_tex} is a thin shell — it only contains \\input{{...}} lines. "
        f"The actual resume content lives here:\n{listing}\n\n"
        f"Open and edit only the ONE file that matches your fix — don't load the whole "
        f"resume for a small change, and don't touch {entry_tex} itself for a content edit. "
        f"Only touch a preamble file for styling/macro/package changes, never for content.\n"
    )


_SYSTEM_PROMPT_TEMPLATE = """You are an expert LaTeX resume editor specializing in ATS (Applicant Tracking System) compliance.

Your goal is to improve the resume's ATS score by editing <<ENTRY_TEX>> — or, if it's a thin shell, the specific file it \\input{}s that matches the fix (see File map below) — to fix failing and warning checks. Do not change the candidate's actual content, credentials, or claims.
<<STARTING_FROM_SCRATCH>>
<<FILE_MAP>>
## Workflow
1. Run the ATS checker to see current issues:
     ats-check <<ENTRY_TEX>> --no-compile --pdf <<ENTRY_PDF>> --json report.json
   Then read report.json to see score, failing checks, and suggested fixes. This
   resolves \\input{}/\\include{} automatically, so it reflects the full resume
   even if <<ENTRY_TEX>> itself is just a shell.

2. Read <<ENTRY_TEX>> to understand the source, then open the specific file that
   contains what you need to fix (see File map below if the resume is split).

3. Fix the highest-impact issues first: "fail" checks cost 15 pts each, "warn" checks cost 5 pts each.
   Use the Edit tool for targeted changes. Use Write if you need to rewrite a section.

4. After editing, recompile:
     latexmk -pdf -interaction=nonstopmode <<ENTRY_TEX>>

5. Re-check to confirm improvement:
     ats-check <<ENTRY_TEX>> --no-compile --pdf <<ENTRY_PDF>>

6. Repeat until the score is maximized or you cannot improve further.

7. Visual check (optional but recommended):
     pdftoppm -png -r 150 <<ENTRY_PDF>> page

If ats-check is not on PATH, use: python -m ats_resume_checker.cli <args>

## Rules
- NEVER change factual content: employer names, job titles, dates, degrees, skills, descriptions.
- NEVER add skills or experience the candidate did not already include.
- You MAY add LaTeX preamble directives, reformat structure, fix packages, rename section headings.
- If a LaTeX build fails, read the error output, fix the syntax, and retry immediately.
- Make targeted edits — avoid rewriting the entire document unless truly necessary.

## Common ATS Fixes by Check ID

**parse.unicode_mapping** (WARN → PASS)
Add to the preamble (preamble.tex if the resume is split) before \\begin{document}:
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

## JD Keyword Verification (run this as a final step if job description keywords were provided)

After you have maximised the ATS score, run this verification pass:

  python -c "
import json, pathlib
from ats_resume_checker.latex import resolve_includes
tex = resolve_includes(pathlib.Path('<<ENTRY_TEX>>')).lower()
report = json.loads(pathlib.Path('report.json').read_text())
jd = report.get('jd_match') or {}
missing = jd.get('missing', [])
found_now = [k for k in missing if k.lower() in tex]
still_missing = [k for k in missing if k.lower() not in tex]
print('JD keywords now covered:', found_now)
print('Still missing from resume:', still_missing)
print(f'Coverage: {len(jd.get(\"matched\",[]))+len(found_now)} / {jd.get(\"total\",0)}')
"

Report the output so the user can see which terms are covered and which are not.
Do NOT add keywords that are not truthfully represented in the candidate's experience.
"""


def _starting_from_scratch_section(entry_tex: str) -> str:
    return (
        f"\n## Starting from scratch\n"
        f"No {entry_tex} exists yet — only a PDF. Before anything else:\n\n"
        f"1. Read resume_writer_skill/SKILL.md in full and follow it to generate {entry_tex}, "
        f"preamble.tex, and sections/*.tex from the candidate's real content. Their current "
        f"resume is available as original_resume.pdf (the PDF they uploaded) and "
        f"original_resume_text.txt (its extracted text, for convenience). Use "
        f"resume_writer_skill/assets/ as your templates exactly as SKILL.md instructs — copy "
        f"preamble.tex verbatim, follow the section examples' structure.\n\n"
        f"2. This is a non-interactive run: you cannot ask the candidate follow-up questions. "
        f"If a detail is genuinely missing or ambiguous in their content (not just awkwardly "
        f"formatted), leave it out rather than inventing it, and note the gap in your final "
        f"summary — don't stop and wait for an answer that will never come.\n\n"
        f"Once {entry_tex} and its sections exist, continue with the workflow below to compile, "
        f"check, and refine.\n"
    )


def _build_system_prompt(
    entry_tex: str, entry_pdf: str, other_files: list[str], generation_mode: bool = False
) -> str:
    prompt = _SYSTEM_PROMPT_TEMPLATE.replace("<<ENTRY_TEX>>", entry_tex).replace("<<ENTRY_PDF>>", entry_pdf)
    if generation_mode:
        prompt = prompt.replace("<<STARTING_FROM_SCRATCH>>", _starting_from_scratch_section(entry_tex))
        # other_files is empty in generation mode (nothing exists yet) — describe the target
        # structure being created so the file map still renders, instead of a second code path.
        target_files = ["preamble.tex"] + [f"sections/{name}" for name in _SECTION_FILE_HINTS]
        return prompt.replace("<<FILE_MAP>>", _file_map_section(entry_tex, target_files))
    prompt = prompt.replace("<<STARTING_FROM_SCRATCH>>", "")
    return prompt.replace("<<FILE_MAP>>", _file_map_section(entry_tex, other_files))

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class AgentEvent:
    """A single typed event from the agent trace."""
    kind: str    # "text" | "tool_call" | "tool_result" | "usage" | "usage_final" | "iteration"
    content: str  # human-readable summary (truncated for tool_result)
    data: dict    # raw structured payload


@dataclass
class UsageSummary:
    """Cumulative token usage and cost for an agent run."""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    total_cost_usd: float | None = None
    num_turns: int = 0
    duration_ms: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def to_dict(self) -> dict:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_creation_tokens": self.cache_creation_tokens,
            "total_tokens": self.total_tokens,
            "total_cost_usd": self.total_cost_usd,
            "num_turns": self.num_turns,
            "duration_ms": self.duration_ms,
        }


@dataclass
class AgentResult:
    final_score: int
    initial_score: int
    improved_tex: str
    final_report: AtsReport | None
    png_pages: list[bytes]
    progress_messages: list[str]
    error: str | None = None
    events: list[AgentEvent] = field(default_factory=list)
    session_dir: str | None = None
    usage: UsageSummary = field(default_factory=UsageSummary)
    pdf_bytes: bytes = b""
    # Actual per-file content after the run, keyed by the same relative paths
    # passed in via tex_files (e.g. "main.tex", "preamble.tex",
    # "sections/experience.tex") — unlike improved_tex (a single flattened,
    # \input-resolved string), this preserves which file(s) the agent
    # actually touched, for re-applying the edits to a split repo.
    final_tex_files: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _summarize_input(inp: dict) -> str:
    """Return a short human-readable summary of a tool input dict."""
    if "command" in inp:
        return inp["command"]
    if "file_path" in inp:
        path = inp["file_path"]
        if "old_string" in inp:
            preview = inp["old_string"][:60].replace("\n", "↵")
            return f"{path} — edit: {preview!r}…"
        return path
    return json.dumps(inp, ensure_ascii=False)[:120]


def _write_tex_files(base_dir: Path, tex_files: dict[str, bytes]) -> None:
    """Write each relative-path -> bytes entry under base_dir, creating subdirs as needed."""
    for rel_path, content in tex_files.items():
        target = base_dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


def _init_session(
    session_base: Path,
    started_at: datetime,
    tex_files: dict[str, bytes],
    pdf_bytes: bytes,
    entry_pdf: str,
    initial_report: AtsReport,
    keywords: list[str],
    jd_keywords: list[str],
    jd_text: str | None,
    model: str,
    max_turns: int,
    prompt: str,
    generation_mode: bool = False,
    extracted_text: str = "",
) -> tuple[Path, Path] | tuple[None, None]:
    """Create session dir + workspace/, write all inputs, return (session_dir, workspace_dir).

    In generation_mode (no tex_files — nothing to edit yet), the uploaded PDF is written as
    original_resume.pdf rather than as entry_pdf: entry_pdf ("main.pdf") doesn't exist until the
    agent compiles the main.tex it's about to create, and pre-seeding it with the uploaded bytes
    would just get silently overwritten by that first compile, destroying the only reference copy
    of the candidate's actual content. The resume_writer_skill/ copy is what lets the sandboxed
    agent follow the same skill an interactive Claude Code session would use for this — it has no
    other way to discover it.
    """
    try:
        timestamp = started_at.strftime("%Y%m%d_%H%M%S")
        session_dir = session_base / f"{timestamp}_resume"
        session_dir.mkdir(parents=True, exist_ok=True)

        # inputs/ — everything the agent was given (read-only reference copies)
        inputs_dir = session_dir / "inputs"
        inputs_dir.mkdir(exist_ok=True)
        _write_tex_files(inputs_dir, tex_files)
        (inputs_dir / entry_pdf).write_bytes(pdf_bytes)
        if keywords:
            (inputs_dir / "keywords.txt").write_text("\n".join(keywords), encoding="utf-8")
        if jd_text:
            (inputs_dir / "jd.txt").write_text(jd_text, encoding="utf-8")
        if jd_keywords:
            (inputs_dir / "jd_keywords.txt").write_text("\n".join(jd_keywords), encoding="utf-8")
        (inputs_dir / "initial_report.json").write_text(
            json.dumps(initial_report.to_dict(), indent=2), encoding="utf-8"
        )
        (inputs_dir / "prompt.txt").write_text(prompt, encoding="utf-8")

        # workspace/ — the agent's live working directory
        workspace_dir = session_dir / "workspace"
        workspace_dir.mkdir(exist_ok=True)
        _write_tex_files(workspace_dir, tex_files)
        if generation_mode:
            (workspace_dir / "original_resume.pdf").write_bytes(pdf_bytes)
            (workspace_dir / "original_resume_text.txt").write_text(extracted_text, encoding="utf-8")
            # Existence of skill_src is validated by the caller before _init_session runs — a
            # failure here would otherwise be swallowed by the except Exception below and silently
            # fall back to a broken (non-generation-mode) workspace instead of surfacing clearly.
            skill_src = Path(__file__).parent.parent / ".claude" / "skills" / "resume-writer"
            shutil.copytree(skill_src, workspace_dir / "resume_writer_skill")
        else:
            (workspace_dir / entry_pdf).write_bytes(pdf_bytes)

        # session.json — partial, updated at completion
        (session_dir / "session.json").write_text(
            json.dumps(
                {
                    "started_at": started_at.isoformat(),
                    "model": model,
                    "max_turns": max_turns,
                    "initial_score": initial_report.score,
                    "status": "running",
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        return session_dir, workspace_dir
    except Exception:
        return None, None


def _finalize_session(
    session_dir: Path,
    workspace_dir: Path,
    entry_pdf: str,
    final_report: AtsReport | None,
    initial_score: int,
    events: list[AgentEvent],
    final_tex: str,
    final_tex_files: dict[str, str],
    usage: UsageSummary,
    iter_count: int,
) -> None:
    """Write results and trace after the agent finishes."""
    try:
        # trace.jsonl
        with (session_dir / "trace.jsonl").open("w", encoding="utf-8") as f:
            for event in events:
                f.write(
                    json.dumps({"kind": event.kind, "content": event.content, "data": event.data})
                    + "\n"
                )

        # plan.md — first agent text block
        text_events = [e for e in events if e.kind == "text"]
        if text_events:
            (session_dir / "plan.md").write_text(text_events[0].content, encoding="utf-8")

        # Final ATS report
        if final_report:
            (session_dir / "final_report.json").write_text(
                json.dumps(final_report.to_dict(), indent=2), encoding="utf-8"
            )

        # improved_resume.tex at session root — a single flattened, \input-resolved
        # convenience copy, useful for a quick read even when the resume is split.
        (session_dir / "improved_resume.tex").write_text(final_tex, encoding="utf-8")

        # final_files/ — the actual per-file state the agent left behind, preserving
        # the original relative layout (main.tex, preamble.tex, sections/*.tex, ...).
        if final_tex_files:
            final_files_dir = session_dir / "final_files"
            for rel_path, content in final_tex_files.items():
                target = final_files_dir / rel_path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")

        # final_resume.pdf at session root (copy from workspace)
        workspace_pdf = workspace_dir / entry_pdf
        if workspace_pdf.exists():
            shutil.copy2(workspace_pdf, session_dir / "final_resume.pdf")

        # Update session.json with final stats
        final_score = final_report.score if final_report else initial_score
        session_meta = json.loads((session_dir / "session.json").read_text(encoding="utf-8"))
        session_meta.update(
            {
                "status": "complete",
                "final_score": final_score,
                "score_delta": final_score - initial_score,
                "iterations": iter_count,
                "num_events": len(events),
                "tool_calls": sum(1 for e in events if e.kind == "tool_call"),
                "usage": usage.to_dict(),
            }
        )
        (session_dir / "session.json").write_text(
            json.dumps(session_meta, indent=2), encoding="utf-8"
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Async core
# ---------------------------------------------------------------------------


async def _run_agent_async(
    tex_files: dict[str, bytes],
    pdf_bytes: bytes,
    max_turns: int,
    model: str,
    max_pages: int,
    keywords: list[str],
    jd_keywords: list[str],
    jd_text: str | None,
    session_base: Path,
    api_key: str | None = None,
    base_url: str | None = None,
    aws_access_key_id: str | None = None,
    aws_secret_access_key: str | None = None,
    aws_profile: str | None = None,
    aws_region: str = "us-east-1",
    message_callback: Callable[[str | AgentEvent], None] | None = None,
) -> AgentResult:
    try:
        from claude_agent_sdk import (
            query,
            ClaudeAgentOptions,
            AssistantMessage,
            ResultMessage,
            ToolUseBlock,
            ToolResultBlock,
        )
        from claude_agent_sdk.types import TextBlock
    except ImportError as exc:
        raise RuntimeError(
            "claude-agent-sdk is not installed. Run: pip install -e '.[agent]'"
        ) from exc

    started_at = datetime.now()

    generation_mode = not tex_files
    entry_tex = "main.tex" if generation_mode or "main.tex" in tex_files else next(iter(tex_files))
    entry_pdf = f"{Path(entry_tex).stem}.pdf"
    other_files = sorted(f for f in tex_files if f != entry_tex)

    resume_writer_skill_dir = Path(__file__).parent.parent / ".claude" / "skills" / "resume-writer"
    if generation_mode and not resume_writer_skill_dir.is_dir():
        raise RuntimeError(
            f"No .tex file was uploaded, so generating one from scratch requires the "
            f"resume-writer skill, which was not found at {resume_writer_skill_dir}. "
            f"Upload a .tex file to edit instead, or restore that skill directory."
        )

    # Compute initial score (needs a temp PDF on disk for pdftotext, and the
    # full file set on disk for resolve_includes to follow \input/\include).
    # We write to a throwaway temp dir only for this pre-flight check;
    # the real workspace is created by _init_session below.
    import tempfile
    with tempfile.TemporaryDirectory() as _pre:
        _pre_path = Path(_pre)
        (_pre_path / "preflight.pdf").write_bytes(pdf_bytes)
        _write_tex_files(_pre_path, tex_files)
        initial_tex = resolve_includes(_pre_path / entry_tex)
        extracted = extract_pdf_text(_pre_path / "preflight.pdf")
        pdf_info = read_pdf_info(_pre_path / "preflight.pdf")

    initial_report = run_checks(
        initial_tex, extracted, pdf_info,
        max_pages=max_pages, keywords=keywords,
        jd_keywords=jd_keywords or None,
    )

    extra_env: dict[str, str] = {}
    if api_key:
        extra_env["ANTHROPIC_API_KEY"] = api_key
    if base_url:
        extra_env["ANTHROPIC_BASE_URL"] = base_url.rstrip("/")
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

    failing = [c.id for c in initial_report.checks if c.status == "fail"]
    warning = [c.id for c in initial_report.checks if c.status == "warn"]

    jd_section = ""
    if initial_report.jd_match:
        missing_jd = initial_report.jd_match.get("missing", [])
        matched_jd = initial_report.jd_match.get("matched", [])
        match_pct = initial_report.jd_match.get("match_pct", 0)
        jd_section = (
            f"\nJob description match: {match_pct:.0%} "
            f"({len(matched_jd)} of {initial_report.jd_match.get('total', 0)} JD keywords found).\n"
            f"Missing JD keywords (add these to the resume if genuinely applicable): {missing_jd}\n"
            "If a missing keyword reflects real experience the candidate has, add it in plain text. "
            "NEVER invent or fabricate experience."
        )

    if generation_mode:
        prompt = (
            f"No LaTeX resume exists yet for this candidate — only a PDF. In PDF-only mode it "
            f"currently scores {initial_report.score}/100.\n"
            f"{jd_section}\n"
            f"Generate {entry_tex} + preamble.tex + sections/*.tex from the candidate's real "
            f"content — see resume_writer_skill/SKILL.md, and original_resume.pdf / "
            f"original_resume_text.txt for their current resume. Then continue with the normal "
            f"workflow in your instructions to compile, check, and refine.\n"
            "Do not invent any factual content (employer names, dates, credentials, skills) "
            "beyond what's in their PDF."
        )
    else:
        prompt = (
            f"{entry_tex} currently scores {initial_report.score}/100.\n"
            f"Failing checks (−15 pts each): {failing}\n"
            f"Warning checks (−5 pts each): {warning}\n"
            f"{jd_section}\n"
            f"Improve the score by editing the file(s) that need it — see the File map in your "
            f"instructions if the resume is split across multiple files. Follow the workflow in "
            f"your instructions.\n"
            f"The compiled PDF is already at {entry_pdf} — use --no-compile for the first ats-check.\n"
            "Do not change any factual content (employer names, dates, credentials, skills)."
        )

    # Create the session directory NOW so all inputs are on disk before the agent starts.
    session_dir_path, workspace_dir = _init_session(
        session_base=session_base,
        started_at=started_at,
        tex_files=tex_files,
        pdf_bytes=pdf_bytes,
        entry_pdf=entry_pdf,
        initial_report=initial_report,
        keywords=keywords,
        jd_keywords=jd_keywords,
        jd_text=jd_text,
        model=model,
        max_turns=max_turns,
        prompt=prompt,
        generation_mode=generation_mode,
        extracted_text=extracted,
    )

    # If session init failed, fall back to a temp directory so the agent can still run.
    if workspace_dir is None:
        import tempfile as _tf
        _fallback_tmp = _tf.mkdtemp()
        workspace_dir = Path(_fallback_tmp)
        _write_tex_files(workspace_dir, tex_files)
        if generation_mode:
            (workspace_dir / "original_resume.pdf").write_bytes(pdf_bytes)
            (workspace_dir / "original_resume_text.txt").write_text(extracted, encoding="utf-8")
            shutil.copytree(resume_writer_skill_dir, workspace_dir / "resume_writer_skill")
        else:
            (workspace_dir / entry_pdf).write_bytes(pdf_bytes)

    tex_path = workspace_dir / entry_tex
    pdf_path = workspace_dir / entry_pdf

    options = ClaudeAgentOptions(
        system_prompt=_build_system_prompt(entry_tex, entry_pdf, other_files, generation_mode=generation_mode),
        allowed_tools=["Read", "Edit", "Write", "Bash"],
        permission_mode="acceptEdits",
        cwd=str(workspace_dir),
        model=model,
        max_turns=max_turns,
        **({"env": extra_env} if extra_env else {}),
    )

    progress_messages: list[str] = []
    events: list[AgentEvent] = []
    usage = UsageSummary()
    iter_count = 0
    _pending_latexmk = False  # True when last ToolUseBlock was a latexmk call

    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                # Accumulate per-turn token usage
                if message.usage:
                    u = message.usage
                    usage.input_tokens += u.get("input_tokens", 0)
                    usage.output_tokens += u.get("output_tokens", 0)
                    usage.cache_read_tokens += u.get("cache_read_input_tokens", 0)
                    usage.cache_creation_tokens += u.get("cache_creation_input_tokens", 0)
                    usage.num_turns += 1
                    usage_event = AgentEvent(
                        kind="usage",
                        content=(
                            f"↑{u.get('input_tokens',0):,} in  "
                            f"↓{u.get('output_tokens',0):,} out  "
                            f"(cumulative: {usage.total_tokens:,} tokens)"
                        ),
                        data={"turn": usage.num_turns, "turn_usage": dict(u), "cumulative": usage.to_dict()},
                    )
                    events.append(usage_event)
                    if message_callback is not None:
                        message_callback(usage_event)

                for block in message.content:
                    if isinstance(block, TextBlock):
                        progress_messages.append(block.text)
                        event = AgentEvent(kind="text", content=block.text, data={})
                        events.append(event)
                        if message_callback is not None:
                            message_callback(event)

                    elif isinstance(block, ToolUseBlock):
                        summary = _summarize_input(block.input)
                        event = AgentEvent(
                            kind="tool_call",
                            content=summary,
                            data={"tool": block.name, "input": block.input, "id": block.id},
                        )
                        events.append(event)
                        if message_callback is not None:
                            message_callback(event)
                        # Flag if this is a latexmk compile call
                        if block.name == "Bash" and "latexmk" in block.input.get("command", ""):
                            _pending_latexmk = True

                    elif isinstance(block, ToolResultBlock):
                        raw = block.content
                        output = raw if isinstance(raw, str) else json.dumps(raw)
                        event = AgentEvent(
                            kind="tool_result",
                            content=output[:500],
                            data={
                                "tool_use_id": block.tool_use_id,
                                "output": output,
                                "is_error": block.is_error,
                            },
                        )
                        events.append(event)
                        if message_callback is not None:
                            message_callback(event)

                        # Snapshot iteration after latexmk result arrives
                        if _pending_latexmk:
                            _pending_latexmk = False
                            if not block.is_error:
                                iter_count += 1
                                try:
                                    if tex_path.exists():
                                        shutil.copy2(tex_path, workspace_dir / f"iteration_{iter_count}.tex")
                                    if pdf_path.exists():
                                        shutil.copy2(pdf_path, workspace_dir / f"iteration_{iter_count}.pdf")
                                    iter_event = AgentEvent(
                                        kind="iteration",
                                        content=f"Iteration {iter_count} snapshot saved",
                                        data={"iteration": iter_count},
                                    )
                                    events.append(iter_event)
                                    if message_callback is not None:
                                        message_callback(iter_event)
                                except Exception:
                                    pass

            elif isinstance(message, ResultMessage):
                if message.total_cost_usd is not None:
                    usage.total_cost_usd = message.total_cost_usd
                usage.num_turns = message.num_turns
                usage.duration_ms = message.duration_ms
                if message.usage:
                    u = message.usage
                    usage.input_tokens = u.get("input_tokens", usage.input_tokens)
                    usage.output_tokens = u.get("output_tokens", usage.output_tokens)
                    usage.cache_read_tokens = u.get("cache_read_input_tokens", usage.cache_read_tokens)
                    usage.cache_creation_tokens = u.get("cache_creation_input_tokens", usage.cache_creation_tokens)
                cost_str = f"${message.total_cost_usd:.4f}" if message.total_cost_usd is not None else "n/a"
                final_usage_event = AgentEvent(
                    kind="usage_final",
                    content=(
                        f"Run complete — {message.num_turns} turns  "
                        f"{usage.total_tokens:,} total tokens  "
                        f"cost: {cost_str}  "
                        f"duration: {message.duration_ms/1000:.1f}s"
                    ),
                    data={"result": {
                        "num_turns": message.num_turns,
                        "total_cost_usd": message.total_cost_usd,
                        "duration_ms": message.duration_ms,
                        "usage": message.usage,
                    }},
                )
                events.append(final_usage_event)
                if message_callback is not None:
                    message_callback(final_usage_event)

    except Exception as sdk_exc:
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
        if "maximum number of turns" in exc_str:
            note = (
                "_Note: the agent reached its turn limit. Results below reflect the "
                "partial improvements made before the limit was hit. Increase 'Max iterations' to allow more work._"
            )
        else:
            note = (
                "_Note: the agent completed but the CLI reported a non-zero exit. "
                "Results below reflect the final state of the resume._"
            )
        progress_messages.append(note)
        events.append(AgentEvent(kind="text", content=note, data={}))

    # Read final state from workspace. final_tex is the flattened, \input-resolved
    # text (matches what ats-check itself sees); final_tex_files preserves the
    # actual per-file content so edits can be reapplied to a split repo.
    final_tex = resolve_includes(tex_path) if tex_path.exists() else initial_tex
    final_tex_files: dict[str, str] = {}
    for rel_path in tex_files:
        file_path = workspace_dir / rel_path
        if file_path.exists():
            try:
                final_tex_files[rel_path] = file_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                pass

    final_report: AtsReport | None = None
    if pdf_path.exists():
        try:
            final_extracted = extract_pdf_text(pdf_path)
            final_pdf_info = read_pdf_info(pdf_path)
            final_report = run_checks(
                final_tex, final_extracted, final_pdf_info,
                max_pages=max_pages, keywords=keywords,
                jd_keywords=jd_keywords or None,
            )
        except Exception:
            pass

    png_pages: list[bytes] = []
    final_pdf_bytes: bytes = b""
    if pdf_path.exists():
        try:
            png_pages = pdf_pages_to_png(pdf_path)
        except PdfToolError:
            pass
        try:
            final_pdf_bytes = pdf_path.read_bytes()
        except Exception:
            pass

    if session_dir_path is not None:
        _finalize_session(
            session_dir=session_dir_path,
            workspace_dir=workspace_dir,
            entry_pdf=entry_pdf,
            final_report=final_report,
            initial_score=initial_report.score,
            events=events,
            final_tex=final_tex,
            final_tex_files=final_tex_files,
            usage=usage,
            iter_count=iter_count,
        )

    return AgentResult(
        final_score=final_report.score if final_report else initial_report.score,
        initial_score=initial_report.score,
        improved_tex=final_tex,
        final_report=final_report or initial_report,
        png_pages=png_pages,
        progress_messages=progress_messages,
        events=events,
        session_dir=str(session_dir_path) if session_dir_path else None,
        pdf_bytes=final_pdf_bytes,
        usage=usage,
        final_tex_files=final_tex_files,
    )


# ---------------------------------------------------------------------------
# Public API (sync wrapper around the async core)
# ---------------------------------------------------------------------------


def run_improvement_agent(
    tex_files: dict[str, bytes],
    pdf_bytes: bytes,
    max_iterations: int = 3,
    model: str = "claude-sonnet-4-6",
    max_pages: int = 2,
    keywords: list[str] | None = None,
    jd_keywords: list[str] | None = None,
    jd_text: str | None = None,
    session_base: Path | str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    aws_access_key_id: str | None = None,
    aws_secret_access_key: str | None = None,
    aws_profile: str | None = None,
    aws_region: str = "us-east-1",
    message_callback: Callable[[str | AgentEvent], None] | None = None,
) -> AgentResult:
    """Run the Claude Agent SDK resume improvement agent synchronously.

    ``tex_files`` maps relative path -> content, e.g.
    ``{"main.tex": b"...", "preamble.tex": b"...", "sections/experience.tex": b"..."}``
    (build it with ``ui.map_uploaded_tex_files``) — every file is written into the
    agent's sandbox preserving that layout, so \\input{}/\\include{} resolves there
    just as it would in the real repo. Whichever key is "main.tex" is treated as
    the compile entry point; for a legacy single-file upload, that one file is.

    Pass ``tex_files={}`` for **generation mode**: no existing resume to edit, only
    ``pdf_bytes``. The sandbox is seeded with the ``resume-writer`` skill instead,
    and the agent builds ``main.tex`` from scratch from the PDF's content before
    falling into the normal compile/check/refine loop. See this module's docstring
    for how that sandbox differs from the editing case. (Callers holding a possibly-
    ``None`` value, e.g. from UI session state, should coerce it to ``{}`` first.)

    Provider selection (mutually exclusive):
    - Default: claude CLI uses its own auth (claude.ai subscription)
    - api_key set: Anthropic API credits
    - base_url set: local model via LM Studio (http://127.0.0.1:1234)
    - aws_access_key_id + aws_secret_access_key set: AWS Bedrock

    Spawns a daemon thread so asyncio.run() always gets a clean event loop,
    which is safe regardless of whether Streamlit has its own loop running.
    """
    max_turns = max_iterations * 8 + 5
    _default_sessions = Path(__file__).parent.parent / "sessions"
    _session_base = Path(session_base) if session_base else _default_sessions

    result_holder: dict[str, Any] = {}
    error_holder: dict[str, Any] = {}

    def _thread() -> None:
        try:
            result_holder["v"] = asyncio.run(
                _run_agent_async(
                    tex_files=tex_files,
                    pdf_bytes=pdf_bytes,
                    max_turns=max_turns,
                    model=model,
                    max_pages=max_pages,
                    keywords=keywords or [],
                    jd_keywords=jd_keywords or [],
                    jd_text=jd_text,
                    session_base=_session_base,
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
