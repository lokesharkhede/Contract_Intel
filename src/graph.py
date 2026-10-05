from typing import TypedDict, Optional
from langgraph.graph import StateGraph, END

from src import llm_gemini, pdf_parser, nlp_utils, playbook_engine, memory


class ContractState(TypedDict, total=False):
    pdf_path: str
    contract_name: str
    paragraphs: list[str]
    playbook: dict
    matches: list[dict]
    clause_results: list[dict]
    summary: str
    contract_id: int
    route: str


def partition_pdf_node(state: ContractState) -> dict:
    paragraphs = pdf_parser.parse_contract(state["pdf_path"])
    return {"paragraphs": paragraphs}


def semantic_clause_matching_node(state: ContractState) -> dict:
    matches = nlp_utils.match_clauses_to_paragraphs(state["paragraphs"], state["playbook"])
    return {"matches": matches}


def evaluate_against_playbook_node(state: ContractState) -> dict:
    clause_results = playbook_engine.reconcile_contract(state["matches"], state["playbook"])
    return {"clause_results": clause_results}


def route_on_flags(state: ContractState) -> str:
    has_flags = any(c["status"] == "flagged" for c in state["clause_results"])
    return "risk_report" if has_flags else "clean_summary"


def clean_summary_node(state: ContractState) -> dict:
    summary = f"No playbook risks identified in {state['contract_name']}. All checked clauses pass."
    return {"summary": summary, "route": "clean"}


def risk_report_node(state: ContractState) -> dict:
    summary = llm_gemini.summarize_flags(state["contract_name"], state["clause_results"])
    return {"summary": summary, "route": "flagged"}


def persist_node(state: ContractState) -> dict:
    contract_id = memory.save_review(state["contract_name"], state["clause_results"], state["summary"])
    return {"contract_id": contract_id}

def build_graph():
    graph = StateGraph(ContractState)

    graph.add_node("partition_pdf", partition_pdf_node)
    graph.add_node("semantic_clause_matching", semantic_clause_matching_node)
    graph.add_node("evaluate_against_playbook", evaluate_against_playbook_node)
    graph.add_node("clean_summary", clean_summary_node)
    graph.add_node("risk_report", risk_report_node)
    graph.add_node("persist", persist_node)

    graph.set_entry_point("partition_pdf")
    graph.add_edge("partition_pdf", "semantic_clause_matching")
    graph.add_edge("semantic_clause_matching", "evaluate_against_playbook")

    graph.add_conditional_edges(
        "evaluate_against_playbook",
        route_on_flags,
        {"clean_summary": "clean_summary", "risk_report": "risk_report"},
    )

    graph.add_edge("clean_summary", "persist")
    graph.add_edge("risk_report", "persist")
    graph.add_edge("persist", END)

    return graph.compile()


def run_pipeline(pdf_path: str, contract_name: str, playbook: dict) -> ContractState:
    app = build_graph()
    initial_state: ContractState = {
        "pdf_path": pdf_path,
        "contract_name": contract_name,
        "playbook": playbook,
    }
    return app.invoke(initial_state)
