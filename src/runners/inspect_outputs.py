"""
CLI runner for final output inspection.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from collections import Counter

from src.config.paths import paths
from src.io.csv_io import read_csv_rows
from src.io.logging_utils import setup_logger
from src.quality_control.final_inspector import run_final_inspection


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect final QC outputs."
    )

    parser.add_argument(
        "--clean-csv",
        default=str(paths.associations_clean_test_csv),
        help="Path to associations_clean_test.csv.",
    )

    parser.add_argument(
        "--rejected-csv",
        default=str(paths.associations_rejected_test_csv),
        help="Path to associations_rejected_test.csv.",
    )

    parser.add_argument(
        "--qc-audit-json",
        default=str(paths.final_quality_control_output_dir / "qc_audit_test.json"),
        help="Path to qc_audit_test.json.",
    )

    parser.add_argument(
        "--out-dir",
        default=str(paths.final_inspection_output_dir),
        help="Output directory for final inspection files.",
    )

    args = parser.parse_args()

    paths.ensure_base_dirs()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    logger = setup_logger(
        name="inspect_outputs",
        log_file=paths.logs_dir / "inspect_outputs.log",
    )

    main_associations_csv = out_dir / "main_associations_test.csv"
    contextual_associations_csv = out_dir / "contextual_associations_test.csv"
    review_rows_csv = out_dir / "review_rows_test.csv"
    rejected_rows_csv = out_dir / "rejected_rows_test.csv"
    rejected_summary_csv = out_dir / "rejected_summary_by_reason_test.csv"
    per_pmid_summary_csv = out_dir / "per_pmid_final_summary_test.csv"
    pollutant_outcome_summary_csv = out_dir / "pollutant_outcome_summary_test.csv"
    inspection_audit_json = out_dir / "inspection_audit_test.json"

    logger.info("=" * 80)
    logger.info("FINAL INSPECTION")
    logger.info("=" * 80)
    logger.info(f"Clean CSV: {args.clean_csv}")
    logger.info(f"Rejected CSV: {args.rejected_csv}")

    audit = run_final_inspection(
        clean_csv=Path(args.clean_csv),
        rejected_csv=Path(args.rejected_csv),
        qc_audit_json=Path(args.qc_audit_json),
        main_associations_csv=main_associations_csv,
        contextual_associations_csv=contextual_associations_csv,
        review_rows_csv=review_rows_csv,
        rejected_rows_csv=rejected_rows_csv,
        rejected_summary_csv=rejected_summary_csv,
        per_pmid_summary_csv=per_pmid_summary_csv,
        pollutant_outcome_summary_csv=pollutant_outcome_summary_csv,
        inspection_audit_json=inspection_audit_json,
    )

    totals = audit["totals"]

    clean_rows = read_csv_rows(Path(args.clean_csv))
    rejected_summary_rows = read_csv_rows(rejected_summary_csv)

    logger.info("=" * 80)
    logger.info("FINAL INSPECTION COMPLETE")
    logger.info("=" * 80)
    logger.info(f"Clean rows: {totals['clean_rows']}")
    logger.info(f"Rejected rows: {totals['rejected_rows']}")
    logger.info(f"Main associations: {totals['main_rows']}")
    logger.info(f"Contextual associations: {totals['contextual_rows']}")
    logger.info(f"Review rows: {totals['review_rows']}")

    print("=" * 80)
    print("FINAL INSPECTION COMPLETE")
    print("=" * 80)
    print(f"Clean rows: {totals['clean_rows']}")
    print(f"Rejected rows: {totals['rejected_rows']}")
    print(f"Main associations: {totals['main_rows']}")
    print(f"Contextual associations: {totals['contextual_rows']}")
    print(f"Review rows: {totals['review_rows']}")
    print("=" * 80)
    print(f"Main CSV: {main_associations_csv}")
    print(f"Contextual CSV: {contextual_associations_csv}")
    print(f"Review CSV: {review_rows_csv}")
    print(f"Rejected CSV: {rejected_rows_csv}")
    print(f"Rejected summary CSV: {rejected_summary_csv}")
    print(f"Per-PMID summary CSV: {per_pmid_summary_csv}")
    print(f"Pollutant-outcome summary CSV: {pollutant_outcome_summary_csv}")
    print(f"Inspection audit JSON: {inspection_audit_json}")
    print("=" * 80)

    print("Top pollutants in clean rows")
    print("-" * 80)
    for pollutant, count in Counter(
        row.get("pollutant_specific", "") for row in clean_rows
    ).most_common(10):
        print(f"{pollutant}: {count}")

    print("=" * 80)
    print("Top outcomes in clean rows")
    print("-" * 80)
    for outcome, count in Counter(
        row.get("outcome_core", "") for row in clean_rows
    ).most_common(10):
        print(f"{outcome}: {count}")

    print("=" * 80)
    print("Rejected reasons")
    print("-" * 80)
    for row in rejected_summary_rows[:15]:
        print(f"{row.get('qc_reject_reason')}: {row.get('count')}")


if __name__ == "__main__":
    main()