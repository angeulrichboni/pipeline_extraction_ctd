# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(os.getenv("CTD_DATA_ROOT", "data/processed"))
OUT_DIR = ROOT / "agent_csv_outputs"
OUT_DIR.mkdir(parents=True, exist_ok=True)


AGENTS = {
    "pollutant_extractor": {
        "filename": "01_pollutant_extractor_output.csv",
        "list_fields": ["pollutants_found", "pollutants"],
        "preferred_fields": [
            "pmid",
            "pollutant_general",
            "pollutant_specific",
            "pollutant_original_mention",
            "is_project_target",
            "is_target_pollutant",
            "pollutant_role",
            "keep_for_final_analysis",
            "evidence_sentence",
            "source_section",
            "source_type",
            "confidence",
        ],
    },
    "outcome_extractor": {
        "filename": "02_outcome_extractor_output.csv",
        "list_fields": ["outcomes_found", "health_outcomes_found", "outcomes"],
        "preferred_fields": [
            "pmid",
            "outcome_original_mention",
            "outcome_normalized",
            "outcome_core",
            "outcome_category",
            "population_group",
            "is_human_study",
            "evidence_sentence",
            "source_section",
            "source_type",
            "confidence",
        ],
    },
    "effect_measure_extractor": {
        "filename": "03_effect_extractor_output.csv",
        "list_fields": ["effects_found", "effect_measures_found", "effect_measures", "effects"],
        "preferred_fields": [
            "pmid",
            "pollutant_general",
            "pollutant_specific",
            "outcome_normalized",
            "measure_type",
            "effect_value",
            "effect_value_numeric",
            "effect_direction",
            "ci_level",
            "ci_lower",
            "ci_upper",
            "p_value",
            "statistical_significance",
            "exposure_increment",
            "exposure_increment_value",
            "exposure_increment_unit",
            "evidence_sentence",
            "source_section",
            "confidence",
        ],
    },
    "association_builder": {
        "filename": "04_association_builder_output.csv",
        "list_fields": ["associations_found", "associations", "main_associations", "association_candidates"],
        "preferred_fields": [
            "association_id",
            "pmid",
            "association_label",
            "association_claim",
            "pollutant_general",
            "pollutant_specific",
            "outcome_normalized",
            "outcome_core",
            "measure_type",
            "effect_value",
            "effect_value_numeric",
            "effect_direction",
            "association_role",
            "evidence_sentence",
            "confidence",
        ],
    },
    "population_extractor": {
        "filename": "05_population_location_extractor_output.csv",
        "list_fields": None,
        "preferred_fields": [
            "pmid",
            "study_country",
            "study_city_or_region",
            "study_location_detail",
            "study_population",
            "age_group",
            "age_min",
            "age_max",
            "age_mean",
            "sex",
            "population_details",
            "evidence_sentence",
            "source_section",
            "confidence",
            "status",
        ],
    },
    "time_extractor": {
        "filename": "06_exposure_temporal_extractor_output.csv",
        "list_fields": ["exposure_temporal_found"],
        "preferred_fields": [
            "association_id",
            "pmid",
            "exposure_window_category",
            "exposure_window_text",
            "exposure_duration_value",
            "exposure_duration_unit",
            "exposure_lag",
            "exposure_period",
            "exposure_averaging_window",
            "exposure_assessment_method",
            "temporal_evidence_sentence",
            "temporal_source_section",
            "temporal_confidence",
            "temporal_status",
        ],
    },
}


def safe_json_load(path: Path) -> Any | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def iter_jsonl(path: Path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        yield json.loads(line)
                    except Exception:
                        continue
    except Exception:
        return


def iter_all_json_objects(root: Path):
    for path in root.rglob("*.json"):
        # Les fichiers de raisonnement CoT (reasoning/*.json) et les fichiers
        # d'etat (*_state.json, qui ne font que re-emballer la meme sortie
        # sous une cle imbriquee) sont exclus : ils matchent le meme champ
        # "agent" que la vraie sortie et creeraient des lignes fantomes ou
        # des doublons dans l'export.
        if "reasoning" in path.parts:
            continue

        if path.name.endswith("_state.json"):
            continue

        obj = safe_json_load(path)
        if obj is not None:
            yield path, obj

    for path in root.rglob("*.jsonl"):
        for obj in iter_jsonl(path):
            yield path, obj


def find_agent_payloads(obj: Any, agent_name: str):
    if isinstance(obj, dict):
        if obj.get("agent") == agent_name:
            yield obj
            return

        if agent_name in obj and isinstance(obj[agent_name], dict):
            yield obj[agent_name]
            return

        for value in obj.values():
            yield from find_agent_payloads(value, agent_name)

    elif isinstance(obj, list):
        for item in obj:
            yield from find_agent_payloads(item, agent_name)


def stringify_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


def extract_rows_from_payload(
    payload: dict[str, Any],
    agent_name: str,
    list_fields: list[str] | None,
    source_path: Path,
) -> list[dict[str, Any]]:

    base = {
        "pmid": payload.get("pmid"),
        "created_at": payload.get("created_at"),
        "agent": agent_name,
        "provider": payload.get("provider"),
        "model": payload.get("model"),
    }

    # association_id n'est pertinent que pour les agents qui travaillent au
    # niveau association (pas pollutant/outcome/population qui sont par
    # PMID) : on ne l'ajoute que si le payload l'a reellement, sinon une
    # colonne fantome entierement vide se glisse dans l'export et casse les
    # jointures ulterieures (ex. avec main_associations_enriched.csv, qui a
    # sa propre colonne association_id).
    if payload.get("association_id") is not None:
        base["association_id"] = payload.get("association_id")

    warnings = payload.get("warnings")
    errors = payload.get("errors")

    if warnings is not None:
        base["warnings"] = warnings

    if errors is not None:
        base["errors"] = errors

    rows = []

    if list_fields:
        items = None

        for field in list_fields:
            value = payload.get(field)
            if isinstance(value, list):
                items = value
                break

        if items is None:
            return []

        for item in items:
            if not isinstance(item, dict):
                continue

            row = dict(base)

            for key, value in item.items():
                row[key] = value

            row["source_json_path"] = str(source_path)

            rows.append(row)

    else:
        row = dict(base)

        for key, value in payload.items():
            if key in {"metadata"}:
                continue
            row[key] = value

        row["source_json_path"] = str(source_path)
        rows.append(row)

    return rows


def clean_dataframe(df: pd.DataFrame, preferred_fields: list[str]) -> pd.DataFrame:
    if df.empty:
        return df

    for col in df.columns:
        df[col] = df[col].apply(stringify_value)

    ordered_cols = []

    for col in preferred_fields:
        if col in df.columns and col not in ordered_cols:
            ordered_cols.append(col)

    technical_cols = [
        "created_at",
        "agent",
        "provider",
        "model",
        "warnings",
        "errors",
        "source_json_path",
    ]

    for col in technical_cols:
        if col in df.columns and col not in ordered_cols:
            ordered_cols.append(col)

    remaining_cols = [
        col for col in df.columns
        if col not in ordered_cols
    ]

    df = df[ordered_cols + remaining_cols]

    dedup_subset = [
        col for col in df.columns
        if col not in {"source_json_path"}
    ]

    df = df.drop_duplicates(subset=dedup_subset, keep="last")

    return df


def export_agent_csv(agent_name: str, config: dict[str, Any]) -> dict[str, Any]:
    all_rows = []

    for source_path, obj in iter_all_json_objects(ROOT):
        for payload in find_agent_payloads(obj, agent_name):
            rows = extract_rows_from_payload(
                payload=payload,
                agent_name=agent_name,
                list_fields=config["list_fields"],
                source_path=source_path,
            )
            all_rows.extend(rows)

    df = pd.DataFrame(all_rows)
    df = clean_dataframe(df, config["preferred_fields"])

    output_path = OUT_DIR / config["filename"]
    df.to_csv(output_path, index=False)

    return {
        "agent": agent_name,
        "rows": len(df),
        "columns": len(df.columns),
        "output_path": str(output_path),
    }


def main() -> None:
    summary = []

    for agent_name, config in AGENTS.items():
        result = export_agent_csv(agent_name, config)
        summary.append(result)

        print(
            f"{agent_name}: rows={result['rows']} "
            f"cols={result['columns']} "
            f"saved={result['output_path']}"
        )

    summary_df = pd.DataFrame(summary)
    summary_path = OUT_DIR / "00_agent_csv_outputs_summary.csv"
    summary_df.to_csv(summary_path, index=False)

    print("Summary saved:", summary_path)


if __name__ == "__main__":
    main()
