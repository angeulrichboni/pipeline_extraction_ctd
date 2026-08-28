"""Merge per-PMID association outputs into global files."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from src.io.csv_io import read_csv_rows, write_csv_rows
from src.io.json_io import read_json_or_empty, write_json


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def safe_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value

    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def safe_int(value: Any) -> int:
    try:
        return int(value)
    except Exception:
        return 0


def safe_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    return []


def read_csv_rows_or_empty(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    return read_csv_rows(path)


def discover_pmids_from_association_dir(
    association_output_dir: Path,
) -> list[str]:
    pmids: list[str] = []

    for path in association_output_dir.glob("*_associations.csv"):
        pmid = path.name.replace("_associations.csv", "").strip()
        if pmid:
            pmids.append(pmid)

    return sorted(set(pmids))


def association_csv_path(
    association_output_dir: Path,
    pmid: str,
) -> Path:
    return association_output_dir / f"{pmid}_associations.csv"


def association_json_path(
    association_output_dir: Path,
    pmid: str,
) -> Path:
    return association_output_dir / f"{pmid}_associations.json"


def pollutant_json_path(
    pollutant_output_dir: Path,
    pmid: str,
) -> Path:
    return pollutant_output_dir / f"{pmid}_pollutants.json"


def outcome_json_path(
    outcome_output_dir: Path,
    pmid: str,
) -> Path:
    return outcome_output_dir / f"{pmid}_outcomes.json"


def effect_json_path(
    effect_output_dir: Path,
    pmid: str,
) -> Path:
    return effect_output_dir / f"{pmid}_effect_measures.json"


def summarize_pmid_outputs(
    pmid: str,
    pollutant_output_dir: Path,
    outcome_output_dir: Path,
    effect_output_dir: Path,
    association_output_dir: Path,
) -> dict[str, Any]:
    pollutant_path = pollutant_json_path(pollutant_output_dir, pmid)
    outcome_path = outcome_json_path(outcome_output_dir, pmid)
    effect_path = effect_json_path(effect_output_dir, pmid)
    association_path = association_json_path(association_output_dir, pmid)
    association_csv = association_csv_path(association_output_dir, pmid)

    pollutant_payload = read_json_or_empty(pollutant_path)
    outcome_payload = read_json_or_empty(outcome_path)
    effect_payload = read_json_or_empty(effect_path)
    association_payload = read_json_or_empty(association_path)

    pollutants = safe_list(pollutant_payload.get("pollutants_found"))
    outcomes = safe_list(outcome_payload.get("outcomes_found"))
    effects = safe_list(effect_payload.get("effect_measures_found"))
    associations = safe_list(association_payload.get("associations"))

    kept_effects = [
        effect for effect in effects
        if safe_bool(effect.get("keep_for_association_builder"))
    ]

    main_associations = [
        assoc for assoc in associations
        if safe_bool(
            assoc.get("classification", {}).get(
                "include_in_main_project_analysis"
            )
        )
    ]

    contextual_associations = [
        assoc for assoc in associations
        if assoc.get("classification", {}).get("association_role")
        == "contextual_direct_association"
    ]

    all_warnings = (
        safe_list(pollutant_payload.get("warnings"))
        + safe_list(outcome_payload.get("warnings"))
        + safe_list(effect_payload.get("warnings"))
        + safe_list(association_payload.get("warnings"))
    )

    all_errors = (
        safe_list(pollutant_payload.get("errors"))
        + safe_list(outcome_payload.get("errors"))
        + safe_list(effect_payload.get("errors"))
        + safe_list(association_payload.get("errors"))
    )

    return {
        "pmid": pmid,

        "pollutants_found": len(pollutants),
        "outcomes_found": len(outcomes),
        "effect_measures_found": len(effects),
        "kept_effect_measures": len(kept_effects),

        "associations_built": len(associations),
        "main_project_associations": len(main_associations),
        "contextual_direct_associations": len(contextual_associations),

        "warnings_total": len(all_warnings),
        "errors_total": len(all_errors),

        "pollutant_errors": len(safe_list(pollutant_payload.get("errors"))),
        "outcome_errors": len(safe_list(outcome_payload.get("errors"))),
        "effect_errors": len(safe_list(effect_payload.get("errors"))),
        "association_errors": len(safe_list(association_payload.get("errors"))),

        "pollutant_output": str(pollutant_path),
        "outcome_output": str(outcome_path),
        "effect_output": str(effect_path),
        "association_output": str(association_path),
        "association_csv": str(association_csv),
    }


def merge_association_csvs(
    pmids: list[str],
    association_output_dir: Path,
    output_csv: Path,
) -> list[dict[str, Any]]:
    all_rows: list[dict[str, Any]] = []

    for pmid in pmids:
        rows = read_csv_rows_or_empty(
            association_csv_path(association_output_dir, pmid)
        )
        all_rows.extend(rows)

    write_csv_rows(output_csv, all_rows)

    return all_rows


def merge_association_jsons(
    pmids: list[str],
    association_output_dir: Path,
) -> list[dict[str, Any]]:
    all_associations: list[dict[str, Any]] = []

    for pmid in pmids:
        payload = read_json_or_empty(
            association_json_path(association_output_dir, pmid)
        )

        all_associations.extend(
            safe_list(payload.get("associations"))
        )

    return all_associations


AUDIT_COLUMNS = [
    "pmid",
    "pollutants_found",
    "outcomes_found",
    "effect_measures_found",
    "kept_effect_measures",
    "associations_built",
    "main_project_associations",
    "contextual_direct_associations",
    "warnings_total",
    "errors_total",
    "pollutant_errors",
    "outcome_errors",
    "effect_errors",
    "association_errors",
    "pollutant_output",
    "outcome_output",
    "effect_output",
    "association_output",
    "association_csv",
]


def run_association_merge(
    pmids: list[str],
    pollutant_output_dir: Path,
    outcome_output_dir: Path,
    effect_output_dir: Path,
    association_output_dir: Path,
    output_associations_csv: Path,
    output_associations_json: Path,
    output_audit_csv: Path,
    output_audit_json: Path,
) -> dict[str, Any]:
    audit_rows = [
        summarize_pmid_outputs(
            pmid=pmid,
            pollutant_output_dir=pollutant_output_dir,
            outcome_output_dir=outcome_output_dir,
            effect_output_dir=effect_output_dir,
            association_output_dir=association_output_dir,
        )
        for pmid in pmids
    ]

    write_csv_rows(
        output_audit_csv,
        audit_rows,
        fieldnames=AUDIT_COLUMNS,
    )

    all_csv_rows = merge_association_csvs(
        pmids=pmids,
        association_output_dir=association_output_dir,
        output_csv=output_associations_csv,
    )

    all_associations = merge_association_jsons(
        pmids=pmids,
        association_output_dir=association_output_dir,
    )

    total_warnings = sum(
        safe_int(row.get("warnings_total"))
        for row in audit_rows
    )

    total_errors = sum(
        safe_int(row.get("errors_total"))
        for row in audit_rows
    )

    total_associations = sum(
        safe_int(row.get("associations_built"))
        for row in audit_rows
    )

    total_main = sum(
        safe_int(row.get("main_project_associations"))
        for row in audit_rows
    )

    total_contextual = sum(
        safe_int(row.get("contextual_direct_associations"))
        for row in audit_rows
    )

    associations_payload = {
        "created_at": now_iso(),
        "n_pmids": len(pmids),
        "n_associations": len(all_associations),
        "associations": all_associations,
    }

    write_json(output_associations_json, associations_payload)

    audit_payload = {
        "run_date": now_iso(),
        "pmids_requested": pmids,
        "n_pmids": len(pmids),
        "totals": {
            "associations_built": total_associations,
            "main_project_associations": total_main,
            "contextual_direct_associations": total_contextual,
            "warnings_total": total_warnings,
            "errors_total": total_errors,
            "csv_rows": len(all_csv_rows),
            "json_associations": len(all_associations),
        },
        "outputs": {
            "associations_all_csv": str(output_associations_csv),
            "associations_all_json": str(output_associations_json),
            "audit_csv": str(output_audit_csv),
            "audit_json": str(output_audit_json),
        },
        "per_pmid": audit_rows,
    }

    write_json(output_audit_json, audit_payload)

    return audit_payload
