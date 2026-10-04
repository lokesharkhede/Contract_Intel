"""
nlp_utils.py — the classic-NLP layer of the pipeline.

This module answers the "where does cosine similarity fit?" question directly:

  - Cosine similarity (via sentence embeddings) is used ONLY to figure out
    WHICH paragraph in the contract corresponds to WHICH playbook clause type.
    This is a semantic retrieval/classification problem — clause wording varies
    a lot between contracts ("either party may terminate for convenience" vs.
    "this agreement may be ended by written notice") and cosine similarity on
    embeddings handles that variation far better than keyword matching.

  - Cosine similarity is NOT used to decide if a clause is risky. That decision
    is deterministic (is 10 days < 30 days?), and belongs in playbook_engine.py,
    not here. Comparing "45 days" to "risky" using embeddings would be the wrong
    tool for a numeric threshold rule — embeddings capture meaning, not magnitude.

So: embeddings for "which clause is this", plain code for "is this clause a problem".
"""

import re
import spacy
from sentence_transformers import SentenceTransformer, util
from rapidfuzz import fuzz

from config import EMBEDDING_MDOEL, CLAUSE_MATCH_THRESHOLD, FUZZY_MATCH_THRESHOLD

_embedding_model = None
_nlp = None


def get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        _embedding_model = SentenceTransformer(EMBEDDING_MDOEL)
    return _embedding_model


def get_spacy_model():
    global _nlp
    if _nlp is None:
        _nlp = spacy.load("en_core_web_sm")
    return _nlp


# ---------------------------------------------------------------------------
# 1. Semantic clause matching via cosine similarity
# ---------------------------------------------------------------------------

def match_clauses_to_paragraphs(paragraphs: list[str], playbook: dict) -> list[dict]:
    """
    For each clause type in the playbook, find the paragraph in the contract
    that is semantically closest to that clause's reference_text, using
    cosine similarity over sentence embeddings.

    Returns one match dict per clause type that clears the threshold:
        {clause_type, matched_text, confidence}
    Clause types with no paragraph above CLAUSE_MATCH_THRESHOLD are treated
    as "not found" (handled downstream — e.g. missing liability cap = high risk).
    """
    model = get_embedding_model()
    para_embeddings = model.encode(paragraphs, convert_to_tensor=True)

    matches = []
    for clause_type, rule in playbook["clauses"].items():
        ref_embedding = model.encode(rule["reference_text"], convert_to_tensor=True)
        scores = util.cos_sim(ref_embedding, para_embeddings)[0]
        best_idx = int(scores.argmax())
        best_score = float(scores[best_idx])

        if best_score >= CLAUSE_MATCH_THRESHOLD:
            matches.append({
                "clause_type": clause_type,
                "matched_text": paragraphs[best_idx],
                "confidence": round(best_score, 3),
            })
        else:
            matches.append({
                "clause_type": clause_type,
                "matched_text": None,
                "confidence": round(best_score, 3),
            })

    return matches


# ---------------------------------------------------------------------------
# 2. Named Entity Recognition — pull dates/durations/money out of matched text
# ---------------------------------------------------------------------------

def extract_entities(text: str) -> dict:
    if not text:
        return {"durations": [], "money": []}
    doc = get_spacy_model()(text)
    return {
        "durations": [ent.text for ent in doc.ents if ent.label_ in ("DATE", "CARDINAL")],
        "money": [ent.text for ent in doc.ents if ent.label_ == "MONEY"],
    }


# ---------------------------------------------------------------------------
# 2b. Evidence bundling — Step 2 of the pipeline
# ---------------------------------------------------------------------------

def extract_evidence(clause_type: str, rule: dict, matched_text: str | None) -> dict:
    """
    Pulls every candidate signal out of the matched clause text using plain
    NLP techniques — regex, NER, fuzzy matching. This function NEVER decides
    anything. It only surfaces raw evidence for the LLM reconciliation step
    (Step 3, in playbook_engine.reconcile_contract) to reason over, and for
    the guardrail to check the LLM's citation against afterward.

    Keeping extraction and decision-making in separate functions is what
    makes the guardrail possible: Step 3 must cite a value that already
    exists here, it can't introduce a new one.
    """
    if not matched_text:
        return {"matched_text": None}

    evidence = {"matched_text": matched_text}
    value_type = rule["value_type"]

    if value_type == "days":
        evidence["regex_days"] = extract_days(matched_text)
    elif value_type == "years":
        evidence["regex_years"] = extract_years(matched_text)
    elif value_type == "multiplier":
        evidence["regex_multiplier"] = extract_multiplier(matched_text)
    elif value_type == "boolean":
        evidence["negation_detected"] = contains_negation(matched_text)
    elif value_type == "categorical":
        evidence["fuzzy_candidates"] = fuzzy_find(
            matched_text, rule.get("acceptable_values", []) + ["one_sided"]
        )
    elif value_type == "jurisdiction":
        evidence["fuzzy_candidates"] = fuzzy_find(
            matched_text, rule.get("acceptable_jurisdictions", [])
        )

    entities = extract_entities(matched_text)
    evidence["ner_dates_or_durations"] = entities["durations"]
    evidence["ner_money"] = entities["money"]
    return evidence


# ---------------------------------------------------------------------------
# 3. Regex — deterministic extraction of days/years/multipliers
#    (cheaper and more reliable than an LLM call for well-patterned numbers)
# ---------------------------------------------------------------------------

def extract_days(text: str) -> int | None:
    """
    Handles both '45 days' and the common legal-drafting style
    'forty-five (45) days', where the digit sits in parentheses
    right before the unit rather than directly adjacent to it.
    """
    if not text:
        return None
    match = re.search(r"\(?(\d+)\)?\s*(?:calendar\s+)?days", text, re.IGNORECASE)
    return int(match.group(1)) if match else None


def extract_years(text: str) -> float | None:
    if not text:
        return None
    match = re.search(r"\(?(\d+)\)?\s*years?", text, re.IGNORECASE)
    if match:
        return float(match.group(1))
    months_match = re.search(r"\(?(\d+)\)?\s*months?", text, re.IGNORECASE)
    if months_match:
        return round(int(months_match.group(1)) / 12, 2)
    return None


def extract_multiplier(text: str) -> float | None:
    if not text:
        return None
    # matches "2x", "2 times", "(2x)", "0.5x"
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:x|times)", text, re.IGNORECASE)
    return float(match.group(1)) if match else None


def contains_negation(text: str) -> bool:
    """Cheap heuristic: does the clause explicitly negate the behavior
    (e.g. 'shall not renew automatically')."""
    if not text:
        return False
    return bool(re.search(r"\bshall not\b|\bwill not\b|\bno automatic\b", text, re.IGNORECASE))


# ---------------------------------------------------------------------------
# 4. Fuzzy string matching — jurisdiction / categorical checks
# ---------------------------------------------------------------------------

def fuzzy_find(text: str, candidates: list[str], threshold: int = FUZZY_MATCH_THRESHOLD) -> list[str]:
    if not text:
        return []
    return [c for c in candidates if fuzz.partial_ratio(c.lower(), text.lower()) >= threshold]
