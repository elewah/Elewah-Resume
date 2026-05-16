"""Report rendering for console, Markdown, and JSON."""

from __future__ import annotations

import json
from pathlib import Path

from .checks import AtsReport, CheckResult


def render_console(report: AtsReport) -> str:
    lines = [
        f"ATS Resume Check: {report.score}/100",
        "",
        "Checks:",
    ]
    for check in report.checks:
        lines.append(f"- [{check.status.upper()}] {check.title}: {check.message}")
    top_fixes = [check for check in report.checks if check.status in {"fail", "warn"} and check.fix]
    if top_fixes:
        lines.extend(["", "Top fixes:"])
        seen = set()
        for check in top_fixes:
            if check.fix in seen:
                continue
            seen.add(check.fix)
            lines.append(f"- {check.fix}")
            if len(seen) == 5:
                break
    return "\n".join(lines)


def render_markdown(report: AtsReport) -> str:
    lines = [
        "# ATS Resume Check Report",
        "",
        f"**Score:** {report.score}/100",
        "",
        "## Checks",
        "",
        "| Status | Check | Finding | Suggested fix |",
        "| --- | --- | --- | --- |",
    ]
    for check in report.checks:
        lines.append(
            f"| {check.status.upper()} | {_escape(check.title)} | {_escape(check.message)} | {_escape(check.fix)} |"
        )
    lines.extend(
        [
            "",
            "## Sections",
            "",
            f"**Source sections:** {', '.join(report.source_sections) if report.source_sections else 'None detected'}",
            "",
            f"**Extracted sections:** {', '.join(report.extracted_sections) if report.extracted_sections else 'None detected'}",
            "",
            "## Keyword Coverage",
            "",
            f"**Found:** {', '.join(report.keywords['found']) if report.keywords['found'] else 'None'}",
            "",
            f"**Missing:** {', '.join(report.keywords['missing']) if report.keywords['missing'] else 'None'}",
            "",
            "## PDF Info",
            "",
        ]
    )
    for key, value in sorted(report.pdf_info.items()):
        lines.append(f"- **{key}:** {value}")
    lines.extend(
        [
            "",
            "## Extracted Text Preview",
            "",
            "```text",
            report.extracted_text_preview,
            "```",
        ]
    )
    return "\n".join(lines)


def write_json(report: AtsReport, path: Path) -> None:
    path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")


def write_markdown(report: AtsReport, path: Path) -> None:
    path.write_text(render_markdown(report), encoding="utf-8")


def has_failures(report: AtsReport) -> bool:
    return any(_is_critical_failure(check) for check in report.checks)


def _is_critical_failure(check: CheckResult) -> bool:
    return check.status == "fail"


def _escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
