"""
llm_client.py — thin wrapper around Gemini.

The LLM is used narrowly, for two jobs only:
  1. Writing a plain-English summary of a clause (optional, for the UI).
  2. Turning a list of rule-engine flags into a readable risk narrative.

The LLM is NEVER asked to decide whether something is risky — that decision
already happened in playbook_engine.py using deterministic rules. This keeps
the one part of the pipeline that must be reliable (the risk decision) out of
the hands of a model that can phrase things confidently but incorrectly.
"""

import os
import json
from google import genai
from config import GEMINI_MODEL, GOOGLE_API_KEY

if not GOOGLE_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY not set. Get a key at "
            "https://aistudio.google.com/apikey and put it in .env"
        )

_gemini_client = genai.Client(api_key=GOOGLE_API_KEY)

def _rule_bounds_text(rule: dict) -> str:
    """Renders only the playbook's numeric/categorical bounds as plain text —
    this is the sole source of truth for 'acceptable', given to the LLM so
    it can't invent its own thresholds."""
    keys = ("acceptable_min_days", "acceptable_max_days", "acceptable_min_years",
            "acceptable_max_years", "acceptable_min_multiplier", "acceptable",
            "acceptable_values", "acceptable_jurisdictions")
    parts = [f"{k}={rule[k]}" for k in keys if k in rule]
    return "; ".join(parts) if parts else "no explicit numeric bound — judge by presence/absence"


RECONCILE_INSTRUCTIONS = """Respond with ONLY a JSON object, no markdown fences, no extra text, matching exactly this shape:
{"status": "ok" | "flagged" | "not_found",
 "risk": "high" | "medium" | "low" | null,
 "cited_value": "<copy this VERBATIM from the evidence dict above -- the exact value you are basing your decision on -- or null if status is not_found>",
 "issue": "<one sentence explaining the flag, only if status is flagged, else empty string>"}

Rules:
- Base your decision ONLY on the evidence dict given. Do not assume facts about the contract that aren't in it.
- cited_value must be copied exactly from a value that appears in the evidence dict. Do not compute, round, or restate it differently.
- If the evidence doesn't actually support a judgement (e.g. matched_text is off-topic for this rule), return status "not_found".
"""


def reconcile_clause(clause_type: str, rule: dict, evidence: dict) -> dict:
    """
    Step 3 of the pipeline. Takes the playbook rule plus every signal
    extracted in Step 2 (nlp_utils.extract_evidence) and asks Gemini to make
    the actual risk call -- reading nuance a rigid threshold comparison can
    miss, e.g. a clause that technically exceeds a limit but is qualified
    elsewhere in the same sentence.

    Anti-hallucination design:
      - The model receives ONLY the evidence dict below, never the full
        contract -- it has nothing to "recall" or invent beyond this clause.
      - temperature=0 and JSON-only output reduce free-form drift.
      - The model must set cited_value to something copied verbatim from the
        evidence. playbook_engine.reconcile_contract() checks that citation
        against the evidence after this call returns, and discards the
        verdict (falling back to the deterministic rule check) if the cited
        value doesn't actually appear in the evidence -- see
        _citation_is_grounded() there. This function does not self-verify;
        the guardrail is intentionally external to it.
    """

    prompt = f"""You are reconciling one contract clause against a compliance rule.

RULE: {rule.get('label', clause_type)} -- {rule['description']}
RULE BOUNDS: {_rule_bounds_text(rule)}

EVIDENCE (already extracted by upstream NLP steps -- regex, NER, fuzzy matching):
{json.dumps(evidence, indent=2)}

{RECONCILE_INSTRUCTIONS}
"""

    response = _gemini_client.models.generate_content(
    model=GEMINI_MODEL,
    contents=prompt,
    config={
        "response_mime_type": "application/json",
        "temperature": 0.0,
    },
    )

    raw = response.text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        raw = raw[4:] if raw.startswith("json") else raw

    try:
        parsed = json.loads(raw)
        parsed.setdefault("status", "not_found")
        parsed.setdefault("risk", None)
        parsed.setdefault("cited_value", None)
        parsed.setdefault("issue", "")
        return parsed
    except json.JSONDecodeError:
        return {"status": "not_found", "risk": None, "cited_value": None,
                "issue": "LLM reconciliation returned unparseable output; needs manual review."}


def summarize_flags(contract_name: str, flags: list[dict]) -> str:
    """
    Takes the deterministic flag list produced by playbook_engine and asks
    Gemini to write a short, plain-English risk summary for a human reviewer.
    The model is given the flags as facts — it explains them, it doesn't
    invent them.
    """

    flagged = [f for f in flags if f["status"] == "flagged"]
    if not flagged:
        return f"No playbook risks were identified in {contract_name}. All checked clauses fall within acceptable ranges."

    flag_lines = "\n".join(
        f"- [{(f.get('risk') or 'unspecified').upper()}] {f['label']}: {f['issue']}" for f in flagged
    )

    prompt = f"""You are assisting a contracts reviewer. Below is a list of
issues already identified by a deterministic rules engine for the contract
"{contract_name}". Do not add new issues or change the risk levels — only
explain the ones given, in plain English, grouped by risk level (high, then
medium, then low). Keep it under 150 words.

Issues:
{flag_lines}
"""
    response = _gemini_client.models.generate_content(
    model=GEMINI_MODEL,
    contents=prompt,
)
    return response.text


def answer_question_about_contract(contract_name: str, clause_results: list[dict], question: str) -> str:
    """
    Lets the user chat with a previously reviewed contract, grounded in the
    stored clause extraction results (not the raw PDF re-read each time —
    that's what persistent memory is for).
    """

    context_lines = "\n".join(
        f"- {c['label']}: {c.get('extracted_value', c.get('issue', 'not found'))}"
        for c in clause_results
    )

    prompt = f"""You are answering questions about a contract named "{contract_name}"
using only the extracted clause data below. If the answer isn't in the data,
say so rather than guessing.

Extracted clause data:
{context_lines}

Question: {question}
"""
    response = _gemini_client.models.generate_content(
    model=GEMINI_MODEL,
    contents=prompt,
)
    return response.text
