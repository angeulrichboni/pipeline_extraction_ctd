"""Extract and normalize human health outcomes from segmented documents."""

from __future__ import annotations

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

OUTCOME_CONTEXT_KEYWORDS = [
    "outcome",
    "endpoint",
    "disease",
    "diagnosis",
    "diagnosed",
    "incidence",
    "incident",
    "risk",
    "cases",
    "case",
    "control",
    "controls",
    "hospital",
    "admission",
    "mortality",
    "morbidity",
    "prevalence",

    "asthma",
    "wheeze",
    "respiratory",

    "amyotrophic lateral sclerosis",
    "als",

    "alzheimer",
    "dementia",
    "vascular dementia",

    "acute kidney injury",
    "kidney",
    "renal",

    "angina",
    "angina pectoris",

    "cancer",
    "lung cancer",
    "adenocarcinoma",
    "squamous",

    "spontaneous abortion",
    "pregnancy loss",
    "fetal loss",
    "miscarriage",

    "cardiovascular",
    "ischemic",
    "stroke",
]


GENE_OR_MECHANISM_TERMS = {
    "gene",
    "genes",
    "expression",
    "mrna",
    "protein",
    "pathway",
    "methylation",
    "transcriptome",
    "twas",
    "gwas",
    "snp",
    "polymorphism",
    "variant",
}


# Helpers

def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def safe_str(value: Any) -> str:
    if value is None:
        return ""

    text = str(value).strip()

    if text.lower() in {"nan", "none", "null"}:
        return ""

    return text


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


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
    text = text.replace("–", "-").replace("—", "-")
    text = text.replace("_", " ")
    text = text.replace("-", " ")
    text = " ".join(text.split())
    return text


def compact(value: Any) -> str:
    text = normalize_text(value)
    return re.sub(r"[^a-z0-9]", "", text)


def contains_word(text: str, word: str) -> bool:
    pattern = r"\b" + re.escape(word) + r"\b"
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


# Outcome normalization

def normalize_outcome_core(value: Any) -> str:
    text = normalize_text(value)
    padded = f" {text} "

    if "amyotrophic lateral sclerosis" in text or contains_word(padded, "als"):
        return "amyotrophic lateral sclerosis"

    if "asthma" in text:
        return "asthma"

    if "acute kidney injury" in text or contains_word(text, "aki"):
        return "acute kidney injury"

    if "alzheimer" in text:
        return "alzheimer disease"

    if "vascular dementia" in text:
        return "vascular dementia"

    if "dementia" in text:
        return "dementia"

    if "angina" in text:
        return "angina pectoris"

    if "lung squamous cell carcinoma" in text or (
        "squamous" in text and "lung" in text
    ):
        return "lung squamous cell carcinoma"

    if "adenocarcinoma" in text and "lung" in text:
        return "lung adenocarcinoma"

    if "adenocarcinoma" in text:
        return "adenocarcinoma"

    if "lung cancer" in text:
        if "female" in text:
            return "female total lung cancer"
        return "lung cancer"

    if "spontaneous abortion" in text:
        return "spontaneous abortion"

    if "pregnancy loss" in text or "fetal loss" in text or "miscarriage" in text:
        return "spontaneous abortion"

    return text


def infer_outcome_type(outcome_core: str, original_mention: str, evidence: str) -> str:
    text = normalize_text(" ".join([outcome_core, original_mention, evidence]))

    if "hospital admission" in text or "admission" in text:
        return "hospitalization"

    if "diagnosis" in text or "diagnosed" in text:
        return "diagnosis"

    if "incidence" in text or "incident" in text:
        return "incidence"

    if "risk" in text:
        return "risk"

    if "mortality" in text or "death" in text:
        return "mortality"

    if "loss" in text or "abortion" in text or "miscarriage" in text:
        return "pregnancy_outcome"

    return "disease"


def infer_outcome_category(outcome_core: str, original_mention: str) -> str:
    text = normalize_text(" ".join([outcome_core, original_mention]))

    if "asthma" in text or "respiratory" in text:
        return "respiratory_disease"

    if (
        "amyotrophic lateral sclerosis" in text
        or "alzheimer" in text
        or "dementia" in text
        or contains_word(text, "als")
    ):
        return "neurodegenerative_disease"

    if "kidney" in text or "renal" in text:
        return "renal_disease"

    if "angina" in text or "cardiovascular" in text or "ischemic" in text:
        return "cardiovascular_disease"

    if "cancer" in text or "carcinoma" in text or "adenocarcinoma" in text:
        return "cancer"

    if "abortion" in text or "pregnancy loss" in text or "miscarriage" in text:
        return "reproductive_outcome"

    return "health_outcome"


def infer_study_design(evidence: str, model_value: str = "") -> str:
    model_value = safe_str(model_value)

    if model_value:
        return model_value

    text = normalize_text(evidence)

    if "mendelian randomization" in text or " mr " in f" {text} ":
        return "Mendelian randomization"

    if "nested case control" in text or "case control" in text:
        return "nested case-control"

    if "cohort" in text:
        return "cohort"

    if "cross sectional" in text or "cross-sectional" in text:
        return "cross-sectional"

    if "time series" in text:
        return "time-series"

    if "case crossover" in text or "case-crossover" in text:
        return "case-crossover"

    return ""


def infer_population_group(evidence: str, model_value: str = "") -> str:
    model_value = safe_str(model_value)

    if model_value:
        return model_value

    text = normalize_text(evidence)

    if "children" in text or "child" in text:
        return "children"

    if "pregnant women" in text:
        return "pregnant women"

    if "women" in text or "female" in text:
        return "women"

    if "men" in text or "male" in text:
        return "men"

    if "patients" in text:
        return "patients"

    if "participants" in text or "subjects" in text:
        return "study subjects"

    return "study subjects"


def infer_is_human_study(evidence: str, model_value: Any = None) -> bool:
    if model_value is not None and safe_str(model_value):
        return safe_bool(model_value, default=True)

    text = normalize_text(evidence)

    non_human_terms = [
        "mice",
        "mouse",
        "rats",
        "rat model",
        "murine",
        "zebrafish",
        "cell line",
        "in vitro",
    ]

    if any(term in text for term in non_human_terms):
        return False

    human_terms = [
        "children",
        "child",
        "patients",
        "participants",
        "subjects",
        "women",
        "men",
        "pregnant",
        "hospital",
        "cohort",
        "case control",
        "diagnosis",
        "admission",
    ]

    if any(term in text for term in human_terms):
        return True

    # Project prototype is focused on human epidemiological CTD exposure studies.
    return True


def infer_outcome_role(
    outcome_core: str,
    original_mention: str,
    evidence: str,
    model_value: str = "",
) -> str:
    model_value = safe_str(model_value)

    if model_value in {
        "primary_outcome",
        "endpoint_variant",
        "case_definition_component",
        "secondary_outcome",
        "ambiguous",
    }:
        return model_value

    text = normalize_text(" ".join([outcome_core, original_mention, evidence]))

    # Case definition components are not independent final outcomes.
    if (
        "cases were defined" in text
        or "case was defined" in text
        or "case definition" in text
        or "defined as children with" in text
        or "minimum of" in text and "hospital admission" in text
        or "icd" in text and "defined" in text
    ):
        return "case_definition_component"

    if "incidence" in text or "incident" in text:
        return "endpoint_variant"

    # Risk is usually a final analytical endpoint, but still linked to same core disease.
    if "risk of" in text:
        return "primary_outcome"

    return "primary_outcome"


def keep_outcome_for_final_analysis(outcome_role: str, is_human_study: bool) -> bool:
    if not is_human_study:
        return False

    if outcome_role == "case_definition_component":
        return False

    return outcome_role in {
        "primary_outcome",
        "endpoint_variant",
        "secondary_outcome",
        "ambiguous",
    }


def is_gene_or_mechanism_like(original_mention: str, evidence: str) -> bool:
    text = normalize_text(" ".join([original_mention, evidence]))

    if any(term in text for term in GENE_OR_MECHANISM_TERMS):
        if not any(
            disease_term in text
            for disease_term in [
                "asthma",
                "amyotrophic lateral sclerosis",
                "als",
                "alzheimer",
                "dementia",
                "kidney injury",
                "angina",
                "cancer",
                "abortion",
                "pregnancy loss",
            ]
        ):
            return True

    return False


# Prompt

def format_previous_pollutants_for_prompt(pollutant_payload: dict[str, Any]) -> str:
    pollutants = safe_list(pollutant_payload.get("pollutants_found"))

    if not pollutants:
        return "No previous pollutants available."

    lines = []

    for item in pollutants[:20]:
        specific = safe_str(item.get("pollutant_specific"))
        role = safe_str(item.get("pollutant_role"))
        lines.append(f"- {specific} ({role})")

    return "\n".join(lines)


def build_outcome_prompt(
    pmid: str,
    document_text: str,
    previous_pollutants_text: str = "",
) -> list[dict[str, str]]:
    system_prompt = """
You are a scientific information extraction agent.

Task:
Extract unique human health outcomes/endpoints explicitly mentioned in the document.

Rules:
- Return ONE item per unique health outcome/end point.
- Do NOT extract pollutants as outcomes.
- Do NOT extract genes, proteins, SNPs, pathways, mechanisms, or biomarkers as outcomes.
- Do NOT extract statistical measures as outcomes.
- Include clinical diseases and epidemiological endpoints.
- Include endpoint variants such as incidence/risk when reported separately.
- Mark pure case-definition components when the text only defines cases.
- Keep evidence_sentence short.
- Before listing outcomes_found, think step by step in the "reasoning" field: identify candidate outcome mentions, check each against the rules above (not a pollutant, not a gene/mechanism, not a pure statistic), and note why any candidate was excluded. Keep it concise (2-5 short sentences).
- Return only valid JSON.
- No markdown.
- No code fences.
""".strip()

    user_prompt = f"""
PMID: {pmid}

Previously extracted pollutants/exposures:
{previous_pollutants_text}

Return ONLY this compact JSON structure:

{{
  "reasoning": "brief step-by-step notes on candidate outcomes and inclusion/exclusion decisions",
  "outcomes_found": [
    {{
      "outcome_original_mention": "exact health outcome mention",
      "evidence_sentence": "short supporting sentence",
      "source_section": "section name if available",
      "population_group": "children | adults | women | patients | study subjects | etc.",
      "study_design": "cohort | nested case-control | Mendelian randomization | etc.",
      "outcome_role": "primary_outcome | endpoint_variant | case_definition_component | secondary_outcome | ambiguous",
      "is_human_study": true,
      "confidence": 0.95
    }}
  ],
  "warnings": [],
  "errors": []
}}

Expected examples:
- asthma diagnosis
- asthma
- amyotrophic lateral sclerosis
- incidence of ALS
- risk of ALS
- acute kidney injury
- Alzheimer disease
- angina pectoris
- lung cancer
- spontaneous abortion

Document outcome-focused context:
{document_text}
""".strip()

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


# Normalization and deduplication

def normalize_outcome_item(item: dict[str, Any]) -> dict[str, Any] | None:
    original = safe_str(item.get("outcome_original_mention"))

    if not original:
        original = safe_str(item.get("outcome_normalized")) or safe_str(
            item.get("outcome_core")
        )

    evidence = safe_str(item.get("evidence_sentence"))

    if is_gene_or_mechanism_like(original, evidence):
        return None

    outcome_core = normalize_outcome_core(original)

    if not outcome_core:
        return None

    population_group = infer_population_group(
        evidence=evidence,
        model_value=safe_str(item.get("population_group")),
    )

    study_design = infer_study_design(
        evidence=evidence,
        model_value=safe_str(item.get("study_design")),
    )

    is_human_study = infer_is_human_study(
        evidence=evidence,
        model_value=item.get("is_human_study"),
    )

    outcome_role = infer_outcome_role(
        outcome_core=outcome_core,
        original_mention=original,
        evidence=evidence,
        model_value=safe_str(item.get("outcome_role")),
    )

    outcome_type = infer_outcome_type(
        outcome_core=outcome_core,
        original_mention=original,
        evidence=evidence,
    )

    outcome_category = infer_outcome_category(
        outcome_core=outcome_core,
        original_mention=original,
    )

    keep_final = keep_outcome_for_final_analysis(
        outcome_role=outcome_role,
        is_human_study=is_human_study,
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

    return {
        "outcome_original_mention": original,
        "outcome_normalized": original,
        "outcome_core": outcome_core,
        "outcome_type": outcome_type,
        "outcome_category": outcome_category,
        "population_group": population_group,
        "is_human_study": is_human_study,
        "study_design": study_design,
        "outcome_role": outcome_role,
        "keep_for_final_analysis": keep_final,
        "role_reason": build_role_reason(outcome_core, outcome_role, keep_final),
        "evidence_sentence": evidence,
        "source_section": safe_str(item.get("source_section")),
        "source_type": source_type,
        "confidence": confidence,
    }


def build_role_reason(
    outcome_core: str,
    outcome_role: str,
    keep_final: bool,
) -> str:
    if outcome_role == "case_definition_component":
        return (
            f"Extracted as a case definition component for {outcome_core}; "
            "not treated as an independent final association."
        )

    if outcome_role == "endpoint_variant":
        return f"Retained as endpoint variant linked to core outcome: {outcome_core}."

    if outcome_role == "primary_outcome":
        return f"Selected as canonical primary outcome for core outcome: {outcome_core}."

    if keep_final:
        return f"Retained for final analysis as outcome: {outcome_core}."

    return f"Not retained for final analysis: {outcome_core}."


def outcome_priority(item: dict[str, Any]) -> tuple[int, float, int]:
    role = safe_str(item.get("outcome_role"))

    role_priority = {
        "primary_outcome": 5,
        "endpoint_variant": 4,
        "secondary_outcome": 3,
        "ambiguous": 2,
        "case_definition_component": 1,
    }.get(role, 0)

    confidence = safe_float(item.get("confidence"), default=0.0)
    evidence_len = len(safe_str(item.get("evidence_sentence")))

    return role_priority, confidence, evidence_len


def outcome_dedup_key(item: dict[str, Any]) -> str:
    core = normalize_outcome_core(item.get("outcome_core"))
    role = safe_str(item.get("outcome_role"))

    # Keep endpoint variants separate from primary outcomes.
    if role == "endpoint_variant":
        mention = normalize_text(item.get("outcome_original_mention"))

        if "incidence" in mention or "incident" in mention:
            return f"{core}|incidence"

        if "risk" in mention:
            return f"{core}|risk"

        return f"{core}|endpoint_variant"

    if role == "case_definition_component":
        return f"{core}|case_definition_component"

    return f"{core}|primary"


def deduplicate_outcomes(
    outcomes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}

    for item in outcomes:
        key = outcome_dedup_key(item)

        if not key:
            continue

        if key not in by_key:
            by_key[key] = item
            continue

        existing = by_key[key]

        if outcome_priority(item) > outcome_priority(existing):
            by_key[key] = item

    return list(by_key.values())


def remove_redundant_endpoint_variants(
    outcomes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Remove analytical variants that duplicate a primary outcome."""
    cores_with_primary = {
        safe_str(item.get("outcome_core"))
        for item in outcomes
        if item.get("outcome_role") == "primary_outcome"
    }

    endpoint_variant_allowed_cores = {
        "amyotrophic lateral sclerosis",
    }

    filtered = []

    for item in outcomes:
        core = safe_str(item.get("outcome_core"))
        role = safe_str(item.get("outcome_role"))
        mention = normalize_text(item.get("outcome_original_mention"))

        if (
            role == "endpoint_variant"
            and core in cores_with_primary
            and core not in endpoint_variant_allowed_cores
            and (
                "risk of" in mention
                or "incidence of" in mention
                or "incident" in mention
            )
        ):
            continue

        filtered.append(item)

    return filtered

def normalize_outcome_payload(payload: dict[str, Any]) -> dict[str, Any]:
    raw_outcomes = safe_list(payload.get("outcomes_found"))

    outcomes = []

    for item in raw_outcomes:
        if not isinstance(item, dict):
            continue

        normalized = normalize_outcome_item(item)

        if normalized is None:
            continue

        outcomes.append(normalized)

    outcomes = deduplicate_outcomes(outcomes)
    outcomes = remove_redundant_endpoint_variants(outcomes)

    warnings = safe_list(payload.get("warnings"))
    errors = safe_list(payload.get("errors"))

    return {
        "outcomes_found": outcomes,
        "warnings": warnings,
        "errors": errors,
    }


# Public API

def run_outcome_extractor_for_pmid(
    pmid: str,
    segmented_document_path: Path,
    pollutant_json_path: Path | None,
    output_json: Path,
    output_state_json: Path,
    raw_response_path: Path,
    repair_response_path: Path,
    reasoning_dir: Path,
    client: Any,
    model: str | None = None,
    max_output_tokens: int = 2500,
) -> dict[str, Any]:
    segmented_payload = read_json(segmented_document_path)

    pollutant_payload = {}

    if pollutant_json_path is not None:
        pollutant_payload = read_json_or_empty(pollutant_json_path)

    previous_pollutants_text = format_previous_pollutants_for_prompt(
        pollutant_payload
    )

    title, abstract = extract_title_and_abstract(segmented_payload)
    chunks = extract_document_chunks(segmented_payload)

    combined_outcomes: list[Any] = []
    combined_warnings: list[Any] = []
    combined_errors: list[Any] = []
    reasoning_entries: list[dict[str, Any]] = []
    raw_response_parts: list[str] = []
    repair_used_any = False

    for chunk in chunks:
        chunk_text = build_chunk_text_with_context(title, abstract, chunk)

        messages = build_outcome_prompt(
            pmid=pmid,
            document_text=chunk_text,
            previous_pollutants_text=previous_pollutants_text,
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

        combined_outcomes.extend(safe_list(chunk_payload.get("outcomes_found")))
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

    normalized_payload = normalize_outcome_payload(
        {
            "outcomes_found": combined_outcomes,
            "warnings": combined_warnings,
            "errors": combined_errors,
        }
    )

    outcomes_found = normalized_payload["outcomes_found"]
    warnings = normalized_payload["warnings"]
    errors = normalized_payload["errors"]

    reasoning_path = write_reasoning_file(
        reasoning_dir=reasoning_dir,
        pmid=pmid,
        agent_name="outcome_extractor",
        entries=reasoning_entries,
    )

    output_payload = {
        "pmid": pmid,
        "created_at": now_iso(),
        "provider": "ILAAS",
        "base_url": settings.ilaas_base_url,
        "model": model or settings.ilaas_model,
        "agent": "outcome_extractor",
        "outcomes_found": outcomes_found,
        "warnings": warnings,
        "errors": errors,
        "metadata": {
            "segmented_document_path": str(segmented_document_path),
            "pollutant_json_path": str(pollutant_json_path) if pollutant_json_path else "",
            "previous_pollutants_loaded": len(
                safe_list(pollutant_payload.get("pollutants_found"))
            ),
            "raw_response_path": str(raw_response_path),
            "repair_response_path": str(repair_response_path),
            "reasoning_path": reasoning_path,
            "json_repair_used": repair_used_any,
            "chunks_processed": len(chunks),
            "n_outcomes_found": len(outcomes_found),
        },
    }

    state_payload = {
        "pmid": pmid,
        "outcome_extractor": output_payload,
        "outcomes_found": outcomes_found,
        "warnings": warnings,
        "errors": errors,
        "metadata": output_payload["metadata"],
    }

    write_json(output_json, output_payload)
    write_json(output_state_json, state_payload)

    return output_payload
