"""Helpers for LaTeX source normalization and optional PDF compilation."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Sequence


class BuildError(RuntimeError):
    """Raised when a LaTeX build command fails or is unavailable."""


LATEX_COMMAND_REPLACEMENTS = (
    "textbf",
    "textit",
    "emph",
    "underline",
    "mbox",
    "small",
    "normalsize",
)


def strip_comments(source: str) -> str:
    """Remove LaTeX comments while preserving escaped percent signs."""
    lines = []
    for line in source.splitlines():
        chars = []
        escaped = False
        for char in line:
            if char == "%" and not escaped:
                break
            chars.append(char)
            escaped = char == "\\" and not escaped
            if char != "\\":
                escaped = False
        lines.append("".join(chars))
    return "\n".join(lines)


def extract_sections(source: str) -> list[str]:
    """Return section titles declared with \\section{...}."""
    cleaned = strip_comments(source)
    return [
        normalize_whitespace(_latex_to_text(match.group(1)))
        for match in re.finditer(r"\\section\*?\{([^{}]+)\}", cleaned)
    ]


def normalize_latex_text(source: str) -> str:
    """Convert common LaTeX resume markup into plain-ish text.

    This is intentionally conservative. It is not a full TeX parser; it extracts
    enough source-truth signal for ATS checks and source-vs-PDF comparisons.
    """
    text = strip_comments(source)
    text = re.sub(r"\\href(?:WithoutArrow)?\{[^{}]*\}\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\section\*?\{([^{}]+)\}", r"\n\1\n", text)
    text = re.sub(r"\\begin\{[^{}]+\}|\\end\{[^{}]+\}", "\n", text)
    text = re.sub(r"\\item(?:\[[^\]]*\])?", "\n", text)
    text = text.replace(r"\&", "&").replace(r"\%", "%").replace(r"\$", "$")
    text = text.replace("~", " ")
    text = text.replace("{", " ").replace("}", " ")
    for command in LATEX_COMMAND_REPLACEMENTS:
        text = re.sub(rf"\\{command}\s*", "", text)
    text = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?", " ", text)
    text = re.sub(r"\\.", " ", text)
    return normalize_whitespace(text)


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


_INCLUDE_RE = re.compile(r"\\(?:input|include)\{([^{}]+)\}")


def resolve_includes(tex_path: Path, _seen: Optional[set[Path]] = None) -> str:
    """Read tex_path and recursively inline \\input{...}/\\include{...} targets.

    Source-based ATS checks (unicode-mapping/package detection, section and
    keyword diagnostics) only ever see the literal text handed to them. If a
    resume is split across multiple files via \\input, those checks need the
    fully assembled source rather than just the top-level file's \\input lines.
    Each \\input/\\include reference to a file that exists alongside the
    including file is replaced with that target's resolved contents (default
    .tex extension). References that don't resolve to a project file — e.g.
    `\\input{glyphtounicode}`, a TeX system macro pulled from texmf, not a
    project file — are left as literal text instead of being dropped, since
    checks like parse.unicode_mapping string-search for the command name
    itself. Lines without a reference are returned unchanged, so a single
    self-contained .tex file round-trips byte-for-byte. Include cycles return
    empty for the repeated branch rather than raising, so one bad reference
    doesn't take down the whole check.
    """
    tex_path = tex_path.resolve()
    seen = set(_seen) if _seen else set()
    if tex_path in seen:
        return ""
    seen.add(tex_path)

    try:
        raw = tex_path.read_text(encoding="utf-8")
    except OSError:
        return ""

    def _replace(match: "re.Match[str]") -> str:
        target_name = match.group(1)
        if not target_name.endswith(".tex"):
            target_name += ".tex"
        target = (tex_path.parent / target_name).resolve()
        if not target.is_file():
            return match.group(0)
        return resolve_includes(target, seen)

    out_lines = []
    for original, stripped in zip(raw.splitlines(), strip_comments(raw).splitlines()):
        if _INCLUDE_RE.search(stripped):
            out_lines.append(_INCLUDE_RE.sub(_replace, stripped))
        else:
            out_lines.append(original)
    return "\n".join(out_lines)


def compile_latex(tex_path: Path, compiler: Optional[str] = None) -> Path:
    """Compile a LaTeX file and return the expected PDF path."""
    tex_path = tex_path.resolve()
    command = _build_command(tex_path, compiler)
    if command is None:
        raise BuildError("No LaTeX compiler found. Install latexmk or pdflatex, or pass --pdf/--no-compile.")

    result = subprocess.run(
        command,
        cwd=str(tex_path.parent),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if result.returncode != 0:
        raise BuildError(result.stdout.strip() or "LaTeX build failed.")

    pdf_path = tex_path.with_suffix(".pdf")
    if not pdf_path.exists():
        raise BuildError(f"LaTeX build succeeded but did not create {pdf_path}.")
    return pdf_path


def _build_command(tex_path: Path, compiler: Optional[str]) -> Optional[Sequence[str]]:
    if compiler:
        if shutil.which(compiler) is None:
            raise BuildError(f"Requested compiler not found: {compiler}")
        if Path(compiler).name == "latexmk":
            return [compiler, "-pdf", "-interaction=nonstopmode", tex_path.name]
        return [compiler, "-interaction=nonstopmode", tex_path.name]

    if shutil.which("latexmk"):
        return ["latexmk", "-pdf", "-interaction=nonstopmode", tex_path.name]
    if shutil.which("pdflatex"):
        return ["pdflatex", "-interaction=nonstopmode", tex_path.name]
    return None


def _latex_to_text(value: str) -> str:
    return normalize_latex_text(value)
