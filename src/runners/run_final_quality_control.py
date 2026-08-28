"""
CLI runner for final quality control.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from src.config.paths import paths
from src.io.logging_utils import setup_logger
from src.quality_control.final_cleaner import run_final_quality_control


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run final quality control on association CSV."
    )

    parser.add_argument(
        "--input-csv",
        default=str(paths.associations_all_test_csv),
        help="Input associations CSV.",
    )

    parser.add_argument(
        "--clean-csv",
        default=str(paths.final_quality_control_output_dir / "associations_clean_test.csv"),
        help="Output clean CSV.",
    )

    parser.add_argument(
        "--rejected-csv",
        default=str(paths.final_quality_control_output_dir / "associations_rejected_test.csv"),
        help="Output rejected CSV.",
    )

    parser.add_argument(
        "--audit-csv",
        default=str(paths.final_quality_control_output_dir / "qc_audit_test.csv"),
        help="Output QC audit CSV.",
    )

    parser.add_argument(
        "--audit-json",
        default=str(paths.final_quality_control_output_dir / "qc_audit_test.json"),
        help="Output QC audit JSON.",
    )

    args = parser.parse_args()

    paths.ensure_base_dirs()

    logger = setup_logger(
        name="run_final_quality_control",
        log_file=paths.logs_dir / "run_final_quality_control.log",
    )

    logger.info("=" * 80)
    logger.info("FINAL QUALITY CONTROL")
    logger.info("=" * 80)
    logger.info(f"Input CSV: {args.input_csv}")

    audit = run_final_quality_control(
        input_csv=Path(args.input_csv),
        clean_csv=Path(args.clean_csv),
        rejected_csv=Path(args.rejected_csv),
        audit_csv=Path(args.audit_csv),
        audit_json=Path(args.audit_json),
    )

    totals = audit["totals"]

    logger.info("=" * 80)
    logger.info("FINAL QUALITY CONTROL COMPLETE")
    logger.info("=" * 80)
    logger.info(f"Input rows: {totals['input_rows']}")
    logger.info(f"Clean rows: {totals['clean_rows']}")
    logger.info(f"Rejected rows: {totals['rejected_rows']}")
    logger.info(f"Clean main analysis rows: {totals['clean_main_analysis_rows']}")
    logger.info(f"Review rows: {totals['review_rows']}")
    logger.info(f"Clean CSV: {args.clean_csv}")
    logger.info(f"Rejected CSV: {args.rejected_csv}")
    logger.info(f"Audit CSV: {args.audit_csv}")
    logger.info(f"Audit JSON: {args.audit_json}")

    print("=" * 80)
    print("FINAL QUALITY CONTROL COMPLETE")
    print("=" * 80)
    print(f"Input rows: {totals['input_rows']}")
    print(f"Clean rows: {totals['clean_rows']}")
    print(f"Rejected rows: {totals['rejected_rows']}")
    print(f"Clean main analysis rows: {totals['clean_main_analysis_rows']}")
    print(f"Review rows: {totals['review_rows']}")
    print(f"Clean CSV: {args.clean_csv}")
    print(f"Rejected CSV: {args.rejected_csv}")
    print(f"Audit CSV: {args.audit_csv}")
    print(f"Audit JSON: {args.audit_json}")
    print("=" * 80)

    print("By decision")
    print("-" * 80)
    for key, value in audit.get("by_decision", {}).items():
        print(f"{key}: {value}")

    print("=" * 80)
    print("By exposure status")
    print("-" * 80)
    for key, value in audit.get("by_exposure_status", {}).items():
        print(f"{key}: {value}")

    print("=" * 80)
    print("By measure status")
    print("-" * 80)
    for key, value in audit.get("by_measure_status", {}).items():
        print(f"{key}: {value}")

    print("=" * 80)
    print("By outcome status")
    print("-" * 80)
    for key, value in audit.get("by_outcome_status", {}).items():
        print(f"{key}: {value}")

    print("=" * 80)
    print("Per PMID")
    print("-" * 80)
    for pmid, stats in audit.get("by_pmid", {}).items():
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