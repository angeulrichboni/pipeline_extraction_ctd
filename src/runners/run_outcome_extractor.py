"""
CLI runner for outcome extractor agent.
"""

from __future__ import annotations

import argparse

from src.config.paths import paths
from src.config.settings import settings
from src.io.csv_io import read_csv_rows
from src.io.logging_utils import setup_logger
from src.llm.client import ILAASClient
from src.agents.outcome_extractor import run_outcome_extractor_for_pmid
from src.runners.parallel_utils import run_pmids


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
        raise ValueError("No PMIDs found for outcome extraction.")

    return pmids


def run_one_pmid(
    pmid: str,
    client: ILAASClient,
    model: str,
    max_output_tokens: int,
) -> dict:
    return run_outcome_extractor_for_pmid(
        pmid=pmid,
        segmented_document_path=paths.segmented_document_path(pmid),
        pollutant_json_path=paths.pollutant_output_path(pmid),
        output_json=paths.outcome_output_path(pmid),
        output_state_json=paths.outcome_output_dir / f"{pmid}_state.json",
        raw_response_path=paths.outcome_output_dir / f"{pmid}_raw_response.txt",
        repair_response_path=paths.outcome_output_dir / f"{pmid}_repair_response.txt",
        reasoning_dir=paths.outcome_output_dir / "reasoning",
        client=client,
        model=model,
        max_output_tokens=max_output_tokens,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run outcome extractor agent."
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

    parser.add_argument(
        "--model",
        default=settings.ilaas_model,
        help="LLM model.",
    )

    parser.add_argument(
        "--max-output-tokens",
        type=int,
        default=2500,
        help="Maximum output tokens for outcome extractor.",
    )

    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=240,
        help="LLM request timeout in seconds.",
    )

    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Nombre de PMIDs traites en parallele (1 = sequentiel, comme avant).",
    )

    args = parser.parse_args()

    paths.ensure_base_dirs()

    logger = setup_logger(
        name="run_outcome_extractor",
        log_file=paths.logs_dir / "run_outcome_extractor.log",
    )

    pmids = resolve_pmids(args)

    client = ILAASClient(
        model=args.model,
        temperature=0.0,
        max_tokens=args.max_output_tokens,
        timeout_seconds=args.timeout_seconds,
    )

    logger.info("=" * 80)
    logger.info("OUTCOME EXTRACTOR")
    logger.info("=" * 80)
    logger.info(f"PMIDs: {len(pmids)}")
    logger.info(f"Model: {args.model}")
    logger.info(f"Chunking: Map-Reduce (1 appel LLM par chunk segmente, pas de troncature)")
    logger.info(f"Workers: {args.workers}")

    def process_one_pmid(pmid: str) -> dict:
        try:
            payload = run_one_pmid(
                pmid=pmid,
                client=client,
                model=args.model,
                max_output_tokens=args.max_output_tokens,
            )

            outcomes_found = payload.get("outcomes_found", [])
            warnings = payload.get("warnings", [])
            errors = payload.get("errors", [])
            repair_used = payload.get("metadata", {}).get("json_repair_used", False)
            previous_pollutants_loaded = payload.get("metadata", {}).get(
                "previous_pollutants_loaded",
                0,
            )

            summary = {
                "pmid": pmid,
                "status": "success",
                "outcomes_found": len(outcomes_found),
                "warnings": len(warnings),
                "errors": len(errors),
                "repair_used": repair_used,
                "previous_pollutants_loaded": previous_pollutants_loaded,
            }

            logger.info(
                f"OK PMID={pmid} | outcomes={summary['outcomes_found']} | "
                f"warnings={summary['warnings']} | "
                f"errors={summary['errors']} | "
                f"repair_used={summary['repair_used']} | "
                f"previous_pollutants={summary['previous_pollutants_loaded']}"
            )

            return summary

        except Exception as exc:
            summary = {
                "pmid": pmid,
                "status": "failed",
                "outcomes_found": 0,
                "warnings": 0,
                "errors": 1,
                "repair_used": False,
                "previous_pollutants_loaded": 0,
                "error_type": type(exc).__name__,
                "message": str(exc),
            }

            logger.exception(f"FAILED PMID={pmid}: {exc}")

            return summary

    summaries = run_pmids(pmids, process_one_pmid, max_workers=args.workers)

    total_outcomes = sum(item["outcomes_found"] for item in summaries)
    total_warnings = sum(item["warnings"] for item in summaries)
    total_errors = sum(item["errors"] for item in summaries)
    total_repairs = sum(1 for item in summaries if item["repair_used"])

    logger.info("=" * 80)
    logger.info("OUTCOME EXTRACTOR COMPLETE")
    logger.info("=" * 80)
    logger.info(f"PMIDs processed: {len(pmids)}")
    logger.info(f"Outcomes found: {total_outcomes}")
    logger.info(f"Warnings: {total_warnings}")
    logger.info(f"Errors: {total_errors}")
    logger.info(f"JSON repairs used: {total_repairs}")

    print("=" * 80)
    print("OUTCOME EXTRACTOR COMPLETE")
    print("=" * 80)
    print(f"PMIDs processed: {len(pmids)}")
    print(f"Outcomes found: {total_outcomes}")
    print(f"Warnings: {total_warnings}")
    print(f"Errors: {total_errors}")
    print(f"JSON repairs used: {total_repairs}")
    print("=" * 80)

    print("Per-PMID summary")
    print("-" * 80)

    for item in summaries:
        print(
            f"{item['pmid']} | "
            f"status={item['status']} | "
            f"outcomes={item['outcomes_found']} | "
            f"warnings={item['warnings']} | "
            f"errors={item['errors']} | "
            f"repair_used={item['repair_used']} | "
            f"previous_pollutants={item['previous_pollutants_loaded']}"
        )


if __name__ == "__main__":
    main()