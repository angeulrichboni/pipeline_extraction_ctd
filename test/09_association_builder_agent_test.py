#!/usr/bin/env python3
"""
Quatrième agent LangGraph : association_builder.

Agent déterministe, sans appel LLM.

Entrées:
    data/prototype/agent_outputs/pollutant_extractor/{pmid}_pollutants.json
    data/prototype/agent_outputs/outcome_extractor/{pmid}_outcomes.json
    data/prototype/agent_outputs/effect_measure_extractor/{pmid}_effect_measures.json

Sorties:
    data/prototype/agent_outputs/association_builder/{pmid}_associations.json
    data/prototype/agent_outputs/association_builder/{pmid}_associations.csv
    data/prototype/agent_outputs/association_builder/{pmid}_state.json

Objectif:
    Construire une table plate d'associations scientifiques.

Règles:
    - Une association scientifique distincte = une ligne.
    - On utilise seulement les effect_measures avec keep_for_association_builder=True.
    - On conserve aussi les associations contextuelles comme CO, NOx, black carbon,
      mais on les marque comme non-cibles du projet si nécessaire.
    - On n'utilise pas les outcomes de type case_definition_component
      comme outcome final indépendant.
    - On ne fusionne pas IVW et MR-PRESSO.
    - On ne fusionne que si les champs scientifiques clés sont identiques.
"""

import argparse
import csv
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph


# ---------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------

POLLUTANT_OUT_DIR = Path("data/prototype/agent_outputs/pollutant_extractor")
OUTCOME_OUT_DIR = Path("data/prototype/agent_outputs/outcome_extractor")
EFFECT_OUT_DIR = Path("data/prototype/agent_outputs/effect_measure_extractor")

OUT_DIR = Path("data/prototype/agent_outputs/association_builder")
OUT_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------
# State
# ---------------------------------------------------------------------

class AssociationBuilderState(TypedDict, total=False):
    pmid: str

    pollutants_found: list[dict[str, Any]]
    outcomes_found: list[dict[str, Any]]
    effect_measures_found: list[dict[str, Any]]

    associations: list[dict[str, Any]]

    warnings: list[dict[str, Any]]
    errors: list[dict[str, Any]]

    metadata: dict[str, Any]


# ---------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------

def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")

    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, obj: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(obj, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_pollutants(pmid: str) -> list[dict[str, Any]]:
    path = POLLUTANT_OUT_DIR / f"{pmid}_pollutants.json"
    payload = read_json(path)
    return payload.get("pollutants_found", [])


def load_outcomes(pmid: str) -> list[dict[str, Any]]:
    path = OUTCOME_OUT_DIR / f"{pmid}_outcomes.json"
    payload = read_json(path)
    return payload.get("outcomes_found", [])


def load_effect_measures(pmid: str) -> list[dict[str, Any]]:
    path = EFFECT_OUT_DIR / f"{pmid}_effect_measures.json"
    payload = read_json(path)
    return payload.get("effect_measures_found", [])


# ---------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------

def safe_str(value: Any) -> str:
    if value is None:
        return ""

    value = str(value)

    if value.lower() == "nan":
        return ""

    return value.strip()


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
    }

    return aliases.get(text, text)


def normalize_outcome_core(value: str) -> str:
    text = normalize_text_key(value)

    if "asthma" in text:
        return "asthma"

    if "amyotrophic lateral sclerosis" in text or " als " in f" {text} ":
        return "amyotrophic lateral sclerosis"

    if "alzheimer" in text:
        return "Alzheimer disease"

    if "acute kidney injury" in text:
        return "acute kidney injury"

    if "adenocarcinoma" in text and "lung" in text:
        return "lung adenocarcinoma"

    if "angina" in text:
        return "angina pectoris"

    if "spontaneous abortion" in text or "abortion" in text:
        return "spontaneous abortion"

    return text


def parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value

    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def parse_float_or_none(value: Any) -> float | None:
    if value is None:
        return None

    text = str(value).strip()

    if not text or text.lower() in {"nan", "none", "null", "not reported"}:
        return None

    text = text.replace(",", ".")
    text = text.replace("−", "-")
    text = re.sub(r"[^0-9eE\.\-\+]", "", text)

    if not text:
        return None

    try:
        return float(text)
    except Exception:
        return None


# ---------------------------------------------------------------------
# Fallback classifications
# ---------------------------------------------------------------------

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

    key = normalize_pollutant_key(
        pollutant_specific or pollutant_general
    )

    if key in {"woodsmoke", "trafficrelatedpollutants"}:
        return "source_marker"

    if key in {"blackcarbon", "soot"}:
        return "secondary"

    if key in {"co", "so2", "nox", "airpollutants"}:
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


# ---------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------

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
    """
    Retour:
        matched_pollutant, warning_or_none
    """
    mention = safe_str(measure_pollutant)
    mention_key = normalize_pollutant_key(mention)

    if not mention_key:
        fallback = fallback_pollutant_from_measure("")
        warning = {
            "warning_type": "missing_pollutant_mention",
            "message": "Effect measure has empty pollutant_mention; fallback pollutant is ambiguous.",
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

        # Bonus si même famille.
        measure_fallback = fallback_pollutant_from_measure(mention)
        measure_general_key = normalize_pollutant_key(
            measure_fallback.get("pollutant_general", "")
        )
        item_general_key = normalize_pollutant_key(
            item.get("pollutant_general", "")
        )

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
            "message": "Effect measure has empty outcome_mention; fallback outcome is ambiguous.",
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


# ---------------------------------------------------------------------
# Association construction
# ---------------------------------------------------------------------

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
    warnings = []

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
        "created_at": datetime.now().isoformat(timespec="seconds"),

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
    """
    Fusion stricte uniquement si les champs scientifiques clés sont identiques.

    Important:
        IVW et MR-PRESSO ne fusionnent pas car analysis_method diffère.
    """
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


# ---------------------------------------------------------------------
# CSV flattening
# ---------------------------------------------------------------------

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


def flatten_association_for_csv(assoc: dict[str, Any]) -> dict[str, Any]:
    pollutant = assoc.get("pollutant", {})
    outcome = assoc.get("outcome", {})
    effect = assoc.get("effect_measure", {})
    exposure = assoc.get("exposure", {})
    analysis = assoc.get("analysis", {})
    evidence = assoc.get("evidence", {})
    classification = assoc.get("classification", {})

    row = {
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

    return row


def write_associations_csv(
    path: Path,
    associations: list[dict[str, Any]],
) -> None:
    rows = [flatten_association_for_csv(assoc) for assoc in associations]

    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


# ---------------------------------------------------------------------
# LangGraph node
# ---------------------------------------------------------------------

def association_builder_node(
    state: AssociationBuilderState,
) -> dict[str, Any]:
    pmid = state["pmid"]

    warnings = list(state.get("warnings", []))
    associations = []

    try:
        kept_effects = [
            effect for effect in state.get("effect_measures_found", [])
            if parse_bool(effect.get("keep_for_association_builder"))
        ]

        for effect in kept_effects:
            association, assoc_warnings = build_association_from_effect(
                pmid=pmid,
                effect=effect,
                pollutants_found=state.get("pollutants_found", []),
                outcomes_found=state.get("outcomes_found", []),
            )

            warnings.extend(assoc_warnings)

            if association is not None:
                associations.append(association)

        associations = deduplicate_associations(associations)

        main_project_count = sum(
            parse_bool(
                assoc.get("classification", {}).get(
                    "include_in_main_project_analysis"
                )
            )
            for assoc in associations
        )

        contextual_count = sum(
            assoc.get("classification", {}).get("association_role")
            == "contextual_direct_association"
            for assoc in associations
        )

        return {
            "associations": associations,
            "warnings": warnings,
            "metadata": {
                **state.get("metadata", {}),
                "association_builder_status": "success",
                "association_builder_ran_at": datetime.now().isoformat(
                    timespec="seconds"
                ),
                "input_effect_measures": len(state.get("effect_measures_found", [])),
                "input_kept_effect_measures": len(kept_effects),
                "associations_built": len(associations),
                "main_project_associations": int(main_project_count),
                "contextual_direct_associations": int(contextual_count),
                "deduplication_rule": (
                    "merge only if scientific key fields are identical; "
                    "analysis_method differences are preserved"
                ),
            },
        }

    except Exception as exc:
        return {
            "errors": state.get("errors", []) + [
                {
                    "agent": "association_builder",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                }
            ],
            "metadata": {
                **state.get("metadata", {}),
                "association_builder_status": "failed",
                "association_builder_ran_at": datetime.now().isoformat(
                    timespec="seconds"
                ),
            },
        }


# ---------------------------------------------------------------------
# LangGraph
# ---------------------------------------------------------------------

def build_graph():
    graph = StateGraph(AssociationBuilderState)

    graph.add_node("association_builder", association_builder_node)

    graph.add_edge(START, "association_builder")
    graph.add_edge("association_builder", END)

    return graph.compile()


# ---------------------------------------------------------------------
# Initial state
# ---------------------------------------------------------------------

def build_initial_state(pmid: str) -> AssociationBuilderState:
    pollutants_found = load_pollutants(pmid)
    outcomes_found = load_outcomes(pmid)
    effect_measures_found = load_effect_measures(pmid)

    return {
        "pmid": pmid,

        "pollutants_found": pollutants_found,
        "outcomes_found": outcomes_found,
        "effect_measures_found": effect_measures_found,

        "associations": [],
        "warnings": [],
        "errors": [],

        "metadata": {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "agent_pipeline": "association_builder_test",
            "previous_pollutants_loaded": len(pollutants_found),
            "previous_outcomes_loaded": len(outcomes_found),
            "previous_effect_measures_loaded": len(effect_measures_found),
            "input_paths": {
                "pollutants": str(POLLUTANT_OUT_DIR / f"{pmid}_pollutants.json"),
                "outcomes": str(OUTCOME_OUT_DIR / f"{pmid}_outcomes.json"),
                "effect_measures": str(
                    EFFECT_OUT_DIR / f"{pmid}_effect_measures.json"
                ),
            },
        },
    }


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build flat pollutant-outcome associations for one PMID."
    )

    parser.add_argument(
        "--pmid",
        default="20123607",
        help="PMID to process. Default: 20123607.",
    )

    args = parser.parse_args()
    pmid = args.pmid

    initial_state = build_initial_state(pmid)

    app = build_graph()
    final_state = app.invoke(initial_state)

    out_state_path = OUT_DIR / f"{pmid}_state.json"
    out_assoc_json_path = OUT_DIR / f"{pmid}_associations.json"
    out_assoc_csv_path = OUT_DIR / f"{pmid}_associations.csv"

    write_json(out_state_path, final_state)

    association_payload = {
        "pmid": pmid,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "associations": final_state.get("associations", []),
        "warnings": final_state.get("warnings", []),
        "errors": final_state.get("errors", []),
        "metadata": final_state.get("metadata", {}),
    }

    write_json(out_assoc_json_path, association_payload)

    write_associations_csv(
        out_assoc_csv_path,
        final_state.get("associations", []),
    )

    print("=" * 80)
    print("ASSOCIATION BUILDER COMPLETE")
    print("=" * 80)
    print(f"PMID: {pmid}")
    print(f"Associations built: {len(final_state.get('associations', []))}")
    print(
        "Main project associations: "
        f"{final_state.get('metadata', {}).get('main_project_associations', 0)}"
    )
    print(
        "Contextual direct associations: "
        f"{final_state.get('metadata', {}).get('contextual_direct_associations', 0)}"
    )
    print(f"Warnings: {len(final_state.get('warnings', []))}")
    print(f"Errors: {len(final_state.get('errors', []))}")
    print(f"State output: {out_state_path}")
    print(f"Association JSON: {out_assoc_json_path}")
    print(f"Association CSV: {out_assoc_csv_path}")
    print("=" * 80)

    if final_state.get("errors"):
        print("ERRORS")
        print("-" * 80)
        for err in final_state["errors"]:
            print(f"- {err.get('error_type')}: {err.get('message')}")
        print("=" * 80)
        return

    print("ASSOCIATIONS")
    print("-" * 80)

    for assoc in final_state.get("associations", []):
        pollutant = assoc.get("pollutant", {})
        outcome = assoc.get("outcome", {})
        effect = assoc.get("effect_measure", {})
        exposure = assoc.get("exposure", {})
        analysis = assoc.get("analysis", {})
        classification = assoc.get("classification", {})

        print(
            f"- {pollutant.get('pollutant_specific')} -> "
            f"{outcome.get('outcome_core')} | "
            f"{effect.get('measure_type')}={effect.get('effect_value')} "
            f"CI={effect.get('ci_lower')}-{effect.get('ci_upper')} "
            f"p={effect.get('p_value')} | "
            f"method={analysis.get('analysis_method')} | "
            f"increment={exposure.get('exposure_increment')} | "
            f"role={classification.get('association_role')} | "
            f"main={classification.get('include_in_main_project_analysis')}"
        )

    if final_state.get("warnings"):
        print("=" * 80)
        print("WARNINGS")
        print("-" * 80)
        for warning in final_state["warnings"]:
            print(f"- {warning.get('warning_type')}: {warning.get('message')}")
        print("=" * 80)


if __name__ == "__main__":
    main()