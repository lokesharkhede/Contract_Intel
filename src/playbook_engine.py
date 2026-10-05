import yaml
from src import llm_gemini, nlp_utils
from config import PLAYBOOK_PATH


def load_playbook() -> dict:
    with open(PLAYBOOK_PATH, "r") as f:
        return yaml.safe_load(f)


def evaluate_clause(clause_type: str, rule: dict, matched_text: str | None,
                     structured_value=None) -> dict:
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
    results = []
    for m in matches:
        rule = playbook["clauses"][m["clause_type"]]
        results.append(evaluate_clause(
            m["clause_type"], rule, m["matched_text"], m.get("structured_value")
        ))
    return results

def _citation_is_grounded(cited_value, evidence: dict) -> bool:
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
