#!/usr/bin/env python3
"""
Inspection finale des sorties QC.

Entrées:
    data/prototype/agent_outputs/final_quality_control/associations_clean_test.csv
    data/prototype/agent_outputs/final_quality_control/associations_rejected_test.csv
    data/prototype/agent_outputs/final_quality_control/qc_audit_test.json

Sorties:
    data/prototype/agent_outputs/final_inspection/main_associations_test.csv
    data/prototype/agent_outputs/final_inspection/contextual_associations_test.csv
    data/prototype/agent_outputs/final_inspection/review_rows_test.csv
    data/prototype/agent_outputs/final_inspection/rejected_rows_test.csv
    data/prototype/agent_outputs/final_inspection/rejected_summary_by_reason_test.csv
    data/prototype/agent_outputs/final_inspection/per_pmid_final_summary_test.csv
    data/prototype/agent_outputs/final_inspection/pollutant_outcome_summary_test.csv
    data/prototype/agent_outputs/final_inspection/inspection_audit_test.json

Objectif:
    Préparer une inspection manuelle rapide avant passage à un échantillon plus large.
"""

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------

DEFAULT_CLEAN_CSV = Path(
    "data/prototype/agent_outputs/final_quality_control/associations_clean_test.csv"
)

DEFAULT_REJECTED_CSV = Path(
    "data/prototype/agent_outputs/final_quality_control/associations_rejected_test.csv"
)

DEFAULT_QC_AUDIT_JSON = Path(
    "data/prototype/agent_outputs/final_quality_control/qc_audit_test.json"
)

OUT_DIR = Path("data/prototype/agent_outputs/final_inspection")
OUT_DIR.mkdir(parents=True, exist_ok=True)

MAIN_ASSOCIATIONS_CSV = OUT_DIR / "main_associations_test.csv"
CONTEXTUAL_ASSOCIATIONS_CSV = OUT_DIR / "contextual_associations_test.csv"
REVIEW_ROWS_CSV = OUT_DIR / "review_rows_test.csv"
REJECTED_ROWS_CSV = OUT_DIR / "rejected_rows_test.csv"
REJECTED_SUMMARY_CSV = OUT_DIR / "rejected_summary_by_reason_test.csv"
PER_PMID_SUMMARY_CSV = OUT_DIR / "per_pmid_final_summary_test.csv"
POLLUTANT_OUTCOME_SUMMARY_CSV = OUT_DIR / "pollutant_outcome_summary_test.csv"
INSPECTION_AUDIT_JSON = OUT_DIR / "inspection_audit_test.json"


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


def read_csv_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing CSV: {path}")

    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_json(path: Path, obj: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(obj, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_csv_rows(
    path: Path,
    rows: list[dict[str, Any]],
    fieldnames: list[str] | None = None,
) -> None:
    if fieldnames is None:
        fieldnames = sorted({key for row in rows for key in row.keys()})

    if not fieldnames:
        fieldnames = ["empty"]

    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


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


# ---------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------

def filter_main_associations(clean_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row for row in clean_rows
        if safe_bool(row.get("qc_include_in_clean_main_analysis"))
    ]


def filter_contextual_associations(clean_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row for row in clean_rows
        if row.get("qc_role") == "contextual_air_pollution_association"
    ]


def filter_review_rows(clean_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row for row in clean_rows
        if row.get("qc_decision") == "review"
    ]


# ---------------------------------------------------------------------
# Summaries
# ---------------------------------------------------------------------

def build_rejected_summary(rejected_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
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


# ---------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------

def build_inspection_audit(
    clean_rows: list[dict[str, Any]],
    rejected_rows: list[dict[str, Any]],
    main_rows: list[dict[str, Any]],
    contextual_rows: list[dict[str, Any]],
    review_rows: list[dict[str, Any]],
    qc_audit: dict[str, Any],
) -> dict[str, Any]:
    by_decision = Counter(row.get("qc_decision", "") for row in clean_rows + rejected_rows)
    by_role = Counter(row.get("qc_role", "") for row in clean_rows + rejected_rows)
    by_result_context = Counter(row.get("qc_result_context", "") for row in clean_rows + rejected_rows)
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
        "outputs": {
            "main_associations_csv": str(MAIN_ASSOCIATIONS_CSV),
            "contextual_associations_csv": str(CONTEXTUAL_ASSOCIATIONS_CSV),
            "review_rows_csv": str(REVIEW_ROWS_CSV),
            "rejected_rows_csv": str(REJECTED_ROWS_CSV),
            "rejected_summary_csv": str(REJECTED_SUMMARY_CSV),
            "per_pmid_summary_csv": str(PER_PMID_SUMMARY_CSV),
            "pollutant_outcome_summary_csv": str(POLLUTANT_OUTCOME_SUMMARY_CSV),
            "inspection_audit_json": str(INSPECTION_AUDIT_JSON),
        },
        "totals": {
            "all_rows": len(clean_rows) + len(rejected_rows),
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


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect final QC outputs."
    )

    parser.add_argument(
        "--clean-csv",
        default=str(DEFAULT_CLEAN_CSV),
        help="Path to associations_clean_test.csv.",
    )

    parser.add_argument(
        "--rejected-csv",
        default=str(DEFAULT_REJECTED_CSV),
        help="Path to associations_rejected_test.csv.",
    )

    parser.add_argument(
        "--qc-audit-json",
        default=str(DEFAULT_QC_AUDIT_JSON),
        help="Path to qc_audit_test.json.",
    )

    args = parser.parse_args()

    clean_csv = Path(args.clean_csv)
    rejected_csv = Path(args.rejected_csv)
    qc_audit_json = Path(args.qc_audit_json)

    clean_rows = read_csv_rows(clean_csv)
    rejected_rows = read_csv_rows(rejected_csv)
    qc_audit = read_json(qc_audit_json)

    main_rows = filter_main_associations(clean_rows)
    contextual_rows = filter_contextual_associations(clean_rows)
    review_rows = filter_review_rows(clean_rows)

    rejected_summary_rows = build_rejected_summary(rejected_rows)
    per_pmid_summary_rows = build_per_pmid_summary(clean_rows, rejected_rows)
    pollutant_outcome_summary_rows = build_pollutant_outcome_summary(clean_rows)

    original_clean_columns = list(clean_rows[0].keys()) if clean_rows else []
    original_rejected_columns = list(rejected_rows[0].keys()) if rejected_rows else original_clean_columns

    write_csv_rows(MAIN_ASSOCIATIONS_CSV, main_rows, original_clean_columns)
    write_csv_rows(CONTEXTUAL_ASSOCIATIONS_CSV, contextual_rows, original_clean_columns)
    write_csv_rows(REVIEW_ROWS_CSV, review_rows, original_clean_columns)
    write_csv_rows(REJECTED_ROWS_CSV, rejected_rows, original_rejected_columns)

    write_csv_rows(
        REJECTED_SUMMARY_CSV,
        rejected_summary_rows,
        ["qc_reject_reason", "count"],
    )

    write_csv_rows(
        PER_PMID_SUMMARY_CSV,
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
        POLLUTANT_OUTCOME_SUMMARY_CSV,
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

    audit = build_inspection_audit(
        clean_rows=clean_rows,
        rejected_rows=rejected_rows,
        main_rows=main_rows,
        contextual_rows=contextual_rows,
        review_rows=review_rows,
        qc_audit=qc_audit,
    )

    write_json(INSPECTION_AUDIT_JSON, audit)

    print("=" * 80)
    print("FINAL INSPECTION COMPLETE")
    print("=" * 80)
    print(f"Clean rows: {len(clean_rows)}")
    print(f"Rejected rows: {len(rejected_rows)}")
    print(f"Main associations: {len(main_rows)}")
    print(f"Contextual associations: {len(contextual_rows)}")
    print(f"Review rows: {len(review_rows)}")
    print("=" * 80)
    print(f"Main CSV: {MAIN_ASSOCIATIONS_CSV}")
    print(f"Contextual CSV: {CONTEXTUAL_ASSOCIATIONS_CSV}")
    print(f"Review CSV: {REVIEW_ROWS_CSV}")
    print(f"Rejected CSV: {REJECTED_ROWS_CSV}")
    print(f"Rejected summary CSV: {REJECTED_SUMMARY_CSV}")
    print(f"Per-PMID summary CSV: {PER_PMID_SUMMARY_CSV}")
    print(f"Pollutant-outcome summary CSV: {POLLUTANT_OUTCOME_SUMMARY_CSV}")
    print(f"Inspection audit JSON: {INSPECTION_AUDIT_JSON}")
    print("=" * 80)

    print("Top pollutants in clean rows")
    print("-" * 80)
    for pollutant, count in Counter(row.get("pollutant_specific", "") for row in clean_rows).most_common(10):
        print(f"{pollutant}: {count}")

    print("=" * 80)
    print("Top outcomes in clean rows")
    print("-" * 80)
    for outcome, count in Counter(row.get("outcome_core", "") for row in clean_rows).most_common(10):
        print(f"{outcome}: {count}")

    print("=" * 80)
    print("Rejected reasons")
    print("-" * 80)
    for row in rejected_summary_rows[:15]:
        print(f"{row['qc_reject_reason']}: {row['count']}")


if __name__ == "__main__":
    main()