"""Build final inspection tables from QC outputs."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from src.io.csv_io import read_csv_rows, write_csv_rows
from src.io.json_io import read_json_or_empty, write_json


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


def split_reason_tokens(reason_text: str) -> list[str]:
    reason_text = safe_str(reason_text)

    if not reason_text:
        return ["no_reason"]

    parts = [
        item.strip()
        for item in reason_text.split("|")
        if item.strip()
    ]

    return parts or ["no_reason"]


# Filters

def filter_main_associations(
    clean_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        row for row in clean_rows
        if safe_bool(row.get("qc_include_in_clean_main_analysis"))
    ]


def filter_contextual_associations(
    clean_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        row for row in clean_rows
        if row.get("qc_role") == "contextual_air_pollution_association"
    ]


def filter_review_rows(
    clean_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        row for row in clean_rows
        if row.get("qc_decision") == "review"
    ]


# Summaries

def build_rejected_summary(
    rejected_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    counter = Counter()

    for row in rejected_rows:
        reasons = split_reason_tokens(row.get("qc_reasons", ""))

        for reason in reasons:
            counter[reason] += 1

    return [
        {
            "qc_reject_reason": reason,
            "count": count,
        }
        for reason, count in counter.most_common()
    ]


def build_per_pmid_summary(
    clean_rows: list[dict[str, Any]],
    rejected_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    pmid_stats = defaultdict(
        lambda: {
            "pmid": "",
            "clean_rows": 0,
            "main_rows": 0,
            "contextual_rows": 0,
            "review_rows": 0,
            "rejected_rows": 0,
            "project_target_rows": 0,
            "contextual_air_pollutant_rows": 0,
            "source_marker_rows": 0,
            "subgroup_rows": 0,
            "sensitivity_rows": 0,
            "supplementary_rows": 0,
            "concentration_response_rows": 0,
        }
    )

    for row in clean_rows:
        pmid = safe_str(row.get("pmid"))
        stats = pmid_stats[pmid]
        stats["pmid"] = pmid
        stats["clean_rows"] += 1

        if safe_bool(row.get("qc_include_in_clean_main_analysis")):
            stats["main_rows"] += 1

        if row.get("qc_role") == "contextual_air_pollution_association":
            stats["contextual_rows"] += 1

        if row.get("qc_decision") == "review":
            stats["review_rows"] += 1

        if row.get("qc_exposure_status") == "project_target_air_pollutant":
            stats["project_target_rows"] += 1

        if row.get("qc_exposure_status") == "contextual_air_pollutant":
            stats["contextual_air_pollutant_rows"] += 1

        if row.get("qc_exposure_status") == "source_marker_air_pollution":
            stats["source_marker_rows"] += 1

        result_context = row.get("qc_result_context")

        if result_context == "subgroup_analysis":
            stats["subgroup_rows"] += 1

        if result_context == "sensitivity_analysis":
            stats["sensitivity_rows"] += 1

        if result_context == "supplementary_analysis":
            stats["supplementary_rows"] += 1

        if result_context == "concentration_response":
            stats["concentration_response_rows"] += 1

    for row in rejected_rows:
        pmid = safe_str(row.get("pmid"))
        stats = pmid_stats[pmid]
        stats["pmid"] = pmid
        stats["rejected_rows"] += 1

    return sorted(
        pmid_stats.values(),
        key=lambda item: item["pmid"],
    )


def build_pollutant_outcome_summary(
    clean_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped = defaultdict(
        lambda: {
            "pollutant_specific": "",
            "pollutant_role": "",
            "outcome_core": "",
            "measure_type": "",
            "analysis_method": "",
            "n_rows": 0,
            "n_main_rows": 0,
            "n_contextual_rows": 0,
            "pmids": set(),
            "result_contexts": set(),
        }
    )

    for row in clean_rows:
        key = (
            safe_str(row.get("pollutant_specific")),
            safe_str(row.get("pollutant_role")),
            safe_str(row.get("outcome_core")),
            safe_str(row.get("measure_type")),
            safe_str(row.get("analysis_method")),
        )

        item = grouped[key]

        item["pollutant_specific"] = key[0]
        item["pollutant_role"] = key[1]
        item["outcome_core"] = key[2]
        item["measure_type"] = key[3]
        item["analysis_method"] = key[4]

        item["n_rows"] += 1
        item["pmids"].add(safe_str(row.get("pmid")))
        item["result_contexts"].add(safe_str(row.get("qc_result_context")))

        if safe_bool(row.get("qc_include_in_clean_main_analysis")):
            item["n_main_rows"] += 1

        if row.get("qc_role") == "contextual_air_pollution_association":
            item["n_contextual_rows"] += 1

    rows = []

    for item in grouped.values():
        rows.append(
            {
                "pollutant_specific": item["pollutant_specific"],
                "pollutant_role": item["pollutant_role"],
                "outcome_core": item["outcome_core"],
                "measure_type": item["measure_type"],
                "analysis_method": item["analysis_method"],
                "n_rows": item["n_rows"],
                "n_main_rows": item["n_main_rows"],
                "n_contextual_rows": item["n_contextual_rows"],
                "n_pmids": len(item["pmids"]),
                "pmids": ";".join(sorted(item["pmids"])),
                "result_contexts": ";".join(sorted(item["result_contexts"])),
            }
        )

    return sorted(
        rows,
        key=lambda item: (
            item["pollutant_specific"],
            item["outcome_core"],
            item["analysis_method"],
        ),
    )


def build_inspection_audit(
    clean_rows: list[dict[str, Any]],
    rejected_rows: list[dict[str, Any]],
    main_rows: list[dict[str, Any]],
    contextual_rows: list[dict[str, Any]],
    review_rows: list[dict[str, Any]],
    qc_audit: dict[str, Any],
    outputs: dict[str, str],
) -> dict[str, Any]:
    all_rows = clean_rows + rejected_rows

    by_decision = Counter(row.get("qc_decision", "") for row in all_rows)
    by_role = Counter(row.get("qc_role", "") for row in all_rows)
    by_result_context = Counter(row.get("qc_result_context", "") for row in all_rows)
    by_pollutant = Counter(row.get("pollutant_specific", "") for row in clean_rows)
    by_outcome = Counter(row.get("outcome_core", "") for row in clean_rows)
    by_method = Counter(row.get("analysis_method", "") for row in clean_rows)

    return {
        "run_date": now_iso(),
        "inputs": {
            "clean_rows": len(clean_rows),
            "rejected_rows": len(rejected_rows),
            "qc_audit_available": bool(qc_audit),
        },
        "outputs": outputs,
        "totals": {
            "all_rows": len(all_rows),
            "clean_rows": len(clean_rows),
            "rejected_rows": len(rejected_rows),
            "main_rows": len(main_rows),
            "contextual_rows": len(contextual_rows),
            "review_rows": len(review_rows),
        },
        "by_decision": dict(by_decision),
        "by_role": dict(by_role),
        "by_result_context": dict(by_result_context),
        "by_pollutant": dict(by_pollutant),
        "by_outcome": dict(by_outcome),
        "by_method": dict(by_method),
    }


# Public API

def run_final_inspection(
    clean_csv: Path,
    rejected_csv: Path,
    qc_audit_json: Path,
    main_associations_csv: Path,
    contextual_associations_csv: Path,
    review_rows_csv: Path,
    rejected_rows_csv: Path,
    rejected_summary_csv: Path,
    per_pmid_summary_csv: Path,
    pollutant_outcome_summary_csv: Path,
    inspection_audit_json: Path,
) -> dict[str, Any]:
    clean_rows = read_csv_rows(clean_csv)
    rejected_rows = read_csv_rows(rejected_csv)
    qc_audit = read_json_or_empty(qc_audit_json)

    main_rows = filter_main_associations(clean_rows)
    contextual_rows = filter_contextual_associations(clean_rows)
    review_rows = filter_review_rows(clean_rows)

    rejected_summary_rows = build_rejected_summary(rejected_rows)
    per_pmid_summary_rows = build_per_pmid_summary(clean_rows, rejected_rows)
    pollutant_outcome_summary_rows = build_pollutant_outcome_summary(clean_rows)

    original_clean_columns = list(clean_rows[0].keys()) if clean_rows else []
    original_rejected_columns = (
        list(rejected_rows[0].keys()) if rejected_rows else original_clean_columns
    )

    write_csv_rows(main_associations_csv, main_rows, original_clean_columns)
    write_csv_rows(contextual_associations_csv, contextual_rows, original_clean_columns)
    write_csv_rows(review_rows_csv, review_rows, original_clean_columns)
    write_csv_rows(rejected_rows_csv, rejected_rows, original_rejected_columns)

    write_csv_rows(
        rejected_summary_csv,
        rejected_summary_rows,
        ["qc_reject_reason", "count"],
    )

    write_csv_rows(
        per_pmid_summary_csv,
        per_pmid_summary_rows,
        [
            "pmid",
            "clean_rows",
            "main_rows",
            "contextual_rows",
            "review_rows",
            "rejected_rows",
            "project_target_rows",
            "contextual_air_pollutant_rows",
            "source_marker_rows",
            "subgroup_rows",
            "sensitivity_rows",
            "supplementary_rows",
            "concentration_response_rows",
        ],
    )

    write_csv_rows(
        pollutant_outcome_summary_csv,
        pollutant_outcome_summary_rows,
        [
            "pollutant_specific",
            "pollutant_role",
            "outcome_core",
            "measure_type",
            "analysis_method",
            "n_rows",
            "n_main_rows",
            "n_contextual_rows",
            "n_pmids",
            "pmids",
            "result_contexts",
        ],
    )

    outputs = {
        "main_associations_csv": str(main_associations_csv),
        "contextual_associations_csv": str(contextual_associations_csv),
        "review_rows_csv": str(review_rows_csv),
        "rejected_rows_csv": str(rejected_rows_csv),
        "rejected_summary_csv": str(rejected_summary_csv),
        "per_pmid_summary_csv": str(per_pmid_summary_csv),
        "pollutant_outcome_summary_csv": str(pollutant_outcome_summary_csv),
        "inspection_audit_json": str(inspection_audit_json),
    }

    audit = build_inspection_audit(
        clean_rows=clean_rows,
        rejected_rows=rejected_rows,
        main_rows=main_rows,
        contextual_rows=contextual_rows,
        review_rows=review_rows,
        qc_audit=qc_audit,
        outputs=outputs,
    )

    write_json(inspection_audit_json, audit)

    return audit
