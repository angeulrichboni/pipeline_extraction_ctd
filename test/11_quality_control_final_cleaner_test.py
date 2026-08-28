#!/usr/bin/env python3
"""
Final Quality Control Cleaner pour le prototype CTD extraction.

Entrée:
    data/prototype/agent_outputs/multi_pmid_runner/associations_all_test.csv

Sorties:
    data/prototype/agent_outputs/final_quality_control/associations_clean_test.csv
    data/prototype/agent_outputs/final_quality_control/associations_rejected_test.csv
    data/prototype/agent_outputs/final_quality_control/qc_audit_test.csv
    data/prototype/agent_outputs/final_quality_control/qc_audit_test.json

Objectif:
    Nettoyer la table globale produite par association_builder.

Décisions:
    - Ne relance pas les agents.
    - Ne modifie pas les extractions sources.
    - Ajoute une couche de décision QC.
    - Garde les associations pollution de l'air exploitables.
    - Rejette les p-values seules, covariables, arsenic/eau, vitamines, âge maternel, etc.
    - Marque les contextes de résultat:
        main_result,
        subgroup_analysis,
        sensitivity_analysis,
        supplementary_analysis,
        concentration_response.

Corrections importantes:
    - Les covariables sont détectées dans les champs exposition/polluant,
      pas dans toute la phrase evidence.
    - Les termes animaux courts comme rat/mouse/mice sont détectés comme mots complets,
      pas comme sous-chaînes. Cela évite que "rat" matche "concentration", "ratio",
      "rate", "respiratory", etc.
"""

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------

DEFAULT_INPUT_CSV = Path(
    "data/prototype/agent_outputs/multi_pmid_runner/associations_all_test.csv"
)

OUT_DIR = Path("data/prototype/agent_outputs/final_quality_control")
OUT_DIR.mkdir(parents=True, exist_ok=True)

CLEAN_CSV = OUT_DIR / "associations_clean_test.csv"
REJECTED_CSV = OUT_DIR / "associations_rejected_test.csv"
AUDIT_CSV = OUT_DIR / "qc_audit_test.csv"
AUDIT_JSON = OUT_DIR / "qc_audit_test.json"


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def safe_str(value: Any) -> str:
    if value is None:
        return ""

    text = str(value).strip()

    if text.lower() in {"nan", "none", "null"}:
        return ""

    return text


def safe_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value

    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def parse_float_or_none(value: Any) -> float | None:
    text = safe_str(value)

    if not text:
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


def normalize_text(value: Any) -> str:
    text = safe_str(value).lower()
    text = text.replace("₂", "2").replace("₃", "3").replace("ₓ", "x")
    text = text.replace("<sub>2</sub>", "2")
    text = text.replace("<sub>3</sub>", "3")
    text = text.replace("<sub>x</sub>", "x")
    text = text.replace("<sub>X</sub>", "x")
    text = text.replace("μ", "µ")
    text = text.replace("–", "-").replace("—", "-")
    text = text.replace("_", " ")
    text = text.replace("-", " ")
    text = " ".join(text.split())
    return text


def compact(value: Any) -> str:
    return normalize_text(value).replace(" ", "").replace(".", "")


def contains_word(text: str, word: str) -> bool:
    """
    Match un mot entier.

    Exemple:
        contains_word("concentration ratio", "rat") -> False
        contains_word("rat model", "rat") -> True
    """
    pattern = r"\b" + re.escape(word) + r"\b"
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


def read_csv_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing input CSV: {path}")

    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader)


def write_csv_rows(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def write_json(path: Path, obj: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(obj, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------
# QC dictionaries
# ---------------------------------------------------------------------

PROJECT_TARGET_KEYS = {
    "pm",
    "pm25",
    "pm10",
    "pm1",
    "ufp",
    "no",
    "no2",
    "o3",
    "ozone",
}

CONTEXTUAL_AIR_POLLUTANT_KEYS = {
    "co",
    "carbonmonoxide",
    "so2",
    "sulfurdioxide",
    "sulphurdioxide",
    "nox",
    "nitrogenoxides",
    "blackcarbon",
    "soot",
    "h2s",
    "hydrogensulfide",
    "trafficrelatedpollution",
    "trafficrelatedpollutants",
    "trp",
    "roadproximity",
    "roadwayproximity",
}

NON_AIR_POLLUTION_TERMS = {
    "arsenic",
    "ias",
    "inorganic arsenic",
    "drinking water",
    "water ias",
    "daily ias",
    "peak ias",
    "average ias",
    "arsenic exposure",
}

COVARIATE_EXPOSURE_TERMS = {
    "maternal age",
    "prenatal vitamin",
    "vitamin use",
    "bmi",
    "body mass index",
    "education",
    "income",
}


# ---------------------------------------------------------------------
# QC classification
# ---------------------------------------------------------------------

def classify_measure(row: dict[str, Any]) -> tuple[str, list[str]]:
    """
    Retour:
        measure_qc_status, reasons
    """
    reasons = []

    measure_type = normalize_text(row.get("measure_type"))
    measure_name = normalize_text(row.get("measure_name"))
    measure_role = normalize_text(row.get("measure_role"))
    evidence = normalize_text(row.get("evidence_sentence"))

    effect_value = parse_float_or_none(row.get("effect_value"))
    ci_lower = parse_float_or_none(row.get("ci_lower"))
    ci_upper = parse_float_or_none(row.get("ci_upper"))
    p_value = safe_str(row.get("p_value"))

    text = " ".join([measure_type, measure_name, measure_role, evidence])

    # P-value seule ou test de tendance : pas une taille d'effet finale.
    if (
        measure_type in {"p value", "pvalue", "p"}
        or "p value for trend" in text
        or "test for trend" in text
        or "tests for trend" in text
    ):
        reasons.append("p_value_or_trend_test_not_direct_effect_size")
        return "reject_measure", reasons

    # Diagnostics / gènes / hétérogénéité / pléiotropie.
    if measure_role in {
        "heterogeneity test",
        "pleiotropy test",
        "gene association",
        "model diagnostic",
        "incomplete effect description",
    }:
        reasons.append(f"measure_role_not_direct_effect: {measure_role}")
        return "reject_measure", reasons

    valid_effect_types = {
        "or",
        "rr",
        "hr",
        "irr",
        "beta",
        "coefficient",
        "percent change",
        "percent_change",
    }

    if measure_type not in valid_effect_types:
        reasons.append(f"unsupported_measure_type: {measure_type}")
        return "reject_measure", reasons

    if effect_value is None:
        reasons.append("missing_numeric_effect_value")
        return "reject_measure", reasons

    has_ci = ci_lower is not None and ci_upper is not None
    has_p = bool(p_value)

    if not has_ci and not has_p:
        reasons.append("missing_ci_and_p_value")
        return "review_measure", reasons

    return "valid_measure", reasons

def is_missing_or_generic_pollutant(
    pollutant_general: Any,
    pollutant_specific: Any,
    pollutant_original: Any,
) -> bool:
    """
    True si aucun vrai polluant n'est identifié.

    Cas typiques:
        pollutant_general = other
        pollutant_specific = empty / nan
        pollutant_original_mention = empty / nan
    """
    values = [
        compact(pollutant_general),
        compact(pollutant_specific),
        compact(pollutant_original),
    ]

    generic_values = {
        "",
        "nan",
        "none",
        "null",
        "other",
        "unknown",
        "ambiguous",
        "notreported",
    }

    return all(value in generic_values for value in values)

def classify_exposure(row: dict[str, Any]) -> tuple[str, list[str]]:
    """
    Classe l'exposition sans rejeter une ligne valide juste parce que
    l'evidence mentionne âge, sexe, région, subgroup, etc.

    Correction:
    - Si aucun vrai polluant n'est identifié, mais que l'evidence indique
      une covariable comme maternal age ou prenatal vitamin use, on rejette.
    - Les valeurs génériques comme other/unknown/nan ne sont pas considérées
      comme de vrais polluants.
    """
    reasons = []

    pollutant_general = row.get("pollutant_general")
    pollutant_specific = row.get("pollutant_specific")
    pollutant_original = row.get("pollutant_original_mention")
    pollutant_role = normalize_text(row.get("pollutant_role"))
    exposure_increment = row.get("exposure_increment")
    evidence_sentence = row.get("evidence_sentence")

    pollutant_text = normalize_text(
        " ".join(
            [
                safe_str(pollutant_general),
                safe_str(pollutant_specific),
                safe_str(pollutant_original),
            ]
        )
    )

    exposure_text = normalize_text(
        " ".join(
            [
                safe_str(pollutant_general),
                safe_str(pollutant_specific),
                safe_str(pollutant_original),
                safe_str(exposure_increment),
            ]
        )
    )

    evidence_text = normalize_text(evidence_sentence)

    key_specific = compact(pollutant_specific)
    key_general = compact(pollutant_general)
    key_original = compact(pollutant_original)

    # 0. Aucun vrai polluant identifié.
    # Exemple:
    #   pollutant_general=other
    #   pollutant_specific=NaN
    #   evidence="Maternal age was associated..."
    if is_missing_or_generic_pollutant(
        pollutant_general=pollutant_general,
        pollutant_specific=pollutant_specific,
        pollutant_original=pollutant_original,
    ):
        if any(term in evidence_text for term in COVARIATE_EXPOSURE_TERMS):
            reasons.append("covariate_or_non_pollutant_effect")
            return "reject_exposure", reasons

        if any(term in evidence_text for term in NON_AIR_POLLUTION_TERMS):
            reasons.append("non_air_pollution_exposure")
            return "reject_exposure", reasons

        reasons.append("missing_or_generic_pollutant")
        return "reject_exposure", reasons

    # 1. Cibles principales du projet.
    if key_specific in PROJECT_TARGET_KEYS or key_general in PROJECT_TARGET_KEYS:
        return "project_target_air_pollutant", reasons

    # 2. Polluants contextuels de pollution de l'air.
    if (
        key_specific in CONTEXTUAL_AIR_POLLUTANT_KEYS
        or key_general in CONTEXTUAL_AIR_POLLUTANT_KEYS
        or key_original in CONTEXTUAL_AIR_POLLUTANT_KEYS
    ):
        return "contextual_air_pollutant", reasons

    # 3. Source markers air pollution.
    if pollutant_role == "source marker":
        reasons.append("air_pollution_source_marker")
        return "source_marker_air_pollution", reasons

    if (
        "traffic related" in pollutant_text
        or "traffic related" in exposure_text
        or "road proximity" in pollutant_text
        or "road proximity" in exposure_text
        or contains_word(pollutant_text, "trp")
        or contains_word(exposure_text, "trp")
    ):
        reasons.append("traffic_related_source_marker")
        return "source_marker_air_pollution", reasons

    # 4. H2S : polluant contextuel, hors cibles principales.
    if "h2s" in exposure_text or "hydrogen sulfide" in exposure_text:
        reasons.append("contextual_air_pollutant_h2s")
        return "contextual_air_pollutant", reasons

    # 5. Non-air-pollution : arsenic/eau/etc.
    if any(term in exposure_text for term in NON_AIR_POLLUTION_TERMS):
        reasons.append("non_air_pollution_exposure")
        return "reject_exposure", reasons

    # 6. Covariables : si l'exposition elle-même est une covariable.
    if any(term in exposure_text for term in COVARIATE_EXPOSURE_TERMS):
        reasons.append("covariate_or_non_pollutant_effect")
        return "reject_exposure", reasons

    reasons.append("ambiguous_or_non_target_exposure")
    return "review_exposure", reasons

def infer_human_study_from_row(row: dict[str, Any]) -> bool:
    """
    Corrige les faux négatifs is_human_study=False quand la ligne indique
    clairement une étude humaine.

    Correction importante:
        Les termes animaux comme rat/mouse/mice doivent être détectés
        comme mots complets, pas comme sous-chaînes.
        Sinon "rat" matche à tort "ratio", "concentration", "rate", etc.
    """
    combined = normalize_text(
        " ".join(
            [
                safe_str(row.get("outcome_core")),
                safe_str(row.get("outcome_normalized")),
                safe_str(row.get("outcome_category")),
                safe_str(row.get("population_group")),
                safe_str(row.get("evidence_sentence")),
                safe_str(row.get("source_section")),
            ]
        )
    )

    non_human_word_terms = [
        "mice",
        "mouse",
        "rat",
        "rats",
        "murine",
        "zebrafish",
    ]

    non_human_phrase_terms = [
        "cell line",
        "in vitro",
        "animal model",
    ]

    human_word_terms = [
        "patients",
        "patient",
        "children",
        "child",
        "adults",
        "adult",
        "females",
        "female",
        "males",
        "male",
        "women",
        "men",
        "subjects",
        "participants",
    ]

    human_phrase_terms = [
        "pregnant women",
        "study subjects",
        "hospital admission",
        "daily dispensing",
        "dispensing of glyceryl trinitrates",
        "asthma",
        "acute angina",
        "angina pectoris",
        "alzheimer",
        "vascular dementia",
        "acute kidney injury",
        "amyotrophic lateral sclerosis",
        "lung cancer",
        "adenocarcinoma",
        "spontaneous abortion",
    ]

    # 1. Détection non-humaine stricte.
    if any(contains_word(combined, term) for term in non_human_word_terms):
        return False

    if any(term in combined for term in non_human_phrase_terms):
        return False

    # 2. Détection humaine.
    if any(contains_word(combined, term) for term in human_word_terms):
        return True

    if any(term in combined for term in human_phrase_terms):
        return True

    # 3. Fallback vers la valeur déjà produite par outcome_extractor.
    return safe_bool(row.get("is_human_study"))


def classify_outcome(row: dict[str, Any]) -> tuple[str, list[str]]:
    reasons = []

    outcome_core = normalize_text(row.get("outcome_core"))
    outcome_role = normalize_text(row.get("outcome_role"))
    is_human = infer_human_study_from_row(row)

    if not outcome_core:
        reasons.append("missing_outcome_core")
        return "reject_outcome", reasons

    if not is_human:
        reasons.append("non_human_study_or_unknown_human_status")
        return "reject_outcome", reasons

    if outcome_role == "case definition component":
        reasons.append("case_definition_component_not_final_outcome")
        return "reject_outcome", reasons

    return "valid_outcome", reasons


def classify_result_context(row: dict[str, Any]) -> tuple[str, list[str]]:
    """
    Ne rejette aucune ligne.
    Sert uniquement à étiqueter le contexte analytique.
    """
    reasons = []

    source_section = normalize_text(row.get("source_section"))
    exposure_increment = normalize_text(row.get("exposure_increment"))
    evidence = normalize_text(row.get("evidence_sentence"))

    combined = " ".join([source_section, exposure_increment, evidence])

    if "sensitivity" in combined or "excluding prevalent cases" in combined:
        reasons.append("sensitivity_analysis_detected")
        return "sensitivity_analysis", reasons

    if "concentration response" in combined or "concentration-response" in combined:
        reasons.append("concentration_response_detected")
        return "concentration_response", reasons

    if (
        "table s" in combined
        or "supplement" in combined
        or "supplementary" in combined
    ):
        reasons.append("supplementary_result_detected")
        return "supplementary_analysis", reasons

    subgroup_terms_phrase = [
        "non smokers",
        "non-smokers",
        "low pollution cohort",
        "high parental stress",
        "low parental stress",
        "apoe",
        "carriers",
        "noncarriers",
        "midwest",
        "northeast",
        "region",
    ]

    subgroup_terms_word = [
        "men",
        "women",
        "male",
        "female",
        "smokers",
    ]

    if any(term in combined for term in subgroup_terms_phrase):
        reasons.append("subgroup_analysis_detected")
        return "subgroup_analysis", reasons

    if any(contains_word(combined, term) for term in subgroup_terms_word):
        reasons.append("subgroup_analysis_detected")
        return "subgroup_analysis", reasons

    return "main_result", reasons


def make_qc_decision(row: dict[str, Any]) -> dict[str, Any]:
    measure_status, measure_reasons = classify_measure(row)
    exposure_status, exposure_reasons = classify_exposure(row)
    outcome_status, outcome_reasons = classify_outcome(row)
    result_context, context_reasons = classify_result_context(row)

    reasons = measure_reasons + exposure_reasons + outcome_reasons + context_reasons

    is_project_target = safe_bool(row.get("is_project_target"))
    original_main = safe_bool(row.get("include_in_main_project_analysis"))

    reject = False
    review = False

    if measure_status == "reject_measure":
        reject = True

    if exposure_status == "reject_exposure":
        reject = True

    if outcome_status == "reject_outcome":
        reject = True

    if measure_status == "review_measure" or exposure_status == "review_exposure":
        review = True

    if reject:
        qc_decision = "reject"
    elif review:
        qc_decision = "review"
    else:
        qc_decision = "accept"

    include_in_clean_database = qc_decision in {"accept", "review"}

    # Les sous-analyses restent dans la base propre mais sont marquées.
    # Elles peuvent rester dans main_analysis si le polluant est une cible projet
    # et si association_builder l'avait déjà classée main.
    include_in_clean_main_analysis = (
        qc_decision == "accept"
        and is_project_target
        and original_main
        and result_context in {
            "main_result",
            "subgroup_analysis",
            "sensitivity_analysis",
            "supplementary_analysis",
            "concentration_response",
        }
    )

    if result_context != "main_result":
        reasons.append(f"result_context={result_context}")

    if include_in_clean_main_analysis:
        clean_role = "main_project_clean_association"
    elif include_in_clean_database and exposure_status in {
        "contextual_air_pollutant",
        "source_marker_air_pollution",
    }:
        clean_role = "contextual_air_pollution_association"
    elif include_in_clean_database and exposure_status == "project_target_air_pollutant":
        clean_role = "target_pollutant_secondary_or_review_association"
    elif include_in_clean_database:
        clean_role = "review_association"
    else:
        clean_role = "rejected_association"

    return {
        "qc_decision": qc_decision,
        "qc_role": clean_role,
        "qc_measure_status": measure_status,
        "qc_exposure_status": exposure_status,
        "qc_outcome_status": outcome_status,
        "qc_result_context": result_context,
        "qc_include_in_clean_database": include_in_clean_database,
        "qc_include_in_clean_main_analysis": include_in_clean_main_analysis,
        "qc_reasons": " | ".join(reasons),
    }


def apply_qc(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    clean_rows = []
    rejected_rows = []

    for row in rows:
        qc = make_qc_decision(row)

        enriched = {
            **row,
            **qc,
        }

        if qc["qc_decision"] in {"accept", "review"}:
            clean_rows.append(enriched)
        else:
            rejected_rows.append(enriched)

    return clean_rows, rejected_rows


# ---------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------

AUDIT_COLUMNS = [
    "metric",
    "value",
]


def build_audit(
    input_rows: list[dict[str, Any]],
    clean_rows: list[dict[str, Any]],
    rejected_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    all_rows = clean_rows + rejected_rows

    by_decision = Counter(row.get("qc_decision", "") for row in all_rows)
    by_role = Counter(row.get("qc_role", "") for row in all_rows)
    by_result_context = Counter(row.get("qc_result_context", "") for row in all_rows)
    by_exposure_status = Counter(row.get("qc_exposure_status", "") for row in all_rows)
    by_measure_status = Counter(row.get("qc_measure_status", "") for row in all_rows)
    by_outcome_status = Counter(row.get("qc_outcome_status", "") for row in all_rows)

    by_pmid = defaultdict(
        lambda: {
            "input_rows": 0,
            "clean_rows": 0,
            "rejected_rows": 0,
            "clean_main": 0,
            "review_rows": 0,
        }
    )

    for row in input_rows:
        pmid = safe_str(row.get("pmid"))
        by_pmid[pmid]["input_rows"] += 1

    for row in clean_rows:
        pmid = safe_str(row.get("pmid"))
        by_pmid[pmid]["clean_rows"] += 1

        if safe_bool(row.get("qc_include_in_clean_main_analysis")):
            by_pmid[pmid]["clean_main"] += 1

        if row.get("qc_decision") == "review":
            by_pmid[pmid]["review_rows"] += 1

    for row in rejected_rows:
        pmid = safe_str(row.get("pmid"))
        by_pmid[pmid]["rejected_rows"] += 1

    return {
        "run_date": now_iso(),
        "totals": {
            "input_rows": len(input_rows),
            "clean_rows": len(clean_rows),
            "rejected_rows": len(rejected_rows),
            "clean_main_analysis_rows": sum(
                safe_bool(row.get("qc_include_in_clean_main_analysis"))
                for row in clean_rows
            ),
            "review_rows": sum(row.get("qc_decision") == "review" for row in clean_rows),
        },
        "by_decision": dict(by_decision),
        "by_role": dict(by_role),
        "by_result_context": dict(by_result_context),
        "by_exposure_status": dict(by_exposure_status),
        "by_measure_status": dict(by_measure_status),
        "by_outcome_status": dict(by_outcome_status),
        "by_pmid": dict(by_pmid),
        "outputs": {
            "clean_csv": str(CLEAN_CSV),
            "rejected_csv": str(REJECTED_CSV),
            "audit_csv": str(AUDIT_CSV),
            "audit_json": str(AUDIT_JSON),
        },
    }


def write_audit_csv(path: Path, audit: dict[str, Any]) -> None:
    rows = []

    rows.append({"metric": "input_rows", "value": audit["totals"]["input_rows"]})
    rows.append({"metric": "clean_rows", "value": audit["totals"]["clean_rows"]})
    rows.append({"metric": "rejected_rows", "value": audit["totals"]["rejected_rows"]})
    rows.append(
        {
            "metric": "clean_main_analysis_rows",
            "value": audit["totals"]["clean_main_analysis_rows"],
        }
    )
    rows.append({"metric": "review_rows", "value": audit["totals"]["review_rows"]})

    for key, value in audit.get("by_decision", {}).items():
        rows.append({"metric": f"decision.{key}", "value": value})

    for key, value in audit.get("by_role", {}).items():
        rows.append({"metric": f"role.{key}", "value": value})

    for key, value in audit.get("by_result_context", {}).items():
        rows.append({"metric": f"result_context.{key}", "value": value})

    for key, value in audit.get("by_exposure_status", {}).items():
        rows.append({"metric": f"exposure_status.{key}", "value": value})

    for key, value in audit.get("by_measure_status", {}).items():
        rows.append({"metric": f"measure_status.{key}", "value": value})

    for key, value in audit.get("by_outcome_status", {}).items():
        rows.append({"metric": f"outcome_status.{key}", "value": value})

    write_csv_rows(path, rows, AUDIT_COLUMNS)


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Final QC cleaner for association CSV."
    )

    parser.add_argument(
        "--input-csv",
        default=str(DEFAULT_INPUT_CSV),
        help="Input associations_all_test.csv path.",
    )

    args = parser.parse_args()

    input_csv = Path(args.input_csv)

    input_rows = read_csv_rows(input_csv)

    if not input_rows:
        raise ValueError(f"Input CSV is empty: {input_csv}")

    clean_rows, rejected_rows = apply_qc(input_rows)

    original_columns = list(input_rows[0].keys())

    qc_columns = [
        "qc_decision",
        "qc_role",
        "qc_measure_status",
        "qc_exposure_status",
        "qc_outcome_status",
        "qc_result_context",
        "qc_include_in_clean_database",
        "qc_include_in_clean_main_analysis",
        "qc_reasons",
    ]

    output_columns = original_columns + [
        col for col in qc_columns if col not in original_columns
    ]

    write_csv_rows(CLEAN_CSV, clean_rows, output_columns)
    write_csv_rows(REJECTED_CSV, rejected_rows, output_columns)

    audit = build_audit(
        input_rows=input_rows,
        clean_rows=clean_rows,
        rejected_rows=rejected_rows,
    )

    write_json(AUDIT_JSON, audit)
    write_audit_csv(AUDIT_CSV, audit)

    print("=" * 80)
    print("FINAL QUALITY CONTROL CLEANER COMPLETE")
    print("=" * 80)
    print(f"Input rows: {len(input_rows)}")
    print(f"Clean rows: {len(clean_rows)}")
    print(f"Rejected rows: {len(rejected_rows)}")
    print(f"Clean main analysis rows: {audit['totals']['clean_main_analysis_rows']}")
    print(f"Review rows: {audit['totals']['review_rows']}")
    print(f"Clean CSV: {CLEAN_CSV}")
    print(f"Rejected CSV: {REJECTED_CSV}")
    print(f"Audit CSV: {AUDIT_CSV}")
    print(f"Audit JSON: {AUDIT_JSON}")
    print("=" * 80)

    print("By decision")
    print("-" * 80)
    for key, value in audit["by_decision"].items():
        print(f"{key}: {value}")

    print("=" * 80)
    print("By result context")
    print("-" * 80)
    for key, value in audit["by_result_context"].items():
        print(f"{key}: {value}")

    print("=" * 80)
    print("By exposure status")
    print("-" * 80)
    for key, value in audit["by_exposure_status"].items():
        print(f"{key}: {value}")

    print("=" * 80)
    print("By measure status")
    print("-" * 80)
    for key, value in audit["by_measure_status"].items():
        print(f"{key}: {value}")

    print("=" * 80)
    print("By outcome status")
    print("-" * 80)
    for key, value in audit["by_outcome_status"].items():
        print(f"{key}: {value}")

    print("=" * 80)
    print("Per PMID")
    print("-" * 80)
    for pmid, stats in audit["by_pmid"].items():
        print(
            f"{pmid} | "
            f"input={stats['input_rows']} | "
            f"clean={stats['clean_rows']} | "
            f"main={stats['clean_main']} | "
            f"review={stats['review_rows']} | "
            f"rejected={stats['rejected_rows']}"
        )


if __name__ == "__main__":
    main()