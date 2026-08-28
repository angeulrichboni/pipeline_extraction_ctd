"""
CLI runner for population/location extractor agent.
"""

from __future__ import annotations

import argparse

from src.config.paths import paths
from src.config.settings import settings
from src.io.csv_io import read_csv_rows
from src.io.logging_utils import setup_logger
from src.llm.client import ILAASClient
from src.agents.population_extractor import run_population_extractor_for_pmid
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
        raise ValueError("No PMIDs found for population extraction.")

    return pmids


def run_one_pmid(
    pmid: str,
    client: ILAASClient,
    model: str,
    max_output_tokens: int,
) -> dict:
    return run_population_extractor_for_pmid(
        pmid=pmid,
        segmented_document_path=paths.segmented_document_path(pmid),
        output_json=paths.population_output_path(pmid),
        output_state_json=paths.population_output_dir / f"{pmid}_state.json",
        raw_response_path=paths.population_output_dir / f"{pmid}_raw_response.txt",
        repair_response_path=paths.population_output_dir / f"{pmid}_repair_response.txt",
        reasoning_dir=paths.population_output_dir / "reasoning",
        client=client,
        model=model,
        max_output_tokens=max_output_tokens,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run population/location extractor agent."
    )

    parser.add_argument("--pmid", default="", help="Single PMID to process.")
    parser.add_argument("--pmids", default="", help="Comma-separated PMIDs to process.")
    parser.add_argument("--limit", type=int, default=None, help="Limit PMIDs loaded from segmented manifest.")
    parser.add_argument("--model", default=settings.ilaas_model, help="LLM model.")
    parser.add_argument("--timeout-seconds", type=int, default=240, help="LLM request timeout in seconds.")
    parser.add_argument("--max-output-tokens", type=int, default=1500, help="Maximum output tokens for population extractor.")
    parser.add_argument(
        "--workers", type=int, default=4,
        help="Nombre de PMIDs traites en parallele (1 = sequentiel).",
    )

    args = parser.parse_args()

    paths.ensure_base_dirs()

    logger = setup_logger(
        name="run_population_extractor",
        log_file=paths.logs_dir / "run_population_extractor.log",
    )

    pmids = resolve_pmids(args)

    client = ILAASClient(
        model=args.model,
        temperature=0.0,
        max_tokens=args.max_output_tokens,
        timeout_seconds=args.timeout_seconds,
    )

    logger.info("=" * 80)
    logger.info("POPULATION EXTRACTOR")
    logger.info("=" * 80)
    logger.info(f"PMIDs: {len(pmids)}")
    logger.info(f"Model: {args.model}")
    logger.info("Chunking: document entier en un appel (reponse unique par PMID, pas de troncature)")
    logger.info(f"Workers: {args.workers}")

    def process_one_pmid(pmid: str) -> dict:
        try:
            payload = run_one_pmid(
                pmid=pmid,
                client=client,
                model=args.model,
                max_output_tokens=args.max_output_tokens,
            )

            repair_used = payload.get("metadata", {}).get("json_repair_used", False)

            summary = {
                "pmid": pmid,
                "status": "success",
                "study_country": payload.get("study_country", ""),
                "sex": payload.get("sex", ""),
                "extraction_status": payload.get("status", ""),
                "repair_used": repair_used,
            }

            logger.info(
                f"OK PMID={pmid} | country={summary['study_country']} | "
                f"sex={summary['sex']} | status={summary['extraction_status']} | "
                f"repair_used={summary['repair_used']}"
            )

            return summary

        except Exception as exc:
            summary = {
                "pmid": pmid,
                "status": "failed",
                "study_country": "",
                "sex": "",
                "extraction_status": "",
                "repair_used": False,
                "error_type": type(exc).__name__,
                "message": str(exc),
            }

            logger.exception(f"FAILED PMID={pmid}: {exc}")

            return summary

    summaries = run_pmids(pmids, process_one_pmid, max_workers=args.workers)

    succeeded = sum(1 for item in summaries if item["status"] == "success")
    failed = sum(1 for item in summaries if item["status"] == "failed")
    total_repairs = sum(1 for item in summaries if item["repair_used"])

    logger.info("=" * 80)
    logger.info("POPULATION EXTRACTOR COMPLETE")
    logger.info("=" * 80)
    logger.info(f"PMIDs processed: {len(pmids)}")
    logger.info(f"Succeeded: {succeeded}")
    logger.info(f"Failed: {failed}")
    logger.info(f"JSON repairs used: {total_repairs}")

    print("=" * 80)
    print("POPULATION EXTRACTOR COMPLETE")
    print("=" * 80)
    print(f"PMIDs processed: {len(pmids)}")
    print(f"Succeeded: {succeeded}")
    print(f"Failed: {failed}")
    print(f"JSON repairs used: {total_repairs}")
    print("=" * 80)

    print("Per-PMID summary")
    print("-" * 80)

    for item in summaries:
        print(
            f"{item['pmid']} | "
            f"status={item['status']} | "
            f"country={item['study_country']} | "
            f"sex={item['sex']} | "
            f"repair_used={item['repair_used']}"
        )


if __name__ == "__main__":
    main()