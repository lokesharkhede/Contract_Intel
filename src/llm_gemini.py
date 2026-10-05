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
