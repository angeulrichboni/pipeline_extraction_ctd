"""
CLI runner for deterministic association builder.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from src.config.paths import paths
from src.io.csv_io import read_csv_rows
from src.io.logging_utils import setup_logger
from src.builders.association_builder import run_association_builder_for_pmid


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


def discover_pmids_from_segmented_dir() -> list[str]:
    pmids = []

    for path in paths.segmented_documents_dir.glob("*_segmented.json"):
        pmid = path.name.replace("_segmented.json", "").strip()
        if pmid:
            pmids.append(pmid)

    return sorted(set(pmids))


def resolve_pmids(args: argparse.Namespace) -> list[str]:
    if args.pmid:
        return [args.pmid.strip()]

    if args.pmids:
        return [
            item.strip()
            for item in args.pmids.split(",")
            if item.strip()
        ]

    pmids = discover_pmids_from_segmented_manifest()

    if not pmids:
        pmids = discover_pmids_from_segmented_dir()

    if args.limit is not None:
        pmids = pmids[: args.limit]

    if not pmids:
        raise ValueError(
            "No PMIDs provided and no PMIDs found in segmented manifest or directory."
        )

    return pmids


def run_one_pmid(pmid: str) -> dict:
    return run_association_builder_for_pmid(
        pmid=pmid,
        pollutant_json=paths.pollutant_output_path(pmid),
        outcome_json=paths.outcome_output_path(pmid),
        effect_measure_json=paths.effect_measure_output_path(pmid),
        output_json=paths.association_json_path(pmid),
        output_csv=paths.association_csv_path(pmid),
        output_state_json=paths.association_output_dir / f"{pmid}_state.json",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run deterministic association builder."
    )

    parser.add_argument(
        "--pmid",
        default="",
        help="Single PMID to process.",
    )

    parser.add_argument(
        "--pmids",
        default="",
        help="Comma-separated PMIDs to process.",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit PMIDs loaded from segmented manifest.",
    )

    args = parser.parse_args()

    paths.ensure_base_dirs()

    logger = setup_logger(
        name="run_association_builder",
        log_file=paths.logs_dir / "run_association_builder.log",
    )

    pmids = resolve_pmids(args)

    logger.info("=" * 80)
    logger.info("ASSOCIATION BUILDER")
    logger.info("=" * 80)
    logger.info(f"PMIDs: {len(pmids)}")

    summaries = []

    for index, pmid in enumerate(pmids, start=1):
        logger.info("-" * 80)
        logger.info(f"[{index}/{len(pmids)}] PMID={pmid}")

        try:
            payload = run_one_pmid(pmid)
            metadata = payload.get("metadata", {})

            summary = {
                "pmid": pmid,
                "status": "success",
                "associations_built": metadata.get("associations_built", 0),
                "main_project_associations": metadata.get(
                    "main_project_associations",
                    0,
                ),
                "contextual_direct_associations": metadata.get(
                    "contextual_direct_associations",
                    0,
                ),
                "warnings": len(payload.get("warnings", [])),
                "errors": len(payload.get("errors", [])),
            }

            summaries.append(summary)

            logger.info(
                f"OK | associations={summary['associations_built']} | "
                f"main={summary['main_project_associations']} | "
                f"contextual={summary['contextual_direct_associations']} | "
                f"warnings={summary['warnings']} | errors={summary['errors']}"
            )

        except Exception as exc:
            summary = {
                "pmid": pmid,
                "status": "failed",
                "error_type": type(exc).__name__,
                "message": str(exc),
                "associations_built": 0,
                "main_project_associations": 0,
                "contextual_direct_associations": 0,
                "warnings": 0,
                "errors": 1,
            }

            summaries.append(summary)

            logger.exception(f"FAILED PMID={pmid}: {exc}")

    total_associations = sum(item["associations_built"] for item in summaries)
    total_main = sum(item["main_project_associations"] for item in summaries)
    total_contextual = sum(item["contextual_direct_associations"] for item in summaries)
    total_errors = sum(item["errors"] for item in summaries)
    total_warnings = sum(item["warnings"] for item in summaries)

    logger.info("=" * 80)
    logger.info("ASSOCIATION BUILDER COMPLETE")
    logger.info("=" * 80)
    logger.info(f"PMIDs processed: {len(pmids)}")
    logger.info(f"Associations built: {total_associations}")
    logger.info(f"Main project associations: {total_main}")
    logger.info(f"Contextual direct associations: {total_contextual}")
    logger.info(f"Warnings: {total_warnings}")
    logger.info(f"Errors: {total_errors}")

    print("=" * 80)
    print("ASSOCIATION BUILDER COMPLETE")
    print("=" * 80)
    print(f"PMIDs processed: {len(pmids)}")
    print(f"Associations built: {total_associations}")
    print(f"Main project associations: {total_main}")
    print(f"Contextual direct associations: {total_contextual}")
    print(f"Warnings: {total_warnings}")
    print(f"Errors: {total_errors}")
    print("=" * 80)

    print("Per-PMID summary")
    print("-" * 80)

    for item in summaries:
        print(
            f"{item['pmid']} | "
            f"status={item['status']} | "
            f"associations={item['associations_built']} | "
            f"main={item['main_project_associations']} | "
            f"contextual={item['contextual_direct_associations']} | "
            f"warnings={item['warnings']} | "
            f"errors={item['errors']}"
        )


if __name__ == "__main__":
    main()