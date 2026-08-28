"""Build flat pollutant-outcome associations without an LLM call."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from src.io.csv_io import write_csv_rows
from src.io.json_io import read_json, write_json


# CSV output columns

CSV_COLUMNS = [
    "association_id",
    "pmid",

    "pollutant_general",
    "pollutant_specific",
    "pollutant_original_mention",
    "is_project_target",
    "pollutant_role",

    "outcome_core",
    "outcome_normalized",
    "outcome_role",
    "outcome_category",
    "population_group",
    "is_human_study",

    "measure_type",
    "measure_name",
    "effect_value",
    "effect_value_numeric",
    "ci_lower",
    "ci_upper",
    "ci_level",
    "p_value",
    "statistical_significance",
    "effect_direction",

    "exposure_increment",
    "exposure_increment_value",
    "exposure_increment_unit",

    "analysis_method",
    "adjustment_status",
    "measure_role",

    "association_role",
    "keep_for_database",
    "include_in_main_project_analysis",

    "evidence_sentence",
    "source_section",
    "source_type",
    "effect_extractor_confidence",
    "pollutant_match_confidence",
    "outcome_match_confidence",
]


# Generic helpers

def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def safe_str(value: Any) -> str:
    if value is None:
        return ""

    value = str(value)

    if value.lower() == "nan":
        return ""

    return value.strip()


def parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value

    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def normalize_text_key(value: str) -> str:
    value = safe_str(value).lower()
    value = value.replace("₂", "2").replace("₃", "3").replace("ₓ", "x")
    value = value.replace("<sub>2</sub>", "2")
    value = value.replace("<sub>3</sub>", "3")
    value = value.replace("<sub>x</sub>", "x")
    value = value.replace("<sub>X</sub>", "x")
    value = value.replace("μ", "µ")
    value = value.replace("–", "-").replace("—", "-")
    value = value.replace("_", " ")
    value = value.replace("-", " ")
    value = " ".join(value.split())
    return value


def normalize_compact(value: str) -> str:
    value = normalize_text_key(value)
    value = value.replace(" ", "")
    value = value.replace(".", "")
    return value


def normalize_pollutant_key(value: str) -> str:
    text = normalize_compact(value)

    aliases = {
        "pm25": "pm25",
        "pm2.5": "pm25",
        "particulatematter25": "pm25",
        "pm10": "pm10",
        "pm1": "pm1",
        "particulatematter": "pm",
        "ultrafineparticles": "ufp",
        "ufp": "ufp",

        "nitricoxide": "no",
        "no": "no",
        "nitrogendioxide": "no2",
        "no2": "no2",
        "nitrogenoxides": "nox",
        "nox": "nox",

        "ozone": "o3",
        "o3": "o3",

        "carbonmonoxide": "co",
        "co": "co",

        "sulfurdioxide": "so2",
        "sulphurdioxide": "so2",
        "so2": "so2",

        "blackcarbon": "blackcarbon",
        "soot": "soot",
        "woodsmoke": "woodsmoke",

        "airpollutants": "airpollutants",
        "trafficrelatedpollutants": "trafficrelatedpollutants",
        "trafficrelatedpollution": "trafficrelatedpollution",

        "h2s": "h2s",
        "hydrogensulfide": "h2s",
    }

    return aliases.get(text, text)


def normalize_outcome_core(value: str) -> str:
    text = normalize_text_key(value)

    if "asthma" in text:
        return "asthma"

    if "amyotrophic lateral sclerosis" in text or " als " in f" {text} ":
        return "amyotrophic lateral sclerosis"

    if "alzheimer" in text:
        return "alzheimer disease"

    if "acute kidney injury" in text:
        return "acute kidney injury"

    if "adenocarcinoma" in text and "lung" in text:
        return "lung adenocarcinoma"

    if "angina" in text:
        return "angina pectoris"

    if "spontaneous abortion" in text or "abortion" in text:
        return "spontaneous abortion"

    return text


# Fallback classifications

def compute_is_project_target_pollutant(
    pollutant_general: str,
    pollutant_specific: str,
) -> bool:
    g = normalize_pollutant_key(pollutant_general)
    s = normalize_pollutant_key(pollutant_specific)

    target_terms = {
        "pm",
        "pm25",
        "pm10",
        "pm1",
        "ufp",
        "no",
        "no2",
        "o3",
    }

    return g in target_terms or s in target_terms


def infer_pollutant_role(
    pollutant_general: str,
    pollutant_specific: str,
    is_project_target: bool,
) -> str:
    if is_project_target:
        return "target"

    key = normalize_pollutant_key(pollutant_specific or pollutant_general)

    if key in {"woodsmoke", "trafficrelatedpollutants", "trafficrelatedpollution"}:
        return "source_marker"

    if key in {"blackcarbon", "soot"}:
        return "secondary"

    if key in {"co", "so2", "nox", "airpollutants", "h2s"}:
        return "contextual"

    return "ambiguous"


def fallback_pollutant_from_measure(mention: str) -> dict[str, Any]:
    mention = safe_str(mention)
    key = normalize_pollutant_key(mention)

    specific_map = {
        "pm25": ("PM", "PM2.5"),
        "pm10": ("PM", "PM10"),
        "pm1": ("PM", "PM1"),
        "pm": ("PM", "particulate matter"),
        "ufp": ("PM", "ultrafine particles"),

        "no": ("NO", "NO"),
        "no2": ("NO2", "NO2"),
        "nox": ("NOx", "NOx"),
        "o3": ("O3", "O3"),

        "co": ("CO", "CO"),
        "so2": ("SO2", "SO2"),
        "blackcarbon": ("black_carbon", "black carbon"),
        "soot": ("soot", "soot"),
        "woodsmoke": ("woodsmoke", "woodsmoke"),
        "trafficrelatedpollution": (
            "traffic_related_pollution",
            "traffic-related pollution",
        ),
        "trafficrelatedpollutants": (
            "traffic_related_pollution",
            "traffic-related pollutants",
        ),
        "h2s": ("H2S", "H2S"),
    }

    pollutant_general, pollutant_specific = specific_map.get(
        key,
        ("other", mention),
    )

    is_project_target = compute_is_project_target_pollutant(
        pollutant_general,
        pollutant_specific,
    )

    pollutant_role = infer_pollutant_role(
        pollutant_general,
        pollutant_specific,
        is_project_target,
    )

    return {
        "pollutant_general": pollutant_general,
        "pollutant_specific": pollutant_specific,
        "pollutant_original_mention": mention,
        "is_project_target": is_project_target,
        "pollutant_role": pollutant_role,
        "keep_for_final_analysis": is_project_target,
        "match_source": "fallback_from_effect_measure",
        "match_confidence": 0.6,
    }


def fallback_outcome_from_measure(mention: str) -> dict[str, Any]:
    mention = safe_str(mention)
    core = normalize_outcome_core(mention)

    return {
        "outcome_normalized": mention or core,
        "outcome_core": core,
        "outcome_role": "primary_outcome",
        "outcome_category": "",
        "population_group": "",
        "is_human_study": True,
        "keep_for_final_analysis": True,
        "match_source": "fallback_from_effect_measure",
        "match_confidence": 0.6,
    }


# Matching

def pollutant_candidate_keys(item: dict[str, Any]) -> set[str]:
    keys = set()

    for field in [
        "pollutant_specific",
        "pollutant_general",
        "pollutant_original_mention",
    ]:
        value = safe_str(item.get(field))
        if value:
            keys.add(normalize_pollutant_key(value))

    return {key for key in keys if key}


def find_best_pollutant_match(
    measure_pollutant: str,
    pollutants_found: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    mention = safe_str(measure_pollutant)
    mention_key = normalize_pollutant_key(mention)

    if not mention_key:
        fallback = fallback_pollutant_from_measure("")
        warning = {
            "warning_type": "missing_pollutant_mention",
            "message": (
                "Effect measure has empty pollutant_mention; "
                "fallback pollutant is ambiguous."
            ),
        }
        return fallback, warning

    best_item = None
    best_score = -1

    for item in pollutants_found:
        keys = pollutant_candidate_keys(item)

        score = 0

        if mention_key in keys:
            score += 100

        for key in keys:
            if key and (mention_key in key or key in mention_key):
                score += 50

        measure_fallback = fallback_pollutant_from_measure(mention)
        measure_general_key = normalize_pollutant_key(
            measure_fallback.get("pollutant_general", "")
        )
        item_general_key = normalize_pollutant_key(item.get("pollutant_general", ""))

        if measure_general_key and measure_general_key == item_general_key:
            score += 20

        if score > best_score:
            best_score = score
            best_item = item

    if best_item is not None and best_score >= 50:
        matched = {
            "pollutant_general": safe_str(best_item.get("pollutant_general")),
            "pollutant_specific": safe_str(best_item.get("pollutant_specific")),
            "pollutant_original_mention": safe_str(
                best_item.get("pollutant_original_mention")
            ),
            "is_project_target": parse_bool(best_item.get("is_project_target")),
            "pollutant_role": safe_str(best_item.get("pollutant_role")),
            "keep_for_final_analysis": parse_bool(
                best_item.get("keep_for_final_analysis")
            ),
            "match_source": "pollutant_extractor",
            "match_confidence": min(1.0, best_score / 100),
        }

        return matched, None

    fallback = fallback_pollutant_from_measure(mention)
    warning = {
        "warning_type": "pollutant_match_fallback",
        "message": (
            f"No confident pollutant_extractor match found for effect pollutant "
            f"mention '{mention}'. Fallback classification was used."
        ),
    }

    return fallback, warning


def outcome_candidate_keys(item: dict[str, Any]) -> set[str]:
    keys = set()

    for field in [
        "outcome_core",
        "outcome_normalized",
        "outcome_original_mention",
    ]:
        value = safe_str(item.get(field))
        if value:
            keys.add(normalize_outcome_core(value))

    return {key for key in keys if key}


def find_best_outcome_match(
    measure_outcome: str,
    outcomes_found: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    mention = safe_str(measure_outcome)
    mention_core = normalize_outcome_core(mention)

    if not mention_core:
        fallback = fallback_outcome_from_measure("")
        warning = {
            "warning_type": "missing_outcome_mention",
            "message": (
                "Effect measure has empty outcome_mention; "
                "fallback outcome is ambiguous."
            ),
        }
        return fallback, warning

    eligible = [
        item for item in outcomes_found
        if item.get("outcome_role") != "case_definition_component"
    ]

    best_item = None
    best_score = -1

    for item in eligible:
        keys = outcome_candidate_keys(item)

        score = 0

        if mention_core in keys:
            score += 100

        for key in keys:
            if key and (mention_core in key or key in mention_core):
                score += 50

        if parse_bool(item.get("keep_for_final_analysis")):
            score += 20

        if item.get("outcome_role") == "primary_outcome":
            score += 15

        if item.get("outcome_role") == "endpoint_variant":
            score += 5

        if score > best_score:
            best_score = score
            best_item = item

    if best_item is not None and best_score >= 50:
        matched = {
            "outcome_normalized": safe_str(best_item.get("outcome_normalized")),
            "outcome_core": safe_str(best_item.get("outcome_core")),
            "outcome_role": safe_str(best_item.get("outcome_role")),
            "outcome_category": safe_str(best_item.get("outcome_category")),
            "population_group": safe_str(best_item.get("population_group")),
            "is_human_study": parse_bool(best_item.get("is_human_study")),
            "keep_for_final_analysis": parse_bool(
                best_item.get("keep_for_final_analysis")
            ),
            "match_source": "outcome_extractor",
            "match_confidence": min(1.0, best_score / 100),
        }

        return matched, None

    fallback = fallback_outcome_from_measure(mention)
    warning = {
        "warning_type": "outcome_match_fallback",
        "message": (
            f"No confident outcome_extractor match found for effect outcome "
            f"mention '{mention}'. Fallback classification was used."
        ),
    }

    return fallback, warning


# Association construction

def make_association_id(
    pmid: str,
    pollutant_specific: str,
    outcome_core: str,
    measure_type: str,
    effect_value: str,
    ci_lower: str,
    ci_upper: str,
    p_value: str,
    analysis_method: str,
) -> str:
    key = "|".join(
        [
            pmid,
            normalize_pollutant_key(pollutant_specific),
            normalize_outcome_core(outcome_core),
            safe_str(measure_type),
            safe_str(effect_value),
            safe_str(ci_lower),
            safe_str(ci_upper),
            safe_str(p_value),
            normalize_text_key(analysis_method),
        ]
    )

    digest = hashlib.md5(key.encode("utf-8")).hexdigest()[:12]

    return f"assoc_{pmid}_{digest}"


def compute_include_in_main_project_analysis(
    pollutant: dict[str, Any],
    outcome: dict[str, Any],
    effect: dict[str, Any],
) -> bool:
    return (
        parse_bool(effect.get("keep_for_association_builder"))
        and parse_bool(outcome.get("keep_for_final_analysis"))
        and parse_bool(pollutant.get("is_project_target"))
    )


def compute_association_role(
    pollutant: dict[str, Any],
    outcome: dict[str, Any],
    effect: dict[str, Any],
) -> str:
    if not parse_bool(effect.get("keep_for_association_builder")):
        return "excluded_effect"

    if not parse_bool(outcome.get("keep_for_final_analysis")):
        return "excluded_outcome"

    if parse_bool(pollutant.get("is_project_target")):
        return "main_project_target_association"

    return "contextual_direct_association"


def build_association_from_effect(
    pmid: str,
    effect: dict[str, Any],
    pollutants_found: list[dict[str, Any]],
    outcomes_found: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    warnings: list[dict[str, Any]] = []

    if not parse_bool(effect.get("keep_for_association_builder")):
        return None, warnings

    pollutant, pollutant_warning = find_best_pollutant_match(
        measure_pollutant=safe_str(effect.get("pollutant_mention")),
        pollutants_found=pollutants_found,
    )

    if pollutant_warning:
        warnings.append(pollutant_warning)

    outcome, outcome_warning = find_best_outcome_match(
        measure_outcome=safe_str(effect.get("outcome_mention")),
        outcomes_found=outcomes_found,
    )

    if outcome_warning:
        warnings.append(outcome_warning)

    association_id = make_association_id(
        pmid=pmid,
        pollutant_specific=pollutant.get("pollutant_specific", ""),
        outcome_core=outcome.get("outcome_core", ""),
        measure_type=effect.get("measure_type", ""),
        effect_value=effect.get("effect_value", ""),
        ci_lower=effect.get("ci_lower", ""),
        ci_upper=effect.get("ci_upper", ""),
        p_value=effect.get("p_value", ""),
        analysis_method=effect.get("analysis_method", ""),
    )

    include_main = compute_include_in_main_project_analysis(
        pollutant=pollutant,
        outcome=outcome,
        effect=effect,
    )

    association_role = compute_association_role(
        pollutant=pollutant,
        outcome=outcome,
        effect=effect,
    )

    association = {
        "association_id": association_id,
        "pmid": pmid,
        "created_at": now_iso(),

        "pollutant": pollutant,
        "outcome": outcome,

        "effect_measure": {
            "measure_type": safe_str(effect.get("measure_type")),
            "measure_name": safe_str(effect.get("measure_name")),
            "measure_family": safe_str(effect.get("measure_family")),
            "effect_value": safe_str(effect.get("effect_value")),
            "effect_value_numeric": effect.get("effect_value_numeric"),
            "ci_lower": safe_str(effect.get("ci_lower")),
            "ci_lower_numeric": effect.get("ci_lower_numeric"),
            "ci_upper": safe_str(effect.get("ci_upper")),
            "ci_upper_numeric": effect.get("ci_upper_numeric"),
            "ci_level": safe_str(effect.get("ci_level")),
            "p_value": safe_str(effect.get("p_value")),
            "statistical_significance": safe_str(
                effect.get("statistical_significance")
            ),
            "effect_direction": safe_str(effect.get("effect_direction")),
        },

        "exposure": {
            "exposure_increment": safe_str(effect.get("exposure_increment")),
            "exposure_increment_value": safe_str(
                effect.get("exposure_increment_value")
            ),
            "exposure_increment_value_numeric": effect.get(
                "exposure_increment_value_numeric"
            ),
            "exposure_increment_unit": safe_str(
                effect.get("exposure_increment_unit")
            ),
        },

        "analysis": {
            "analysis_method": safe_str(effect.get("analysis_method")),
            "adjustment_status": safe_str(effect.get("adjustment_status")),
            "measure_role": safe_str(effect.get("measure_role")),
        },

        "evidence": {
            "evidence_sentence": safe_str(effect.get("evidence_sentence")),
            "source_section": safe_str(effect.get("source_section")),
            "source_type": safe_str(effect.get("source_type")),
            "effect_extractor_confidence": effect.get("confidence"),
            "pollutant_match_confidence": pollutant.get("match_confidence"),
            "outcome_match_confidence": outcome.get("match_confidence"),
        },

        "classification": {
            "association_type": "direct_pollutant_health_outcome",
            "association_role": association_role,
            "keep_for_database": True,
            "include_in_main_project_analysis": include_main,
            "non_significant_results_policy": "kept_if_numeric_effect_available",
        },
    }

    return association, warnings


def deduplicate_associations(
    associations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}

    for assoc in associations:
        assoc_id = assoc["association_id"]

        if assoc_id not in by_id:
            by_id[assoc_id] = assoc
            continue

        existing = by_id[assoc_id]

        existing_conf = float(
            existing.get("evidence", {}).get("effect_extractor_confidence") or 0
        )
        new_conf = float(
            assoc.get("evidence", {}).get("effect_extractor_confidence") or 0
        )

        if new_conf > existing_conf:
            by_id[assoc_id] = assoc

    return list(by_id.values())


# CSV flattening

def flatten_association_for_csv(assoc: dict[str, Any]) -> dict[str, Any]:
    pollutant = assoc.get("pollutant", {})
    outcome = assoc.get("outcome", {})
    effect = assoc.get("effect_measure", {})
    exposure = assoc.get("exposure", {})
    analysis = assoc.get("analysis", {})
    evidence = assoc.get("evidence", {})
    classification = assoc.get("classification", {})

    return {
        "association_id": assoc.get("association_id"),
        "pmid": assoc.get("pmid"),

        "pollutant_general": pollutant.get("pollutant_general"),
        "pollutant_specific": pollutant.get("pollutant_specific"),
        "pollutant_original_mention": pollutant.get("pollutant_original_mention"),
        "is_project_target": pollutant.get("is_project_target"),
        "pollutant_role": pollutant.get("pollutant_role"),

        "outcome_core": outcome.get("outcome_core"),
        "outcome_normalized": outcome.get("outcome_normalized"),
        "outcome_role": outcome.get("outcome_role"),
        "outcome_category": outcome.get("outcome_category"),
        "population_group": outcome.get("population_group"),
        "is_human_study": outcome.get("is_human_study"),

        "measure_type": effect.get("measure_type"),
        "measure_name": effect.get("measure_name"),
        "effect_value": effect.get("effect_value"),
        "effect_value_numeric": effect.get("effect_value_numeric"),
        "ci_lower": effect.get("ci_lower"),
        "ci_upper": effect.get("ci_upper"),
        "ci_level": effect.get("ci_level"),
        "p_value": effect.get("p_value"),
        "statistical_significance": effect.get("statistical_significance"),
        "effect_direction": effect.get("effect_direction"),

        "exposure_increment": exposure.get("exposure_increment"),
        "exposure_increment_value": exposure.get("exposure_increment_value"),
        "exposure_increment_unit": exposure.get("exposure_increment_unit"),

        "analysis_method": analysis.get("analysis_method"),
        "adjustment_status": analysis.get("adjustment_status"),
        "measure_role": analysis.get("measure_role"),

        "association_role": classification.get("association_role"),
        "keep_for_database": classification.get("keep_for_database"),
        "include_in_main_project_analysis": classification.get(
            "include_in_main_project_analysis"
        ),

        "evidence_sentence": evidence.get("evidence_sentence"),
        "source_section": evidence.get("source_section"),
        "source_type": evidence.get("source_type"),
        "effect_extractor_confidence": evidence.get("effect_extractor_confidence"),
        "pollutant_match_confidence": evidence.get("pollutant_match_confidence"),
        "outcome_match_confidence": evidence.get("outcome_match_confidence"),
    }


# Public API

def build_associations(
    pmid: str,
    pollutants_found: list[dict[str, Any]],
    outcomes_found: list[dict[str, Any]],
    effect_measures_found: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    associations: list[dict[str, Any]] = []

    kept_effects = [
        effect for effect in effect_measures_found
        if parse_bool(effect.get("keep_for_association_builder"))
    ]

    for effect in kept_effects:
        association, assoc_warnings = build_association_from_effect(
            pmid=pmid,
            effect=effect,
            pollutants_found=pollutants_found,
            outcomes_found=outcomes_found,
        )

        warnings.extend(assoc_warnings)

        if association is not None:
            associations.append(association)

    associations = deduplicate_associations(associations)

    main_project_count = sum(
        parse_bool(
            assoc.get("classification", {}).get("include_in_main_project_analysis")
        )
        for assoc in associations
    )

    contextual_count = sum(
        assoc.get("classification", {}).get("association_role")
        == "contextual_direct_association"
        for assoc in associations
    )

    metadata = {
        "association_builder_status": "success",
        "association_builder_ran_at": now_iso(),
        "input_effect_measures": len(effect_measures_found),
        "input_kept_effect_measures": len(kept_effects),
        "associations_built": len(associations),
        "main_project_associations": int(main_project_count),
        "contextual_direct_associations": int(contextual_count),
        "deduplication_rule": (
            "merge only if scientific key fields are identical; "
            "analysis_method differences are preserved"
        ),
    }

    return associations, warnings, metadata


def run_association_builder_for_pmid(
    pmid: str,
    pollutant_json: Path,
    outcome_json: Path,
    effect_measure_json: Path,
    output_json: Path,
    output_csv: Path,
    output_state_json: Path,
) -> dict[str, Any]:
    pollutant_payload = read_json(pollutant_json)
    outcome_payload = read_json(outcome_json)
    effect_payload = read_json(effect_measure_json)

    pollutants_found = pollutant_payload.get("pollutants_found", [])
    outcomes_found = outcome_payload.get("outcomes_found", [])
    effect_measures_found = effect_payload.get("effect_measures_found", [])

    errors: list[dict[str, Any]] = []

    associations, warnings, metadata = build_associations(
        pmid=pmid,
        pollutants_found=pollutants_found,
        outcomes_found=outcomes_found,
        effect_measures_found=effect_measures_found,
    )

    association_payload = {
        "pmid": pmid,
        "created_at": now_iso(),
        "agent": "association_builder",
        "associations": associations,
        "warnings": warnings,
        "errors": errors,
        "metadata": {
            **metadata,
            "input_paths": {
                "pollutants": str(pollutant_json),
                "outcomes": str(outcome_json),
                "effect_measures": str(effect_measure_json),
            },
            "output_paths": {
                "associations_json": str(output_json),
                "associations_csv": str(output_csv),
                "state_json": str(output_state_json),
            },
        },
    }

    state_payload = {
        "pmid": pmid,
        "pollutants_found": pollutants_found,
        "outcomes_found": outcomes_found,
        "effect_measures_found": effect_measures_found,
        "associations": associations,
        "warnings": warnings,
        "errors": errors,
        "metadata": association_payload["metadata"],
    }

    csv_rows = [
        flatten_association_for_csv(assoc)
        for assoc in associations
    ]

    write_json(output_json, association_payload)
    write_json(output_state_json, state_payload)
    write_csv_rows(output_csv, csv_rows, fieldnames=CSV_COLUMNS)

    return association_payload