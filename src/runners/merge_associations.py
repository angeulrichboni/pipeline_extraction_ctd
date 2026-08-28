"""
CLI runner for merging per-PMID association outputs.
"""

from __future__ import annotations

import argparse

from src.config.paths import paths
from src.io.csv_io import read_csv_rows
from src.io.logging_utils import setup_logger
from src.builders.association_merger import (
    discover_pmids_from_association_dir,
    run_association_merge,
)


def discover_pmids_from_segmented_manifest() -> list[str]:
    manifest = paths.segmented_manifest_test_csv

    if not manifest.exists():
        return []

    rows = read_csv_rows(manifest)

    pmids = [
        str(row.get("pmid", "")).strip()
        for row in rows
        if str(row.get("pmid", "")).strip()
    ]

    return sorted(set(pmids))


def resolve_pmids(args: argparse.Namespace) -> list[str]:
    if args.pmids:
        pmids = [
            item.strip()
            for item in args.pmids.split(",")
            if item.strip()
        ]

    elif args.from_association_dir:
        pmids = discover_pmids_from_association_dir(
            paths.association_output_dir
        )

    else:
        pmids = discover_pmids_from_segmented_manifest()

    if args.limit is not None:
        pmids = pmids[: args.limit]

    if not pmids:
        raise ValueError("No PMIDs found for association merge.")

    return pmids


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Merge per-PMID association outputs."
    )

    parser.add_argument(
        "--pmids",
        default="",
        help="Comma-separated PMIDs.",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit PMIDs.",
    )

    parser.add_argument(
        "--from-association-dir",
        action="store_true",
        help="Discover PMIDs from association_builder output directory.",
    )

    args = parser.parse_args()

    paths.ensure_base_dirs()

    logger = setup_logger(
        name="merge_associations",
        log_file=paths.logs_dir / "merge_associations.log",
    )

    pmids = resolve_pmids(args)

    output_associations_csv = (
        paths.multi_pmid_runner_output_dir / "associations_all_test.csv"
    )
    output_associations_json = (
        paths.multi_pmid_runner_output_dir / "associations_all_test.json"
    )
    output_audit_csv = (
        paths.multi_pmid_runner_output_dir / "multi_pmid_audit_test.csv"
    )
    output_audit_json = (
        paths.multi_pmid_runner_output_dir / "multi_pmid_audit_test.json"
    )

    logger.info("=" * 80)
    logger.info("MERGE ASSOCIATIONS")
    logger.info("=" * 80)
    logger.info(f"PMIDs: {len(pmids)}")

    audit = run_association_merge(
        pmids=pmids,
        pollutant_output_dir=paths.pollutant_output_dir,
        outcome_output_dir=paths.outcome_output_dir,
        effect_output_dir=paths.effect_measure_output_dir,
        association_output_dir=paths.association_output_dir,
        output_associations_csv=output_associations_csv,
        output_associations_json=output_associations_json,
        output_audit_csv=output_audit_csv,
        output_audit_json=output_audit_json,
    )

    totals = audit["totals"]

    logger.info("=" * 80)
    logger.info("MERGE ASSOCIATIONS COMPLETE")
    logger.info("=" * 80)
    logger.info(f"PMIDs merged: {audit['n_pmids']}")
    logger.info(f"Associations built: {totals['associations_built']}")
    logger.info(f"Main project associations: {totals['main_project_associations']}")
    logger.info(
        f"Contextual direct associations: "
        f"{totals['contextual_direct_associations']}"
    )
    logger.info(f"Warnings: {totals['warnings_total']}")
    logger.info(f"Errors: {totals['errors_total']}")
    logger.info(f"Associations CSV: {output_associations_csv}")
    logger.info(f"Associations JSON: {output_associations_json}")
    logger.info(f"Audit CSV: {output_audit_csv}")
    logger.info(f"Audit JSON: {output_audit_json}")

    print("=" * 80)
    print("MERGE ASSOCIATIONS COMPLETE")
    print("=" * 80)
    print(f"PMIDs merged: {audit['n_pmids']}")
    print(f"Associations built: {totals['associations_built']}")
    print(f"Main project associations: {totals['main_project_associations']}")
    print(f"Contextual direct associations: {totals['contextual_direct_associations']}")
    print(f"Warnings: {totals['warnings_total']}")
    print(f"Errors: {totals['errors_total']}")
    print(f"Associations CSV: {output_associations_csv}")
    print(f"Associations JSON: {output_associations_json}")
    print(f"Audit CSV: {output_audit_csv}")
    print(f"Audit JSON: {output_audit_json}")
    print("=" * 80)

    print("Per-PMID summary")
    print("-" * 80)
    for row in audit["per_pmid"]:
        print(
            f"{row['pmid']} | "
            f"pollutants={row['pollutants_found']} | "
            f"outcomes={row['outcomes_found']} | "
            f"effects={row['effect_measures_found']} | "
            f"kept_effects={row['kept_effect_measures']} | "
            f"associations={row['associations_built']} | "
            f"main={row['main_project_associations']} | "
            f"contextual={row['contextual_direct_associations']} | "
            f"warnings={row['warnings_total']} | "
            f"errors={row['errors_total']}"
        )


if __name__ == "__main__":
    main()