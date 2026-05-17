"""Streamlit UI for ATS Resume Checker.

Run locally with:
    streamlit run app.py
"""

from __future__ import annotations

import json

from ats_resume_checker.checks import DEFAULT_KEYWORDS, AtsReport
from ats_resume_checker.pdf_tools import PdfToolError
from ats_resume_checker.report import render_markdown
from ats_resume_checker.ui import analyze_uploaded_resume, parse_keywords, summarize_status_counts, top_fixes


def main() -> None:
    import streamlit as st

    st.set_page_config(page_title="ATS Resume Checker", page_icon=":page_facing_up:", layout="wide")
    st.title("ATS Resume Checker")
    st.caption("Upload a LaTeX source file and its generated PDF to inspect ATS-friendly text extraction.")

    with st.sidebar:
        st.header("Inputs")
        tex_file = st.file_uploader("LaTeX source (.tex)", type=["tex"])
        pdf_file = st.file_uploader("Generated resume PDF (.pdf)", type=["pdf"])
        max_pages = st.number_input("Maximum page count", min_value=1, max_value=10, value=2, step=1)
        raw_keywords = st.text_area(
            "Target keywords",
            value="\n".join(DEFAULT_KEYWORDS),
            height=220,
            help="One keyword per line. These are checked against the extracted PDF text.",
        )
        run_button = st.button("Run ATS Check", type="primary", use_container_width=True)

    if not tex_file or not pdf_file:
        st.info("Upload both a `.tex` source file and the matching `.pdf` resume to begin.")
        return

    if not run_button:
        st.info("Files are ready. Click **Run ATS Check** to analyze the resume.")
        return

    try:
        analysis = analyze_uploaded_resume(
            tex_file.getvalue(),
            pdf_file.getvalue(),
            max_pages=int(max_pages),
            keywords=parse_keywords(raw_keywords),
        )
    except UnicodeDecodeError:
        st.error("Could not read the uploaded `.tex` file as UTF-8 text.")
        return
    except PdfToolError as exc:
        st.error(str(exc))
        st.info("Install Poppler so `pdftotext` and `pdfinfo` are available, then rerun the app.")
        return

    _render_report(st, analysis.report, analysis.extracted_text)


def _render_report(st, report: AtsReport, extracted_text: str) -> None:
    counts = summarize_status_counts(report)
    col_score, col_pass, col_warn, col_fail = st.columns(4)
    col_score.metric("ATS Resume Check", f"{report.score}/100")
    col_pass.metric("Pass", counts["pass"])
    col_warn.metric("Warn", counts["warn"])
    col_fail.metric("Fail", counts["fail"])

    fixes = top_fixes(report)
    if fixes:
        st.subheader("Top Fixes")
        for fix in fixes:
            st.warning(fix)

    checks_tab, keywords_tab, metadata_tab, extracted_tab, downloads_tab = st.tabs(
        ["Checks", "Keywords", "PDF Metadata", "Extracted Text", "Downloads"]
    )

    with checks_tab:
        st.dataframe(
            [
                {
                    "status": check.status.upper(),
                    "check": check.title,
                    "finding": check.message,
                    "suggested_fix": check.fix,
                }
                for check in report.checks
            ],
            use_container_width=True,
            hide_index=True,
        )

    with keywords_tab:
        found_col, missing_col = st.columns(2)
        with found_col:
            st.subheader("Found")
            st.write(report.keywords["found"] or ["None"])
        with missing_col:
            st.subheader("Missing")
            st.write(report.keywords["missing"] or ["None"])

    with metadata_tab:
        st.dataframe(
            [{"field": key, "value": value} for key, value in sorted(report.pdf_info.items())],
            use_container_width=True,
            hide_index=True,
        )
        with st.expander("Detected sections"):
            st.write("Source sections:", report.source_sections or ["None detected"])
            st.write("Extracted sections:", report.extracted_sections or ["None detected"])

    with extracted_tab:
        st.code(report.extracted_text_preview or extracted_text, language="text")

    with downloads_tab:
        markdown_report = render_markdown(report)
        json_report = json.dumps(report.to_dict(), indent=2)
        st.download_button("Download Markdown report", markdown_report, file_name="ats-report.md", mime="text/markdown")
        st.download_button("Download JSON report", json_report, file_name="ats-report.json", mime="application/json")
        st.download_button("Download extracted text", extracted_text, file_name="extracted-text.txt", mime="text/plain")


if __name__ == "__main__":
    main()
