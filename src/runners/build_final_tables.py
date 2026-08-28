from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

import pandas as pd


DATA_ROOT = Path(os.getenv("CTD_DATA_ROOT", "data/processed_full"))

INPUT_DIR = DATA_ROOT / "agent_outputs" / "final_inspection"
OUTPUT_DIR = DATA_ROOT / "final_tables"


MAIN_INPUT = INPUT_DIR / "main_associations_test.csv"
CONTEXTUAL_INPUT = INPUT_DIR / "contextual_associations_test.csv"
POLLUTANT_OUTCOME_SUMMARY_INPUT = INPUT_DIR / "pollutant_outcome_summary_test.csv"
PER_PMID_SUMMARY_INPUT = INPUT_DIR / "per_pmid_final_summary_test.csv"
REVIEW_INPUT = INPUT_DIR / "review_rows_test.csv"
REJECTED_INPUT = INPUT_DIR / "rejected_rows_test.csv"


def clean_text(value) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none", "null"}:
        return ""
    return text


def normalize_key(value) -> str:
    text = clean_text(value).lower()
    text = text.replace("₂", "2").replace("₃", "3")
    text = text.replace("µ", "u").replace("μ", "u")
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text


def make_association_label(row: pd.Series) -> str:
    pollutant = clean_text(row.get("pollutant_specific")) or clean_text(row.get("pollutant_general"))
    outcome = clean_text(row.get("outcome_normalized")) or clean_text(row.get("outcome_core"))

    if pollutant and outcome:
        return f"{pollutant} -> {outcome}"

    return ""


def make_pollutant_outcome_key(row: pd.Series) -> str:
    pollutant = clean_text(row.get("pollutant_specific")) or clean_text(row.get("pollutant_general"))
    outcome = clean_text(row.get("outcome_normalized")) or clean_text(row.get("outcome_core"))

    pollutant_key = normalize_key(pollutant)
    outcome_key = normalize_key(outcome)

    if pollutant_key and outcome_key:
        return f"{pollutant_key}__{outcome_key}"

    return ""


def make_association_claim(row: pd.Series) -> str:
    pollutant = clean_text(row.get("pollutant_specific")) or clean_text(row.get("pollutant_general"))
    outcome = clean_text(row.get("outcome_normalized")) or clean_text(row.get("outcome_core"))
    direction = clean_text(row.get("effect_direction")).lower()

    if not pollutant or not outcome:
        return ""

    if direction == "increase":
        return f"{pollutant} is associated with increased {outcome}"

    if direction == "decrease":
        return f"{pollutant} is associated with decreased {outcome}"

    return f"{pollutant} is associated with {outcome}"


def make_effect_summary(row: pd.Series) -> str:
    measure = clean_text(row.get("measure_type"))
    value = clean_text(row.get("effect_value"))
    ci_lower = clean_text(row.get("ci_lower"))
    ci_upper = clean_text(row.get("ci_upper"))
    p_value = clean_text(row.get("p_value"))
    significance = clean_text(row.get("statistical_significance"))

    parts = []

    if measure and value:
        parts.append(f"{measure}={value}")

    if ci_lower and ci_upper:
        ci_level = clean_text(row.get("ci_level")) or "95%"
        parts.append(f"{ci_level} CI [{ci_lower}, {ci_upper}]")

    if p_value:
        parts.append(f"p={p_value}")

    if significance:
        parts.append(significance)

    return "; ".join(parts)


def infer_contextual_exposure_type(row: pd.Series) -> str:
    text = " ".join(
        [
            clean_text(row.get("pollutant_specific")),
            clean_text(row.get("pollutant_general")),
            clean_text(row.get("pollutant_original_mention")),
            clean_text(row.get("qc_reasons")),
            clean_text(row.get("evidence_sentence")),
        ]
    ).lower()

    if any(term in text for term in ["traffic", "road", "vehicle", "diesel", "truck"]):
        return "traffic_related"

    if any(term in text for term in ["biomass", "wood smoke", "solid fuel", "kerosene", "cook smoke", "cooking"]):
        return "combustion"

    if any(term in text for term in ["environmental tobacco smoke", "secondhand", "passive smoking", "ets", "shs", "cotinine"]):
        return "tobacco_smoke"

    if any(term in text for term in ["industrial", "incinerator", "power plant", "oil and gas", "welding"]):
        return "industrial"

    if any(term in text for term in ["metal", "nickel", "manganese", "copper", "vanadium", "sulfur", "silicon"]):
        return "metal_air_context"

    if any(term in text for term in ["source_marker", "source marker", "road proximity", "dispersion", "air mass"]):
        return "source_marker"

    return "other_contextual"


def add_derived_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    df["association_label"] = df.apply(make_association_label, axis=1)
    df["association_claim"] = df.apply(make_association_claim, axis=1)
    df["pollutant_outcome_key"] = df.apply(make_pollutant_outcome_key, axis=1)
    df["effect_summary"] = df.apply(make_effect_summary, axis=1)

    return df


def select_existing_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    existing = [col for col in columns if col in df.columns]
    return df[existing].copy()


def build_main_analysis_ready() -> pd.DataFrame:
    df = pd.read_csv(MAIN_INPUT)
    df = add_derived_columns(df)

    columns = [
        "association_id",
        "pmid",
        "association_label",
        "association_claim",
        "pollutant_outcome_key",
        "pollutant_general",
        "pollutant_specific",
        "pollutant_original_mention",
        "outcome_normalized",
        "outcome_core",
        "outcome_category",
        "population_group",
        "is_human_study",
        "measure_type",
        "effect_value",
        "effect_value_numeric",
        "effect_direction",
        "ci_level",
        "ci_lower",
        "ci_upper",
        "p_value",
        "statistical_significance",
        "effect_summary",
        "exposure_increment",
        "exposure_increment_value",
        "exposure_increment_unit",
        "adjustment_status",
        "analysis_method",
        "qc_result_context",
        "evidence_sentence",
    ]

    return select_existing_columns(df, columns)


def build_main_scientific() -> pd.DataFrame:
    df = pd.read_csv(MAIN_INPUT)
    df = add_derived_columns(df)

    columns = [
        "association_id",
        "pmid",
        "association_label",
        "association_claim",
        "pollutant_outcome_key",
        "pollutant_general",
        "pollutant_specific",
        "pollutant_original_mention",
        "outcome_normalized",
        "outcome_core",
        "outcome_category",
        "population_group",
        "is_human_study",
        "measure_type",
        "measure_name",
        "measure_role",
        "effect_value",
        "effect_value_numeric",
        "effect_direction",
        "ci_level",
        "ci_lower",
        "ci_upper",
        "p_value",
        "statistical_significance",
        "effect_summary",
        "exposure_increment",
        "exposure_increment_value",
        "exposure_increment_unit",
        "adjustment_status",
        "analysis_method",
        "source_section",
        "source_type",
        "evidence_sentence",
        "pollutant_match_confidence",
        "outcome_match_confidence",
        "effect_extractor_confidence",
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

    return select_existing_columns(df, columns)


def build_contextual_analysis_ready() -> pd.DataFrame:
    df = pd.read_csv(CONTEXTUAL_INPUT)
    df = add_derived_columns(df)
    df["contextual_exposure_type"] = df.apply(infer_contextual_exposure_type, axis=1)

    columns = [
        "association_id",
        "pmid",
        "association_label",
        "association_claim",
        "pollutant_outcome_key",
        "contextual_exposure_type",
        "pollutant_general",
        "pollutant_specific",
        "pollutant_original_mention",
        "outcome_normalized",
        "outcome_core",
        "outcome_category",
        "population_group",
        "is_human_study",
        "measure_type",
        "effect_value",
        "effect_value_numeric",
        "effect_direction",
        "ci_level",
        "ci_lower",
        "ci_upper",
        "p_value",
        "statistical_significance",
        "effect_summary",
        "exposure_increment",
        "exposure_increment_value",
        "exposure_increment_unit",
        "adjustment_status",
        "analysis_method",
        "qc_result_context",
        "evidence_sentence",
    ]

    return select_existing_columns(df, columns)


def copy_if_exists(src: Path, dst: Path) -> None:
    if not src.exists():
        print(f"WARNING missing input: {src}")
        return

    shutil.copy2(src, dst)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    main_analysis = build_main_analysis_ready()
    main_scientific = build_main_scientific()
    contextual_analysis = build_contextual_analysis_ready()

    outputs = {
        "01_main_associations_analysis.csv": main_analysis,
        "02_main_associations_scientific.csv": main_scientific,
        "03_contextual_associations_analysis_ready.csv": contextual_analysis,
    }

    for filename, df in outputs.items():
        path = OUTPUT_DIR / filename
        df.to_csv(path, index=False)
        print(f"WROTE {path} | rows={len(df)} | cols={len(df.columns)}")

    copy_if_exists(
        POLLUTANT_OUTCOME_SUMMARY_INPUT,
        OUTPUT_DIR / "04_pollutant_outcome_summary.csv",
    )
    copy_if_exists(
        PER_PMID_SUMMARY_INPUT,
        OUTPUT_DIR / "05_per_pmid_summary.csv",
    )
    copy_if_exists(
        REVIEW_INPUT,
        OUTPUT_DIR / "06_review_rows.csv",
    )
    copy_if_exists(
        REJECTED_INPUT,
        OUTPUT_DIR / "07_rejected_rows.csv",
    )

    print("=" * 80)
    print("FINAL TABLES CREATED")
    print("=" * 80)
    print(f"Output dir: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()