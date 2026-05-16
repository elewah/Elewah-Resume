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
