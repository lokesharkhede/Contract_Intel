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

def match_clauses_to_paragraphs(paragraphs: list[str], playbook: dict) -> list[dict]:
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

def extract_entities(text: str) -> dict:
    if not text:
        return {"durations": [], "money": []}
    doc = get_spacy_model()(text)
    return {
        "durations": [ent.text for ent in doc.ents if ent.label_ in ("DATE", "CARDINAL")],
        "money": [ent.text for ent in doc.ents if ent.label_ == "MONEY"],
    }

def extract_evidence(clause_type: str, rule: dict, matched_text: str | None) -> dict:
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

def extract_days(text: str) -> int | None:
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
    if not text:
        return False
    return bool(re.search(r"\bshall not\b|\bwill not\b|\bno automatic\b", text, re.IGNORECASE))

def fuzzy_find(text: str, candidates: list[str], threshold: int = FUZZY_MATCH_THRESHOLD) -> list[str]:
    if not text:
        return []
    return [c for c in candidates if fuzz.partial_ratio(c.lower(), text.lower()) >= threshold]
