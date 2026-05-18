"""ATS heuristic checks and scoring."""

from __future__ import annotations

import re
import string
from dataclasses import asdict, dataclass
from typing import Any, Iterable

from .latex import extract_sections, normalize_latex_text


DEFAULT_KEYWORDS = [
    "Python",
    "LLMs",
    "RAG",
    "LangChain",
    "LangGraph",
    "FastAPI",
    "PostgreSQL",
    "Docker",
    "AWS",
    "MLOps",
    "computer vision",
    "document intelligence",
    "semantic search",
    "model deployment",
]

SECTION_GROUPS = {
    "summary": ("summary", "professional summary", "profile"),
    "skills": ("skills", "technical skills", "technologies"),
    "experience": ("experience", "professional experience", "work experience", "employment"),
    "education": ("education",),
    "projects": ("projects", "selected projects"),
}

RISKY_LAYOUT_PACKAGES = {
    "fontawesome": "Icon fonts often extract as unreadable glyphs.",
    "fontawesome5": "Icon fonts often extract as unreadable glyphs.",
    "paracol": "Multi-column layouts can reorder text in some parsers.",
    "multicol": "Multi-column layouts can reorder text in some parsers.",
    "tabularx": "Tables can make reading order harder for ATS parsers.",
    "tikz": "Graphic-heavy layouts may hide meaningful text from extraction.",
}


@dataclass
class CheckResult:
    id: str
    title: str
    status: str
    message: str
    fix: str = ""


@dataclass
class AtsReport:
    score: int
    checks: list[CheckResult]
    source_sections: list[str]
    extracted_sections: list[str]
    keywords: dict[str, list[str]]
    pdf_info: dict[str, Any]
    extracted_text: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["checks"] = [asdict(check) for check in self.checks]
        return data


def run_checks(
    tex_source: str,
    extracted_text: str,
    pdf_info: dict[str, Any],
    max_pages: int = 2,
    keywords: Iterable[str] = DEFAULT_KEYWORDS,
) -> AtsReport:
    """Run all ATS checks.

    Pass ``tex_source=""`` (or omit) to run in **PDF-only mode**: checks that
    require LaTeX source (``parse.unicode_mapping``, ``layout.package.*``) are
    silently skipped and the score is computed from the remaining checks only.
    """
    has_source = bool(tex_source and tex_source.strip())
    source_text = normalize_latex_text(tex_source) if has_source else ""
    source_sections = extract_sections(tex_source) if has_source else []
    extracted_sections = _detect_sections(extracted_text)
    checks: list[CheckResult] = []

    checks.extend(_contact_checks(extracted_text))
    checks.extend(_section_checks(extracted_text, source_sections, has_source=has_source))
    checks.extend(_parseability_checks(tex_source, extracted_text, pdf_info, max_pages, has_source=has_source))
    checks.extend(_layout_checks(tex_source, extracted_text, has_source=has_source))

    keyword_result = _keyword_coverage(source_text, extracted_text, keywords)
    checks.append(_keyword_check(keyword_result))

    score = _score(checks)
    return AtsReport(
        score=score,
        checks=checks,
        source_sections=source_sections,
        extracted_sections=extracted_sections,
        keywords=keyword_result,
        pdf_info=pdf_info,
        extracted_text=_full_extracted_text(extracted_text),
    )


def _contact_checks(text: str) -> list[CheckResult]:
    first_nonempty = next((line.strip() for line in text.splitlines() if line.strip()), "")
    checks = [
        CheckResult(
            "contact.name",
            "Name extraction",
            "pass" if _looks_like_name(first_nonempty) else "warn",
            f"First extracted line: {first_nonempty!r}" if first_nonempty else "No non-empty first line found.",
            "Put the candidate name as selectable text at the top of the resume.",
        ),
        CheckResult(
            "contact.email",
            "Email extraction",
            "pass" if re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text) else "fail",
            "Email address is extractable." if "@" in text else "No extractable email address found.",
            "Use a plain text email address instead of icon-only contact links.",
        ),
        CheckResult(
            "contact.phone",
            "Phone extraction",
            "pass" if re.search(r"(?:\+?\d[\s().-]*){10,}", text) else "warn",
            "Phone number appears extractable."
            if re.search(r"(?:\+?\d[\s().-]*){10,}", text)
            else "No phone number found in extracted text.",
            "Use a plain text phone number with country code when possible.",
        ),
        CheckResult(
            "contact.links",
            "Professional links",
            "pass" if re.search(r"(linkedin|github|portfolio|https?://|www\.)", text, re.I) else "warn",
            "Professional links appear extractable."
            if re.search(r"(linkedin|github|portfolio|https?://|www\.)", text, re.I)
            else "No LinkedIn, GitHub, or portfolio link found in extracted text.",
            "Use plain link text such as linkedin.com/in/name and github.com/name.",
        ),
    ]
    return checks


def _section_checks(text: str, source_sections: list[str], *, has_source: bool = True) -> list[CheckResult]:
    normalized = _lower_words(text)
    source_normalized = {_lower_words(section) for section in source_sections}
    checks = []
    for group, aliases in SECTION_GROUPS.items():
        found_in_pdf = any(alias in normalized for alias in aliases)
        found_in_source = any(alias in source_normalized for alias in aliases)
        status = "pass" if found_in_pdf else "warn"
        message = f"{group.title()} section found in extracted text." if found_in_pdf else f"{group.title()} section not found in extracted text."
        if has_source and found_in_source and not found_in_pdf:
            message += " It exists in source, so the PDF layout may be hurting extraction."
        checks.append(
            CheckResult(
                f"section.{group}",
                f"{group.title()} section",
                status,
                message,
                "Use conventional section headings as selectable text.",
            )
        )
    return checks


def _parseability_checks(
    tex_source: str, text: str, pdf_info: dict[str, Any], max_pages: int, *, has_source: bool = True
) -> list[CheckResult]:
    pages = pdf_info.get("pages")
    encrypted = str(pdf_info.get("encrypted", "")).lower()
    javascript = str(pdf_info.get("javascript", "")).lower()
    checks = [
        CheckResult(
            "parse.text_volume",
            "PDF text extraction",
            "pass" if len(text.strip()) >= 500 else "fail",
            f"Extracted {len(text.strip())} characters.",
            "Ensure the PDF contains selectable text, not only images.",
        ),
        CheckResult(
            "parse.glyphs",
            "Garbage glyph scan",
            "pass" if _garbage_ratio(text) < 0.01 else "warn",
            f"Suspicious character ratio: {_garbage_ratio(text):.2%}.",
            "Remove icon fonts or replace icons with plain text labels.",
        ),
        CheckResult(
            "parse.encrypted",
            "PDF encryption",
            "pass" if encrypted in ("", "no") else "fail",
            f"Encrypted: {pdf_info.get('encrypted', 'unknown')}.",
            "Do not submit encrypted or password-protected PDFs.",
        ),
        CheckResult(
            "parse.javascript",
            "PDF JavaScript",
            "pass" if javascript in ("", "no") else "warn",
            f"JavaScript: {pdf_info.get('javascript', 'unknown')}.",
            "Avoid JavaScript or interactive PDF features in resumes.",
        ),
        CheckResult(
            "parse.page_count",
            "Page count",
            "pass" if isinstance(pages, int) and pages <= max_pages else "warn",
            f"Pages: {pages if pages is not None else 'unknown'}; target max: {max_pages}.",
            f"Keep the resume at {max_pages} page(s) or less for this check.",
        ),
    ]
    # unicode_mapping requires LaTeX source — skip in PDF-only mode.
    # Strip comments first so a commented-out \input{glyphtounicode} does not
    # produce a false-positive PASS.
    if has_source:
        from .latex import strip_comments as _strip_comments
        stripped = _strip_comments(tex_source)
        has_unicode_hints = "glyphtounicode" in stripped and "pdfgentounicode" in stripped
        checks.insert(
            2,
            CheckResult(
                "parse.unicode_mapping",
                "Unicode mapping hints",
                "pass" if has_unicode_hints else "warn",
                "LaTeX source includes Unicode extraction hints." if has_unicode_hints else "Unicode extraction hints not detected.",
                "For pdfTeX, include glyphtounicode and set \\pdfgentounicode=1.",
            ),
        )
    return checks


def _layout_checks(tex_source: str, extracted_text: str, *, has_source: bool = True) -> list[CheckResult]:
    checks = []
    # Package checks require LaTeX source — skip entirely in PDF-only mode
    if has_source:
        for package, reason in RISKY_LAYOUT_PACKAGES.items():
            if re.search(rf"\\usepackage(?:\[[^\]]*\])?\{{[^}}]*\b{re.escape(package)}\b[^}}]*\}}", tex_source, re.I):
                checks.append(
                    CheckResult(
                        f"layout.package.{package}",
                        f"Layout package: {package}",
                        "warn",
                        reason,
                        "Verify pdftotext reading order and replace visual-only elements with plain text where possible.",
                    )
                )
    if re.search(r"^\w+\s*\n\w+\s*$", extracted_text, re.M):
        checks.append(
            CheckResult(
                "layout.heading_split",
                "Possible split heading",
                "warn",
                "Some adjacent one-word lines may indicate section headings split during extraction.",
                "If needed, simplify heading styling or verify the split does not hide section meaning.",
            )
        )
    else:
        checks.append(
            CheckResult(
                "layout.heading_split",
                "Possible split heading",
                "pass",
                "No obvious split heading pattern detected.",
            )
        )
    return checks


def _keyword_coverage(source_text: str, extracted_text: str, keywords: Iterable[str]) -> dict[str, list[str]]:
    source_lower = source_text.lower()
    extracted_lower = extracted_text.lower()
    wanted = list(keywords)
    found = [keyword for keyword in wanted if keyword.lower() in extracted_lower]
    missing_from_pdf = [keyword for keyword in wanted if keyword.lower() not in extracted_lower]
    present_in_source_only = [
        keyword
        for keyword in wanted
        if keyword.lower() in source_lower and keyword.lower() not in extracted_lower
    ]
    return {
        "found": found,
        "missing": missing_from_pdf,
        "source_only": present_in_source_only,
    }


def _keyword_check(keyword_result: dict[str, list[str]]) -> CheckResult:
    found = keyword_result["found"]
    missing = keyword_result["missing"]
    if len(found) >= 10:
        status = "pass"
    elif len(found) >= 6:
        status = "warn"
    else:
        status = "fail"
    return CheckResult(
        "keywords.coverage",
        "Keyword coverage",
        status,
        f"Found {len(found)} target keywords. Missing: {', '.join(missing) if missing else 'none'}.",
        "Tailor the keyword list to the target job and make sure important terms extract from the PDF.",
    )


def _detect_sections(text: str) -> list[str]:
    found = []
    normalized = _lower_words(text)
    for aliases in SECTION_GROUPS.values():
        for alias in aliases:
            if alias in normalized:
                found.append(alias.title())
                break
    return found


def _looks_like_name(value: str) -> bool:
    words = value.split()
    return 2 <= len(words) <= 5 and all(word[:1].isupper() for word in words if word[:1].isalpha())


def _garbage_ratio(text: str) -> float:
    if not text:
        return 1.0
    allowed = set(string.printable) | {"•", "–", "—", "’", "“", "”", "é", "É"}
    suspicious = sum(1 for char in text if char not in allowed and not char.isspace())
    return suspicious / max(len(text), 1)


def _score(checks: list[CheckResult]) -> int:
    score = 100
    for check in checks:
        if check.status == "warn":
            score -= 5
        elif check.status == "fail":
            score -= 15
    return max(score, 0)


def _full_extracted_text(text: str) -> str:
    return text.strip()


def _lower_words(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower())
