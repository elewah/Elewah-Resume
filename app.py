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

    # Persistent state across Streamlit reruns
    st.session_state.setdefault("ats_analysis", None)
    st.session_state.setdefault("agent_result", None)
    st.session_state.setdefault("uploaded_tex_bytes", None)
    st.session_state.setdefault("uploaded_pdf_bytes", None)
    st.session_state.setdefault("uploaded_keywords", None)

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

    if run_button:
        # Clear stale agent result whenever the user re-runs the ATS check
        st.session_state.agent_result = None
        try:
            analysis = analyze_uploaded_resume(
                tex_file.getvalue(),
                pdf_file.getvalue(),
                max_pages=int(max_pages),
                keywords=parse_keywords(raw_keywords),
            )
            st.session_state.ats_analysis = analysis
            st.session_state.uploaded_tex_bytes = tex_file.getvalue()
            st.session_state.uploaded_pdf_bytes = pdf_file.getvalue()
            st.session_state.uploaded_keywords = parse_keywords(raw_keywords)
        except UnicodeDecodeError:
            st.error("Could not read the uploaded `.tex` file as UTF-8 text.")
            return
        except PdfToolError as exc:
            st.error(str(exc))
            st.info("Install Poppler so `pdftotext` and `pdfinfo` are available, then rerun the app.")
            return

    if st.session_state.ats_analysis is None:
        st.info("Files are ready. Click **Run ATS Check** to analyze the resume.")
        return

    analysis = st.session_state.ats_analysis
    _render_report(st, analysis.report, analysis.extracted_text)

    st.divider()
    _render_ai_section(st, int(max_pages))


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
            [{"field": key, "value": str(value)} for key, value in sorted(report.pdf_info.items())],
            use_container_width=True,
            hide_index=True,
        )
        with st.expander("Detected sections"):
            st.write("Source sections:", report.source_sections or ["None detected"])
            st.write("Extracted sections:", report.extracted_sections or ["None detected"])

    with extracted_tab:
        st.caption("Full text extracted from the uploaded PDF. This is not truncated.")
        st.code(report.extracted_text or extracted_text.strip(), language="text")

    with downloads_tab:
        markdown_report = render_markdown(report)
        json_report = json.dumps(report.to_dict(), indent=2)
        st.download_button("Download Markdown report", markdown_report, file_name="ats-report.md", mime="text/markdown")
        st.download_button("Download JSON report", json_report, file_name="ats-report.json", mime="application/json")
        st.download_button("Download extracted text", extracted_text, file_name="extracted-text.txt", mime="text/plain")


_PROVIDER_ANTHROPIC = "Anthropic (Claude)"
_PROVIDER_BEDROCK = "AWS Bedrock"
_PROVIDER_LM_STUDIO = "Local (LM Studio)"


def _render_ai_section(st, max_pages: int) -> None:
    """AI Resume Improvement section — shown below the ATS report."""
    st.header("AI Resume Improvement")

    provider = st.radio(
        "Provider",
        options=[_PROVIDER_ANTHROPIC, _PROVIDER_BEDROCK, _PROVIDER_LM_STUDIO],
        horizontal=True,
    )

    # Shared iteration slider (shown for all providers)
    col_model, col_iters = st.columns(2)

    # Provider-specific fields
    api_key = None
    base_url = None
    aws_access_key_id = None
    aws_secret_access_key = None
    aws_profile = None
    aws_region = "us-east-1"

    if provider == _PROVIDER_ANTHROPIC:
        st.caption(
            "Uses the Claude Code agent via your Anthropic subscription or API key. "
            "Requires the `claude` CLI to be installed and authenticated."
        )
        with col_model:
            model = st.selectbox(
                "Model",
                options=["claude-sonnet-4-6", "claude-opus-4-7", "claude-haiku-4-5"],
                index=0,
            )
        with col_iters:
            max_iterations = st.slider("Max iterations", min_value=1, max_value=5, value=3)

        with st.expander("API key (optional — use if your subscription is out of credits)"):
            api_key = st.text_input(
                "Anthropic API key",
                type="password",
                placeholder="sk-ant-...",
                help=(
                    "Leave empty to use your Claude Code subscription. "
                    "Enter an API key from console.anthropic.com to use API credits instead."
                ),
            ) or None

    elif provider == _PROVIDER_BEDROCK:
        st.caption(
            "Runs Claude models via Amazon Bedrock using your AWS credentials. "
            "Ensure the model is enabled in your AWS account's Bedrock model access settings."
        )
        with col_model:
            model = st.selectbox(
                "Model",
                options=[
                    "us.anthropic.claude-sonnet-4-6",
                    "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
                    "us.anthropic.claude-opus-4-1-20250805-v1:0",
                ],
                index=0,
                help=(
                    "Cross-region inference profile IDs. "
                    "Make sure the model is enabled in your AWS account's Bedrock Model Access. "
                    "IDs may vary — check the Bedrock console if you see an 'invalid model' error."
                ),
            )
        with col_iters:
            max_iterations = st.slider("Max iterations", min_value=1, max_value=5, value=3)

        use_profile = st.toggle("Use AWS profile (~/.aws/credentials)", value=True)

        if use_profile:
            col_prof, col_reg = st.columns(2)
            with col_prof:
                aws_profile = st.text_input(
                    "AWS Profile",
                    value="default",
                    help="Profile name from ~/.aws/credentials (e.g. default, work, bedrock).",
                )
            with col_reg:
                aws_region = st.selectbox(
                    "AWS Region",
                    options=["us-east-1", "us-west-2", "eu-west-1", "ap-northeast-1", "ap-southeast-1"],
                    index=0,
                    help="Must be a region where Bedrock Claude models are available.",
                )
        else:
            col_key, col_secret = st.columns(2)
            with col_key:
                aws_access_key_id = st.text_input(
                    "AWS Access Key ID",
                    placeholder="AKIA...",
                    help="From AWS Console → IAM → Your user → Security credentials.",
                ) or None
            with col_secret:
                aws_secret_access_key = st.text_input(
                    "AWS Secret Access Key",
                    type="password",
                    placeholder="wJalrXUt...",
                ) or None
            aws_profile = None
            aws_region = st.selectbox(
                "AWS Region",
                options=["us-east-1", "us-west-2", "eu-west-1", "ap-northeast-1", "ap-southeast-1"],
                index=0,
                help="Must be a region where Bedrock Claude models are available.",
            )
            if not aws_access_key_id or not aws_secret_access_key:
                st.warning("Enter your AWS Access Key ID and Secret Access Key to use Bedrock.")

    else:  # LM Studio
        st.caption(
            "Sends requests to a local LM Studio model via its Anthropic-compatible endpoint. "
            "Make sure LM Studio is running with the server started."
        )
        with col_model:
            model = st.text_input(
                "Model ID",
                value="qwen/qwen3.5-9b",
                help="The model ID as shown in LM Studio (e.g. qwen/qwen3.5-9b).",
            )
        with col_iters:
            max_iterations = st.slider("Max iterations", min_value=1, max_value=5, value=2)

        base_url = st.text_input(
            "LM Studio base URL",
            value="http://127.0.0.1:1234",
            help=(
                "In LM Studio: Local Server → REST API v1 → Anthropic-compatible → Start Server. "
                "Use 127.0.0.1 (not localhost) to avoid IPv6 issues on macOS."
            ),
        )
        st.info(
            "Load your model in LM Studio with **context window ≥ 16384 tokens** before running. "
            "(Model settings → n_ctx)"
        )

    run_agent_button = st.button("Run AI Agent", type="primary")

    if run_agent_button:
        import queue as _queue
        import threading as _threading

        st.session_state.agent_result = None
        msg_q: _queue.Queue[str | None] = _queue.Queue()
        result_holder: dict = {}
        error_holder: dict = {}

        # Read session state on the main Streamlit thread — threads cannot access it.
        _tex_bytes = st.session_state.get("uploaded_tex_bytes")
        _pdf_bytes = st.session_state.get("uploaded_pdf_bytes")
        _keywords = st.session_state.get("uploaded_keywords") or []

        if not _tex_bytes or not _pdf_bytes:
            st.error("Run the ATS check first to upload your files before using the AI agent.")
            return

        def _run_in_thread() -> None:
            from ats_resume_checker.agent import run_improvement_agent
            try:
                result_holder["v"] = run_improvement_agent(
                    tex_bytes=_tex_bytes,
                    pdf_bytes=_pdf_bytes,
                    max_iterations=max_iterations,
                    model=model,
                    max_pages=max_pages,
                    keywords=_keywords,
                    api_key=api_key,
                    base_url=base_url or None,
                    aws_access_key_id=aws_access_key_id,
                    aws_secret_access_key=aws_secret_access_key,
                    aws_profile=aws_profile,
                    aws_region=aws_region,
                    message_callback=lambda m: msg_q.put(m),
                )
            except Exception as exc:
                error_holder["v"] = exc
            finally:
                msg_q.put(None)  # sentinel — agent finished

        t = _threading.Thread(target=_run_in_thread, daemon=True)
        t.start()

        with st.status("AI agent is working…", expanded=True) as status:
            while True:
                try:
                    msg = msg_q.get(timeout=0.3)
                except _queue.Empty:
                    continue
                if msg is None:
                    break
                st.markdown(msg)
            status.update(label="Agent finished", state="complete", expanded=False)

        t.join()

        if "v" in error_holder:
            exc = error_holder["v"]
            exc_str = str(exc)
            if isinstance(exc, RuntimeError):
                st.error(exc_str)
            elif "error result: success" in exc_str or "maximum number of turns" in exc_str:
                st.warning(
                    "The agent hit a turn limit or non-zero exit. "
                    "Results below reflect partial improvements — increase Max iterations for more."
                )
                if "v" in result_holder:
                    st.session_state.agent_result = result_holder["v"]
            else:
                st.error(f"Agent error ({type(exc).__name__}): {exc_str}")
        elif "v" in result_holder:
            st.session_state.agent_result = result_holder["v"]

    if st.session_state.agent_result is not None:
        _render_agent_result(st, st.session_state.agent_result)


def _render_agent_result(st, result) -> None:
    """Display iteration history, PDF preview, and download for the improved resume."""
    delta = result.final_score - result.initial_score
    col_initial, col_final, col_delta = st.columns(3)
    col_initial.metric("Initial Score", f"{result.initial_score}/100")
    col_final.metric("Final Score", f"{result.final_score}/100")
    col_delta.metric("Improvement", f"{delta:+d} pts", delta_color="normal")

    if result.progress_messages:
        st.subheader("Agent Reasoning")
        with st.expander("View agent's step-by-step reasoning", expanded=False):
            for msg in result.progress_messages:
                st.markdown(msg)
    else:
        st.info("The agent made no further improvements (score was already optimal).")

    if result.png_pages:
        st.subheader("Visual PDF Preview")
        st.caption("Rendered pages of the improved resume — check for readability and layout issues.")
        for i, png_bytes in enumerate(result.png_pages):
            st.image(png_bytes, caption=f"Page {i + 1}", use_container_width=True)

    st.subheader("Download Improved Resume")
    st.download_button(
        "Download improved .tex",
        data=result.improved_tex.encode("utf-8"),
        file_name="resume_improved.tex",
        mime="text/plain",
    )


if __name__ == "__main__":
    main()
