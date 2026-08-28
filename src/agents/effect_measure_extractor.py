"""Extract quantitative effect estimates for pollutant-outcome pairs."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from src.config.settings import settings
from src.io.json_io import read_json, read_json_or_empty, write_json
from src.agents.document_chunks import (
    extract_title_and_abstract,
    extract_document_chunks,
    build_chunk_text_with_context,
    write_reasoning_file,
)


# Context keywords

EFFECT_CONTEXT_KEYWORDS = [
    "odds ratio",
    "relative risk",
    "risk ratio",
    "hazard ratio",
    "incidence rate ratio",
    "rate ratio",
    "beta",
    "coefficient",
    "percent change",
    "% change",
    "95% ci",
    "confidence interval",
    "ci:",
    "p =",
    "p=",
    "p-value",
    "p value",
    "per ",
    "increase",
    "decrease",
    "higher",
    "lower",
    "associated",
    "association",
    "effect estimate",
    "estimate",
    "logistic regression",
    "poisson",
    "cox",
    "ivw",
    "inverse variance weighted",
    "mendelian randomization",
    "mr-presso",
    "mr presso",
    "weighted median",
    "mr egger",
    "egger",
    "heterogeneity",
    "pleiotropy",
    "f-statistic",
    "f statistic",
    "twas",
    "gwas",
    "significant",
    "non-significant",
    "not significant",
]

MEASURE_TYPE_ALIASES = {
    "odds ratio": "OR",
    "or": "OR",
    "relative risk": "RR",
    "risk ratio": "RR",
    "rr": "RR",
    "hazard ratio": "HR",
    "hr": "HR",
    "incidence rate ratio": "IRR",
    "irr": "IRR",
    "rate ratio": "IRR",
    "beta": "beta",
    "coefficient": "beta",
    "percent change": "percent_change",
    "% change": "percent_change",
    "percentage change": "percent_change",
    "p value": "p_value",
    "p-value": "p_value",
    "p": "p_value",
}

DIRECT_MEASURE_TYPES = {
    "OR",
    "RR",
    "HR",
    "IRR",
    "beta",
    "coefficient",
    "percent_change",
}

REJECT_MEASURE_ROLES = {
    "pleiotropy_test",
    "heterogeneity_test",
    "gene_association",
    "model_diagnostic",
    "p_value_only",
    "trend_test_only",
    "incomplete_effect_description",
}


# Generic helpers

def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def safe_str(value: Any) -> str:
    if value is None:
        return ""

    text = str(value).strip()

    if text.lower() in {"nan", "none", "null", "not reported", "nr"}:
        return ""

    return text


def safe_float(value: Any, default: float = 0.0) -> float:
    parsed = parse_float_or_none(value)

    if parsed is None:
        return default

    return parsed


def safe_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value

    text = safe_str(value).lower()

    if text in {"true", "1", "yes", "y"}:
        return True

    if text in {"false", "0", "no", "n"}:
        return False

    return default


def safe_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value

    return []


def normalize_text(value: Any) -> str:
    text = safe_str(value).lower()
    text = text.replace("₂", "2").replace("₃", "3").replace("ₓ", "x")
    text = text.replace("β", "beta")
    text = text.replace("μ", "µ")
    text = text.replace("−", "-")
    text = text.replace("–", "-").replace("—", "-")
    text = text.replace("_", " ")
    text = " ".join(text.split())
    return text


def compact(value: Any) -> str:
    text = normalize_text(value)
    return re.sub(r"[^a-z0-9]", "", text)


def parse_float_or_none(value: Any) -> float | None:
    text = safe_str(value)

    if not text:
        return None

    text = text.replace(",", ".")
    text = text.replace("−", "-")
    text = text.replace("×10", "e")
    text = re.sub(r"(?i)\s*x\s*10\^", "e", text)
    text = re.sub(r"[^0-9eE\.\-\+]", "", text)

    if not text:
        return None

    try:
        return float(text)
    except Exception:
        return None


def parse_p_value(value: Any) -> tuple[str, float | None]:
    text = safe_str(value)

    if not text:
        return "", None

    normalized = (
        text.replace("−", "-")
        .replace(",", ".")
        .replace("=>", ">")
        .replace("=<", "<")
        .strip()
    )

    numeric = parse_float_or_none(normalized)

    return normalized, numeric


def normalize_measure_type(value: Any, evidence: str = "") -> str:
    raw = normalize_text(value)

    if raw in MEASURE_TYPE_ALIASES:
        return MEASURE_TYPE_ALIASES[raw]

    evidence_text = normalize_text(evidence)

    if "odds ratio" in evidence_text or re.search(r"\bor\b", evidence_text):
        return "OR"

    if "hazard ratio" in evidence_text or re.search(r"\bhr\b", evidence_text):
        return "HR"

    if "relative risk" in evidence_text or "risk ratio" in evidence_text:
        return "RR"

    if "incidence rate ratio" in evidence_text or re.search(r"\birr\b", evidence_text):
        return "IRR"

    if "percent change" in evidence_text or "% change" in evidence_text:
        return "percent_change"

    if "beta" in evidence_text or "coefficient" in evidence_text:
        return "beta"

    if raw:
        return MEASURE_TYPE_ALIASES.get(raw, raw)

    return ""


def infer_measure_family(measure_type: str) -> str:
    if measure_type in {"OR", "RR", "HR", "IRR"}:
        return "ratio"

    if measure_type in {"beta", "coefficient"}:
        return "difference"

    if measure_type == "percent_change":
        return "percent_change"

    if measure_type == "p_value":
        return "p_value"

    return "other"


def infer_effect_direction(
    measure_type: str,
    effect_value_numeric: float | None,
    evidence: str,
) -> str:
    text = normalize_text(evidence)

    if "increase" in text or "increased" in text or "higher" in text:
        return "increase"

    if "decrease" in text or "decreased" in text or "lower" in text:
        return "decrease"

    if effect_value_numeric is None:
        return "unknown"

    if measure_type in {"OR", "RR", "HR", "IRR"}:
        if effect_value_numeric > 1:
            return "increase"

        if effect_value_numeric < 1:
            return "decrease"

        return "null"

    if measure_type in {"beta", "coefficient", "percent_change"}:
        if effect_value_numeric > 0:
            return "increase"

        if effect_value_numeric < 0:
            return "decrease"

        return "null"

    return "unknown"


def infer_statistical_significance(
    ci_lower_numeric: float | None,
    ci_upper_numeric: float | None,
    p_value_numeric: float | None,
    measure_type: str,
    evidence: str,
    p_value_raw: str = "",
) -> str:
    text = normalize_text(evidence)
    p_raw = safe_str(p_value_raw).replace("=>", ">").replace("=<", "<")

    if (
        "not significant" in text
        or "non significant" in text
        or "non-significant" in text
        or "without significance" in text
        or "no significant" in text
    ):
        return "non_significant"

    if p_value_numeric is not None:
        if ">" in p_raw and p_value_numeric >= 0.05:
            return "non_significant"

        if "<" in p_raw and p_value_numeric <= 0.05:
            return "significant"

        if p_value_numeric < 0.05:
            return "significant"

        return "non_significant"

    if ci_lower_numeric is not None and ci_upper_numeric is not None:
        if measure_type in {"OR", "RR", "HR", "IRR"}:
            if ci_lower_numeric > 1 or ci_upper_numeric < 1:
                return "significant"

            return "non_significant"

        if measure_type in {"beta", "coefficient", "percent_change"}:
            if ci_lower_numeric > 0 or ci_upper_numeric < 0:
                return "significant"

            return "non_significant"

    if "significant" in text:
        return "significant"

    return "unknown"


# Prior extracted entities

def format_previous_pollutants_for_prompt(pollutant_payload: dict[str, Any]) -> str:
    pollutants = safe_list(pollutant_payload.get("pollutants_found"))

    if not pollutants:
        return "No previous pollutants available."

    lines = []

    for item in pollutants[:30]:
        specific = safe_str(item.get("pollutant_specific"))
        role = safe_str(item.get("pollutant_role"))
        lines.append(f"- {specific} ({role})")

    return "\n".join(lines)


def format_previous_outcomes_for_prompt(outcome_payload: dict[str, Any]) -> str:
    outcomes = safe_list(outcome_payload.get("outcomes_found"))

    if not outcomes:
        return "No previous outcomes available."

    lines = []

    for item in outcomes[:30]:
        core = safe_str(item.get("outcome_core"))
        role = safe_str(item.get("outcome_role"))
        keep = safe_str(item.get("keep_for_final_analysis"))
        lines.append(f"- {core} ({role}, keep={keep})")

    return "\n".join(lines)


# Prompt

def build_effect_measure_prompt(
    pmid: str,
    document_text: str,
    previous_pollutants_text: str,
    previous_outcomes_text: str,
) -> list[dict[str, str]]:
    system_prompt = """
You are a scientific information extraction agent.

Task:
Extract quantitative pollutant-health outcome effect estimates.

Rules:
- Extract direct exposure/pollutant -> health outcome quantitative estimates.
- Extract direct pollutant-outcome effect estimates first.
- Extract OR, RR, HR, IRR, beta/coefficient, percent change when numeric.
- Include CI and p-value when available.
- Keep non-significant direct effects if a numeric effect estimate is reported.
- Do NOT extract p-value-only results as direct effects.
- Do NOT create incomplete OR/RR/HR rows with empty effect_value.
- If a pollutant is mentioned without a numeric estimate, skip it.
- Do NOT extract pleiotropy tests, heterogeneity tests, F-statistics, model diagnostics, or gene associations as direct effects.
- Include diagnostics only if they are short and explicitly reported.
- Mark diagnostics with the correct measure_role.
- Do NOT infer values not explicitly present.
- Keep evidence_sentence short.
- Before listing effect_measures_found, think step by step in the "reasoning" field: identify candidate pollutant-outcome pairs, check each against the rules above (numeric value present, not a diagnostic-only test, correct measure_role), and note why any candidate was excluded or reclassified. Keep it concise (2-5 short sentences).
- Return only valid JSON.
- No markdown.
- No code fences.
""".strip()

    user_prompt = f"""
PMID: {pmid}

Previously extracted pollutants/exposures:
{previous_pollutants_text}

Previously extracted outcomes:
{previous_outcomes_text}

Return ONLY this compact JSON structure:

{{
  "reasoning": "brief step-by-step notes on candidate pollutant-outcome pairs and inclusion/exclusion decisions",
  "effect_measures_found": [
    {{
      "pollutant_mention": "PM2.5 | NO2 | etc.",
      "outcome_mention": "asthma | ALS | etc.",
      "measure_type": "OR | RR | HR | IRR | beta | percent_change | p_value | other",
      "effect_value": "2.40",
      "ci_lower": "1.26",
      "ci_upper": "4.57",
      "ci_level": "95%",
      "p_value": "7.46E-3",
      "exposure_increment": "per 10-µg/m3 increase in NO2",
      "analysis_method": "logistic regression | IVW | MR-PRESSO | etc.",
      "adjustment_status": "adjusted | unadjusted | unknown",
      "measure_role": "direct_effect_estimate | pleiotropy_test | heterogeneity_test | gene_association | model_diagnostic | p_value_only | incomplete_effect_description",
      "evidence_sentence": "short supporting sentence",
      "source_section": "section name if available",
      "confidence": 0.95
    }}
  ],
  "warnings": [],
  "errors": []
}}

Important:
- If NO2 has only 'similar trend' with no numeric effect estimate, do not create a direct effect estimate.
- If a sentence says p > 0.05 for pleiotropy or heterogeneity, mark it as pleiotropy_test or heterogeneity_test.
- If a sentence reports F-statistics, mark it as model_diagnostic.
- If a sentence reports genes associated with exposure/outcome, mark it as gene_association.
- For association building, direct_effect_estimate is the main useful role.
- Do not output incomplete direct effects with empty effect_value.

Document effect-focused context:
{document_text}
""".strip()

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


# Normalization and classification

def infer_measure_role(
    item: dict[str, Any],
    measure_type: str,
    evidence: str,
) -> str:
    model_role = safe_str(item.get("measure_role"))

    if model_role in {
        "direct_effect_estimate",
        "pleiotropy_test",
        "heterogeneity_test",
        "gene_association",
        "model_diagnostic",
        "p_value_only",
        "trend_test_only",
        "incomplete_effect_description",
    }:
        return model_role

    text = normalize_text(
        " ".join(
            [
                evidence,
                safe_str(item.get("analysis_method")),
                safe_str(item.get("measure_type")),
            ]
        )
    )

    if "pleiotropy" in text:
        return "pleiotropy_test"

    if "heterogeneity" in text or "cochran" in text:
        return "heterogeneity_test"

    if "f-statistic" in text or "f statistic" in text or "above 10" in text:
        return "model_diagnostic"

    if "twas" in text or "gene" in text or "genes" in text:
        return "gene_association"

    if measure_type == "p_value":
        return "p_value_only"

    effect_value = parse_float_or_none(item.get("effect_value"))

    if effect_value is None:
        return "incomplete_effect_description"

    return "direct_effect_estimate"


def infer_analysis_method(item: dict[str, Any], evidence: str) -> str:
    model_value = safe_str(item.get("analysis_method"))

    if model_value:
        return model_value

    text = normalize_text(evidence)

    if "mr presso" in text or "mr-presso" in text:
        return "MR-PRESSO"

    if "inverse variance weighted" in text or "ivw" in text:
        return "IVW"

    if "weighted median" in text:
        return "weighted median"

    if "mr egger" in text or "egger" in text:
        return "MR-Egger"

    if "logistic regression" in text:
        return "logistic regression"

    if "poisson" in text:
        return "Poisson regression"

    if "cox" in text:
        return "Cox regression"

    if "linear regression" in text:
        return "linear regression"

    return "unknown"


def infer_adjustment_status(item: dict[str, Any], evidence: str) -> str:
    model_value = safe_str(item.get("adjustment_status"))

    if model_value in {"adjusted", "unadjusted", "unknown"}:
        return model_value

    text = normalize_text(evidence)

    if "adjusted" in text or "adjustment" in text or "controlled for" in text:
        return "adjusted"

    if "unadjusted" in text or "crude" in text:
        return "unadjusted"

    return "unknown"


def parse_exposure_increment_value_and_unit(
    exposure_increment: str,
) -> tuple[str, float | None, str]:
    text = safe_str(exposure_increment)

    if not text:
        return "", None, ""

    value = None
    unit = ""

    match = re.search(
        r"per\s+([0-9]+(?:\.[0-9]+)?)\s*[- ]?\s*([a-zA-Zµμ/0-9\.\^]+)",
        text,
        flags=re.IGNORECASE,
    )

    if match:
        value = parse_float_or_none(match.group(1))
        unit = match.group(2)

    return text, value, unit


def keep_for_association_builder(
    measure_type: str,
    measure_role: str,
    effect_value_numeric: float | None,
) -> tuple[bool, str]:
    if measure_role in REJECT_MEASURE_ROLES:
        return False, f"Excluded because measure_role={measure_role}."

    if measure_role != "direct_effect_estimate":
        return False, f"Excluded because measure_role={measure_role}."

    if measure_type not in DIRECT_MEASURE_TYPES:
        return False, (
            f"Excluded because measure_type={measure_type} "
            "is not a direct effect type."
        )

    if effect_value_numeric is None:
        return False, "Excluded because numeric effect value is missing."

    return True, "Kept as complete direct pollutant-outcome effect estimate."


def normalize_effect_item(item: dict[str, Any]) -> dict[str, Any] | None:
    evidence = safe_str(item.get("evidence_sentence"))

    pollutant_mention = safe_str(item.get("pollutant_mention"))
    outcome_mention = safe_str(item.get("outcome_mention"))

    measure_type = normalize_measure_type(item.get("measure_type"), evidence=evidence)

    effect_value = safe_str(item.get("effect_value"))
    effect_value_numeric = parse_float_or_none(effect_value)

    ci_lower = safe_str(item.get("ci_lower"))
    ci_lower_numeric = parse_float_or_none(ci_lower)

    ci_upper = safe_str(item.get("ci_upper"))
    ci_upper_numeric = parse_float_or_none(ci_upper)

    ci_level = safe_str(item.get("ci_level")) or "95%"

    p_value, p_value_numeric = parse_p_value(item.get("p_value"))

    analysis_method = infer_analysis_method(item, evidence)
    adjustment_status = infer_adjustment_status(item, evidence)
    measure_role = infer_measure_role(item, measure_type, evidence)

    exposure_increment, exposure_increment_value, exposure_increment_unit = (
        parse_exposure_increment_value_and_unit(
            safe_str(item.get("exposure_increment"))
        )
    )

    significance = infer_statistical_significance(
        ci_lower_numeric=ci_lower_numeric,
        ci_upper_numeric=ci_upper_numeric,
        p_value_numeric=p_value_numeric,
        measure_type=measure_type,
        evidence=evidence,
        p_value_raw=p_value,
    )

    effect_direction = infer_effect_direction(
        measure_type=measure_type,
        effect_value_numeric=effect_value_numeric,
        evidence=evidence,
    )

    keep, keep_reason = keep_for_association_builder(
        measure_type=measure_type,
        measure_role=measure_role,
        effect_value_numeric=effect_value_numeric,
    )

    confidence = safe_float(item.get("confidence"), default=0.0)

    if confidence < 0:
        confidence = 0.0

    if confidence > 1:
        confidence = 1.0

    raw_source_type = safe_str(item.get("source_type"))

    if "|" in raw_source_type:
        source_type = "segmented_document"
    else:
        source_type = raw_source_type or "segmented_document"

    if measure_role == "direct_effect_estimate" and (
        not pollutant_mention or not outcome_mention
    ):
        keep = False
        keep_reason = (
            "Excluded because pollutant_mention or outcome_mention is missing."
        )

    return {
        "effect_measure_id": make_effect_measure_id(
            pollutant_mention=pollutant_mention,
            outcome_mention=outcome_mention,
            measure_type=measure_type,
            effect_value=effect_value,
            ci_lower=ci_lower,
            ci_upper=ci_upper,
            p_value=p_value,
            analysis_method=analysis_method,
            evidence=evidence,
        ),

        "pollutant_mention": pollutant_mention,
        "outcome_mention": outcome_mention,

        "measure_type": measure_type,
        "measure_name": measure_type,
        "measure_family": infer_measure_family(measure_type),

        "effect_value": effect_value,
        "effect_value_numeric": effect_value_numeric,

        "ci_lower": ci_lower,
        "ci_lower_numeric": ci_lower_numeric,
        "ci_upper": ci_upper,
        "ci_upper_numeric": ci_upper_numeric,
        "ci_level": ci_level,

        "p_value": p_value,
        "p_value_numeric": p_value_numeric,

        "statistical_significance": significance,
        "effect_direction": effect_direction,

        "exposure_increment": exposure_increment,
        "exposure_increment_value": safe_str(exposure_increment_value),
        "exposure_increment_value_numeric": exposure_increment_value,
        "exposure_increment_unit": exposure_increment_unit,

        "analysis_method": analysis_method,
        "adjustment_status": adjustment_status,
        "measure_role": measure_role,

        "keep_for_association_builder": keep,
        "keep_reason": keep_reason,

        "evidence_sentence": evidence,
        "source_section": safe_str(item.get("source_section")),
        "source_type": source_type,
        "confidence": confidence,
    }


def make_effect_measure_id(
    pollutant_mention: str,
    outcome_mention: str,
    measure_type: str,
    effect_value: str,
    ci_lower: str,
    ci_upper: str,
    p_value: str,
    analysis_method: str,
    evidence: str,
) -> str:
    key = "|".join(
        [
            normalize_text(pollutant_mention),
            normalize_text(outcome_mention),
            normalize_text(measure_type),
            safe_str(effect_value),
            safe_str(ci_lower),
            safe_str(ci_upper),
            safe_str(p_value),
            normalize_text(analysis_method),
            normalize_text(evidence)[:200],
        ]
    )

    digest = hashlib.md5(key.encode("utf-8")).hexdigest()[:12]

    return f"effect_{digest}"


def effect_dedup_key(item: dict[str, Any]) -> str:
    return "|".join(
        [
            normalize_text(item.get("pollutant_mention")),
            normalize_text(item.get("outcome_mention")),
            normalize_text(item.get("measure_type")),
            safe_str(item.get("effect_value")),
            safe_str(item.get("ci_lower")),
            safe_str(item.get("ci_upper")),
            safe_str(item.get("p_value")),
            normalize_text(item.get("analysis_method")),
            normalize_text(item.get("measure_role")),
        ]
    )


def effect_priority(item: dict[str, Any]) -> tuple[int, float, int]:
    keep_priority = 1 if safe_bool(item.get("keep_for_association_builder")) else 0
    confidence = safe_float(item.get("confidence"), default=0.0)
    evidence_len = len(safe_str(item.get("evidence_sentence")))

    return keep_priority, confidence, evidence_len


def deduplicate_effect_measures(
    effects: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}

    for item in effects:
        key = effect_dedup_key(item)

        if not key:
            continue

        if key not in by_key:
            by_key[key] = item
            continue

        existing = by_key[key]

        if effect_priority(item) > effect_priority(existing):
            by_key[key] = item

    return list(by_key.values())


def normalize_effect_payload(payload: dict[str, Any]) -> dict[str, Any]:
    raw_effects = safe_list(payload.get("effect_measures_found"))

    effects = []

    for item in raw_effects:
        if not isinstance(item, dict):
            continue

        normalized = normalize_effect_item(item)

        if normalized is None:
            continue

        effects.append(normalized)

    effects = deduplicate_effect_measures(effects)

    warnings = safe_list(payload.get("warnings"))
    errors = safe_list(payload.get("errors"))

    return {
        "effect_measures_found": effects,
        "warnings": warnings,
        "errors": errors,
    }


# Public API

def run_effect_measure_extractor_for_pmid(
    pmid: str,
    segmented_document_path: Path,
    pollutant_json_path: Path | None,
    outcome_json_path: Path | None,
    output_json: Path,
    output_state_json: Path,
    raw_response_path: Path,
    repair_response_path: Path,
    reasoning_dir: Path,
    client: Any,
    model: str | None = None,
    max_output_tokens: int = 3500,
) -> dict[str, Any]:
    segmented_payload = read_json(segmented_document_path)

    pollutant_payload = {}
    outcome_payload = {}

    if pollutant_json_path is not None:
        pollutant_payload = read_json_or_empty(pollutant_json_path)

    if outcome_json_path is not None:
        outcome_payload = read_json_or_empty(outcome_json_path)

    previous_pollutants_text = format_previous_pollutants_for_prompt(
        pollutant_payload
    )

    previous_outcomes_text = format_previous_outcomes_for_prompt(
        outcome_payload
    )

    title, abstract = extract_title_and_abstract(segmented_payload)
    chunks = extract_document_chunks(segmented_payload)

    combined_effects: list[Any] = []
    combined_warnings: list[Any] = []
    combined_errors: list[Any] = []
    reasoning_entries: list[dict[str, Any]] = []
    raw_response_parts: list[str] = []
    repair_used_any = False

    for chunk in chunks:
        chunk_text = build_chunk_text_with_context(title, abstract, chunk)

        messages = build_effect_measure_prompt(
            pmid=pmid,
            document_text=chunk_text,
            previous_pollutants_text=previous_pollutants_text,
            previous_outcomes_text=previous_outcomes_text,
        )

        chunk_payload, first_response, repair_response = client.chat_json(
            messages=messages,
            model=model,
            max_tokens=max_output_tokens,
            temperature=0.0,
            repair_on_fail=True,
        )

        raw_response_parts.append(
            f"--- chunk {chunk['chunk_index']} ({chunk['section_title']}) ---\n"
            f"{first_response.content}"
        )

        if repair_response is not None:
            repair_used_any = True

        combined_effects.extend(safe_list(chunk_payload.get("effect_measures_found")))
        combined_warnings.extend(safe_list(chunk_payload.get("warnings")))
        combined_errors.extend(safe_list(chunk_payload.get("errors")))

        chunk_reasoning = safe_str(chunk_payload.get("reasoning"))

        if chunk_reasoning:
            reasoning_entries.append(
                {
                    "chunk_index": chunk["chunk_index"],
                    "section_title": chunk["section_title"],
                    "reasoning": chunk_reasoning,
                }
            )

    raw_response_path.parent.mkdir(parents=True, exist_ok=True)
    raw_response_path.write_text("\n\n".join(raw_response_parts), encoding="utf-8")

    repair_response_path.parent.mkdir(parents=True, exist_ok=True)
    repair_response_path.write_text("used" if repair_used_any else "", encoding="utf-8")

    normalized_payload = normalize_effect_payload(
        {
            "effect_measures_found": combined_effects,
            "warnings": combined_warnings,
            "errors": combined_errors,
        }
    )

    effect_measures_found = normalized_payload["effect_measures_found"]
    warnings = normalized_payload["warnings"]
    errors = normalized_payload["errors"]

    kept_effects = [
        effect for effect in effect_measures_found
        if safe_bool(effect.get("keep_for_association_builder"))
    ]

    reasoning_path = write_reasoning_file(
        reasoning_dir=reasoning_dir,
        pmid=pmid,
        agent_name="effect_measure_extractor",
        entries=reasoning_entries,
    )

    output_payload = {
        "pmid": pmid,
        "created_at": now_iso(),
        "provider": "ILAAS",
        "base_url": settings.ilaas_base_url,
        "model": model or settings.ilaas_model,
        "agent": "effect_measure_extractor",
        "effect_measures_found": effect_measures_found,
        "warnings": warnings,
        "errors": errors,
        "metadata": {
            "segmented_document_path": str(segmented_document_path),
            "pollutant_json_path": str(pollutant_json_path) if pollutant_json_path else "",
            "outcome_json_path": str(outcome_json_path) if outcome_json_path else "",
            "previous_pollutants_loaded": len(
                safe_list(pollutant_payload.get("pollutants_found"))
            ),
            "previous_outcomes_loaded": len(
                safe_list(outcome_payload.get("outcomes_found"))
            ),
            "raw_response_path": str(raw_response_path),
            "repair_response_path": str(repair_response_path),
            "reasoning_path": reasoning_path,
            "json_repair_used": repair_used_any,
            "chunks_processed": len(chunks),
            "n_effect_measures_found": len(effect_measures_found),
            "n_kept_for_association_builder": len(kept_effects),
        },
    }

    state_payload = {
        "pmid": pmid,
        "effect_measure_extractor": output_payload,
        "effect_measures_found": effect_measures_found,
        "warnings": warnings,
        "errors": errors,
        "metadata": output_payload["metadata"],
    }

    write_json(output_json, output_payload)
    write_json(output_state_json, state_payload)

    return output_payload
