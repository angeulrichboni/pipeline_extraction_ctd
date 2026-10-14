"""CLI runner for the pollutant extractor agent."""

from __future__ import annotations

import argparse

from src.agents.pollutant_extractor import run_pollutant_extractor_for_pmid
from src.config.paths import paths
from src.config.settings import settings
from src.io.csv_io import read_csv_rows
from src.io.logging_utils import setup_logger
from src.llm.client import ILAASClient
from src.runners.parallel_utils import run_pmids


def discover_pmids_from_segmented_manifest() -> list[str]:
    manifest = paths.segmented_manifest_test_csv
    if not manifest.exists():
        return []
    return sorted(
        {
            str(row.get("pmid", "")).strip()
            for row in read_csv_rows(manifest)
            if str(row.get("pmid", "")).strip()
        }
    )


def discover_pmids_from_segmented_dir() -> list[str]:
    return sorted(
        {
            path.name.removesuffix("_segmented.json").strip()
            for path in paths.segmented_documents_dir.glob("*_segmented.json")
            if path.name.removesuffix("_segmented.json").strip()
        }
    )


def resolve_pmids(args: argparse.Namespace) -> list[str]:
    if args.pmid:
        return [args.pmid.strip()]
    if args.pmids:
        return [item.strip() for item in args.pmids.split(",") if item.strip()]

    pmids = discover_pmids_from_segmented_manifest()
    if not pmids:
        pmids = discover_pmids_from_segmented_dir()
    if args.limit is not None:
        pmids = pmids[: args.limit]
    if not pmids:
        raise ValueError("No PMIDs found for pollutant extraction.")
    return pmids


def run_one_pmid(
    pmid: str,
    client: ILAASClient,
    model: str,
    max_output_tokens: int,
) -> dict:
    return run_pollutant_extractor_for_pmid(
        pmid=pmid,
        segmented_document_path=paths.segmented_document_path(pmid),
        output_json=paths.pollutant_output_path(pmid),
        output_state_json=paths.pollutant_output_dir / f"{pmid}_state.json",
        raw_response_path=paths.pollutant_output_dir / f"{pmid}_raw_response.txt",
        repair_response_path=paths.pollutant_output_dir / f"{pmid}_repair_response.txt",
        reasoning_dir=paths.pollutant_output_dir / "reasoning",
        client=client,
        model=model,
        max_output_tokens=max_output_tokens,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run pollutant extractor agent.")
    parser.add_argument("--pmid", default="", help="Single PMID to process.")
    parser.add_argument("--pmids", default="", help="Comma-separated PMIDs to process.")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--model", default=settings.ilaas_model)
    parser.add_argument("--timeout-seconds", type=int, default=240)
    parser.add_argument("--max-output-tokens", type=int, default=3000)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    paths.ensure_base_dirs()
    logger = setup_logger(
        name="run_pollutant_extractor",
        log_file=paths.logs_dir / "run_pollutant_extractor.log",
    )
    pmids = resolve_pmids(args)
    client = ILAASClient(
        model=args.model,
        temperature=0.0,
        max_tokens=args.max_output_tokens,
        timeout_seconds=args.timeout_seconds,
    )

    def process_one_pmid(pmid: str) -> dict:
        try:
            payload = run_one_pmid(
                pmid=pmid,
                client=client,
                model=args.model,
                max_output_tokens=args.max_output_tokens,
            )
            return {
                "pmid": pmid,
                "status": "success",
                "pollutants": len(payload.get("pollutants_found", [])),
                "warnings": len(payload.get("warnings", [])),
                "errors": len(payload.get("errors", [])),
                "repair_used": payload.get("metadata", {}).get("json_repair_used", False),
            }
        except Exception as exc:
            logger.exception("FAILED PMID=%s: %s", pmid, exc)
            return {
                "pmid": pmid,
                "status": "failed",
                "pollutants": 0,
                "warnings": 0,
                "errors": 1,
                "repair_used": False,
                "error_type": type(exc).__name__,
                "message": str(exc),
            }

    summaries = run_pmids(pmids, process_one_pmid, max_workers=args.workers)
    succeeded = sum(item["status"] == "success" for item in summaries)
    failed = len(summaries) - succeeded
    total_pollutants = sum(item["pollutants"] for item in summaries)

    logger.info(
        "POLLUTANT EXTRACTOR COMPLETE | pmids=%s succeeded=%s failed=%s pollutants=%s",
        len(pmids), succeeded, failed, total_pollutants,
    )
    print(
        f"POLLUTANT EXTRACTOR COMPLETE | PMIDs={len(pmids)} | "
        f"succeeded={succeeded} | failed={failed} | pollutants={total_pollutants}"
    )


if __name__ == "__main__":
    main()
