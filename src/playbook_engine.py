"""
playbook_engine.py — deterministic rule evaluation.

This is intentionally boring, plain Python: no LLM, no embeddings.
Once nlp_utils.py has told us "this paragraph is the termination_notice
clause" and pulled out "45 days" as the value, deciding whether 45 days
breaches the playbook rule (min 30 / max 90) is arithmetic — arithmetic
should not be delegated to a language model.
"""

import yaml
from src import llm_gemini, nlp_utils
from config import PLAYBOOK_PATH


def load_playbook() -> dict:
    with open(PLAYBOOK_PATH, "r") as f:
        return yaml.safe_load(f)


def evaluate_clause(clause_type: str, rule: dict, matched_text: str | None,
                     structured_value=None) -> dict:
    """
    Evaluates a single matched (or missing) clause against its playbook rule.
    Returns a flag dict if there's an issue, otherwise a clean-status dict.
    """
    result = {
        "clause_type": clause_type,
        "label": rule.get("label", clause_type),
        "matched_text": matched_text,
        "status": "ok",
        "risk": None,
        "issue": None,
    }

    if matched_text is None:
        # Clause wasn't found in the contract at all
        if rule.get("value_type") == "boolean" and rule.get("acceptable") is True:
            result.update(status="flagged", risk=rule.get("risk_if_absent", "medium"),
                          issue=f"{rule['label']} not found in contract.")
        elif "risk_if_missing" in rule:
            result.update(status="flagged", risk=rule["risk_if_missing"],
                          issue=f"{rule['label']} not found in contract.")
        else:
            result.update(status="not_found", risk="low",
                          issue=f"{rule['label']} not found — could not evaluate.")
        return result

    value_type = rule["value_type"]

    if value_type == "days":
        days = nlp_utils.extract_days(matched_text)
        if days is None:
            result.update(status="not_found", issue="Could not extract a day value from matched clause.")
        elif "acceptable_min_days" in rule and days < rule["acceptable_min_days"]:
            result.update(status="flagged", risk=rule["risk_if_below_min"],
                          issue=f"{rule['label']} is {days} days, below minimum of {rule['acceptable_min_days']}.")
        elif "acceptable_max_days" in rule and days > rule["acceptable_max_days"]:
            result.update(status="flagged", risk=rule["risk_if_above_max"],
                          issue=f"{rule['label']} is {days} days, above maximum of {rule['acceptable_max_days']}.")
        else:
            result["extracted_value"] = days

    elif value_type == "years":
        years = nlp_utils.extract_years(matched_text)
        if years is None:
            result.update(status="not_found", issue="Could not extract a duration from matched clause.")
        elif "acceptable_min_years" in rule and years < rule["acceptable_min_years"]:
            result.update(status="flagged", risk=rule["risk_if_below_min"],
                          issue=f"{rule['label']} is {years} years, below minimum of {rule['acceptable_min_years']}.")
        elif "acceptable_max_years" in rule and years > rule["acceptable_max_years"]:
            result.update(status="flagged", risk=rule["risk_if_above_max"],
                          issue=f"{rule['label']} is {years} years, above maximum of {rule['acceptable_max_years']}.")
        else:
            result["extracted_value"] = years

    elif value_type == "multiplier":
        mult = nlp_utils.extract_multiplier(matched_text)
        if mult is None:
            result.update(status="not_found", issue="Could not extract a liability multiplier from matched clause.")
        elif mult < rule.get("acceptable_min_multiplier", 1.0):
            result.update(status="flagged", risk=rule["risk_if_below_min"],
                          issue=f"{rule['label']} is {mult}x fees, below minimum of {rule['acceptable_min_multiplier']}x.")
        else:
            result["extracted_value"] = mult

    elif value_type == "boolean":
        # e.g. auto_renewal, assignment_rights, carve-outs present.
        # Kept only as the guardrail fallback path (see reconcile_contract below) —
        # the primary decision now comes from llm_client.reconcile_clause, which
        # is grounded against the same evidence this regex/fuzzy check produces.
        if structured_value is not None:
            clause_is_present_as_written = bool(structured_value)
        else:
            clause_is_present_as_written = not nlp_utils.contains_negation(matched_text)

        if clause_is_present_as_written and rule.get("acceptable") is False:
            result.update(status="flagged", risk=rule["risk_if_present"],
                          issue=f"{rule['label']} appears to be present without restriction.")
        else:
            result["extracted_value"] = clause_is_present_as_written

    elif value_type == "categorical":
        # Prefer the LLM classification — a mutual indemnification clause rarely
        # contains the literal word "mutual", so fuzzy string matching against the
        # keyword misses it. Fall back to fuzzy matching only if no LLM value given.
        if structured_value is not None:
            acceptable = structured_value in rule.get("acceptable_values", [])
            if not acceptable:
                risk_key = "risk_if_one_sided" if "risk_if_one_sided" in rule else "risk_if_unspecified"
                result.update(status="flagged", risk=rule.get(risk_key, "medium"),
                              issue=f"{rule['label']} classified as '{structured_value}', "
                                    f"not one of {rule.get('acceptable_values')}.")
            else:
                result["extracted_value"] = structured_value
        else:
            found = nlp_utils.fuzzy_find(matched_text, rule.get("acceptable_values", []))
            if not found:
                risk_key = "risk_if_one_sided" if "risk_if_one_sided" in rule else "risk_if_unspecified"
                result.update(status="flagged", risk=rule.get(risk_key, "medium"),
                              issue=f"{rule['label']} does not clearly match an acceptable value "
                                    f"({rule.get('acceptable_values')}).")
            else:
                result["extracted_value"] = found[0]

    elif value_type == "jurisdiction":
        found = nlp_utils.fuzzy_find(matched_text, rule.get("acceptable_jurisdictions", []))
        if not found:
            result.update(status="flagged", risk=rule.get("risk_if_not_listed", "low"),
                          issue=f"{rule['label']} not on approved list "
                                f"({rule.get('acceptable_jurisdictions')}).")
        else:
            result["extracted_value"] = found[0]

    return result


def evaluate_contract(matches: list[dict], playbook: dict) -> list[dict]:
    """Runs evaluate_clause() for every matched clause type.

    This is the pure rule-based path, kept as-is. It's used two ways now:
      1. Directly, if you want a fully deterministic run (see reconcile_contract's
         `use_llm=False` option below).
      2. As the guardrail fallback inside reconcile_contract() when the LLM's
         cited evidence can't be verified.
    """
    results = []
    for m in matches:
        rule = playbook["clauses"][m["clause_type"]]
        results.append(evaluate_clause(
            m["clause_type"], rule, m["matched_text"], m.get("structured_value")
        ))
    return results


# ---------------------------------------------------------------------------
# Step 2 + Step 3 orchestration — evidence extraction, then LLM reconciliation,
# then a deterministic guardrail that verifies the LLM's citation before
# trusting its verdict.
# ---------------------------------------------------------------------------

def _citation_is_grounded(cited_value, evidence: dict) -> bool:
    """
    Checks that whatever the LLM says it relied on (cited_value) actually
    appears somewhere in the Step 2 evidence dict, rather than being a
    number or phrase the model generated on its own. This is the guardrail:
    it doesn't judge whether the LLM's *reasoning* is correct, only whether
    its claimed evidence is real.
    """
    if cited_value in (None, "", "null"):
        return True  # a "not_found"/no-citation verdict has nothing to fabricate
    cited_str = str(cited_value).strip().lower()
    if not cited_str:
        return True
    for v in evidence.values():
        if v is None:
            continue
        if isinstance(v, list):
            if any(cited_str in str(item).lower() or str(item).lower() in cited_str for item in v):
                return True
        else:
            if cited_str in str(v).lower() or str(v).lower() in cited_str:
                return True
    return False


def reconcile_contract(matches: list[dict], playbook: dict) -> list[dict]:
    """
    The full 3-step architecture:

      Step 1 (already done upstream, in nlp_utils.match_clauses_to_paragraphs):
              cosine similarity over embeddings picks the matched paragraph
              for each clause type.
      Step 2  nlp_utils.extract_evidence() pulls regex/NER/fuzzy-match signals
              out of that paragraph -- no decisions made here.
      Step 3  llm_client.reconcile_clause() reads the rule + evidence and
              returns the actual risk verdict, citing which evidence it used.

    Guardrail: after Step 3, _citation_is_grounded() checks the LLM's citation
    against the Step 2 evidence. If it doesn't check out -- the LLM cited a
    value that was never extracted -- its verdict is discarded and
    evaluate_clause() (the deterministic path) is used for that clause
    instead, with a note added explaining the fallback. This bounds how much
    a single clause's outcome can be pure LLM invention, without giving up
    the nuance an LLM adds over rigid threshold checks.
    """
    results = []
    for m in matches:
        clause_type = m["clause_type"]
        rule = playbook["clauses"][clause_type]
        matched_text = m["matched_text"]

        if matched_text is None:
            results.append(evaluate_clause(clause_type, rule, None))
            continue

        evidence = nlp_utils.extract_evidence(clause_type, rule, matched_text)
        llm_result = llm_gemini.reconcile_clause(clause_type, rule, evidence)

        if _citation_is_grounded(llm_result.get("cited_value"), evidence):
            results.append({
                "clause_type": clause_type,
                "label": rule.get("label", clause_type),
                "matched_text": matched_text,
                "status": llm_result.get("status", "not_found"),
                "risk": llm_result.get("risk"),
                "issue": llm_result.get("issue") or None,
                "extracted_value": llm_result.get("cited_value"),
                "decided_by": "llm_reconciliation",
            })
        else:
            fallback = evaluate_clause(clause_type, rule, matched_text)
            fallback["issue"] = (
                (fallback.get("issue") + " " if fallback.get("issue") else "")
                + "[Guardrail: LLM citation was not grounded in extracted evidence -- "
                  "used the deterministic rule check instead.]"
            )
            fallback["decided_by"] = "deterministic_fallback"
            results.append(fallback)

    return results
