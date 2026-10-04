"""
app.py — Streamlit frontend for the Contract Intelligence & Redline Assistant.

Two tabs:
  1. Review a Contract   -> upload a PDF, run the LangGraph pipeline, see flags
  2. Review History      -> browse previously reviewed contracts (from memory.py),
                             and chat with any one of them
"""

import os
import tempfile
import streamlit as st

from src import memory
from src.playbook_engine import load_playbook
from src.graph import run_pipeline
from src.llm_gemini import answer_question_about_contract

st.set_page_config(page_title="Contract Intelligence Assistant", layout="wide")
memory.init_db()

RISK_COLOR = {"high": "🔴", "medium": "🟠", "low": "🟡"}

st.title("📄 Contract Intelligence & Redline Assistant")
tab_review, tab_history = st.tabs(["Review a Contract", "Review History"])

# ---------------------------------------------------------------------------
# TAB 1 — Review a new contract
# ---------------------------------------------------------------------------
with tab_review:
    st.subheader("Upload a contract PDF")
    uploaded_file = st.file_uploader("Choose a PDF", type=["pdf"])

    if uploaded_file is not None:
        if st.button("Run Review", type="primary"):
            with st.spinner("Parsing PDF and matching clauses..."):
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                    tmp.write(uploaded_file.read())
                    tmp_path = tmp.name

                playbook = load_playbook()
                result = run_pipeline(tmp_path, uploaded_file.name, playbook)
                os.unlink(tmp_path)

            st.session_state["last_result"] = result

    if "last_result" in st.session_state:
        result = st.session_state["last_result"]
        clause_results = result["clause_results"]
        flagged = [c for c in clause_results if c["status"] == "flagged"]

        col1, col2, col3 = st.columns(3)
        col1.metric("Clauses Checked", len(clause_results))
        col2.metric("Flags Raised", len(flagged))
        col3.metric("Overall Status", "🔴 Needs Review" if flagged else "🟢 Clean")

        st.markdown("### Risk Summary")
        st.info(result["summary"])

        st.markdown("### Clause-by-Clause Results")
        for c in clause_results:
            icon = RISK_COLOR.get(c.get("risk"), "✅") if c["status"] == "flagged" else "✅"
            with st.expander(f"{icon} {c['label']} — {c['status'].replace('_', ' ').title()}"):
                if c["status"] == "flagged":
                    st.write(f"**Issue:** {c['issue']}")
                    st.write(f"**Risk level:** {c['risk']}")
                elif c["status"] == "not_found":
                    st.write(c["issue"])
                else:
                    st.write(f"**Extracted value:** {c.get('extracted_value')}")
                if c.get("matched_text"):
                    st.caption(f"Matched contract text: \u201c{c['matched_text']}\u201d")

# ---------------------------------------------------------------------------
# TAB 2 — Review history + chat with a past contract
# ---------------------------------------------------------------------------
with tab_history:
    st.subheader("Previously Reviewed Contracts")
    contracts = memory.list_reviewed_contracts()

    if not contracts:
        st.write("No contracts reviewed yet — run a review in the first tab.")
    else:
        options = {
            f"#{c['id']} — {c['contract_name']} ({c['overall_status']}, {c['reviewed_at'][:10]})": c["id"]
            for c in contracts
        }
        selected_label = st.selectbox("Select a contract", list(options.keys()))
        selected_id = options[selected_label]
        contract = memory.get_contract(selected_id)
        clause_rows = memory.get_clause_results(selected_id)

        st.markdown(f"**Summary:** {contract['summary']}")
        st.markdown(
            f"High: {contract['num_flags_high']} · "
            f"Medium: {contract['num_flags_medium']} · "
            f"Low: {contract['num_flags_low']}"
        )

        st.markdown("### Ask a question about this contract")
        question = st.text_input("e.g. What is the termination notice period?")
        if st.button("Ask") and question:
            with st.spinner("Thinking..."):
                answer = answer_question_about_contract(
                    contract["contract_name"], clause_rows, question
                )
            st.write(answer)
