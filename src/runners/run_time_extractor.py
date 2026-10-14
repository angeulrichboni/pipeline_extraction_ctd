"""
CLI runner for exposure temporal (time) extractor agent.

Contrairement aux autres agents (1 PMID -> 1 appel), celui-ci traite
plusieurs associations par PMID : la table d'associations deja enrichie
(main_associations_enriched.csv, section 4.14 du README) est chargee une
fois, regroupee par PMID, puis chaque PMID est traite avec la liste de ses
associations.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import pandas as pd

from src.config.paths import paths
from src.config.settings import settings
from src.io.logging_utils import setup_logger
from src.llm.client import ILAASClient
from src.agents.time_extractor import run_time_extractor_for_pmid
from src.runners.parallel_utils import run_pmids

DATA_ROOT = Path(os.getenv("CTD_DATA_ROOT", "data/processed"))
DEFAULT_ASSOCIATIONS_PATH = DATA_ROOT / "enrichment" / "main_associations_enriched.csv"

ASSOCIATION_COLUMNS = [
    "association_id", "pmid", "pollutant_specific", "outcome_normalized",
    "measure_type", "effect_value", "exposure_increment", "evidence_sentence",
]


def load_associations_by_pmid(associations_path: Path) -> dict[str, list[dict]]:
    df = pd.read_csv(associations_path, low_memory=False)
    df["pmid"] = df["pmid"].astype(str)

    for col in ASSOCIATION_COLUMNS:
        if col not in df.columns:
            df[col] = ""

    df["association_claim"] = df["measure_type"].astype(str)

    grouped: dict[str, list[dict]] = {}

    for pmid, group in df.groupby("pmid"):
        grouped[pmid] = group[ASSOCIATION_COLUMNS + ["association_claim"]].to_dict("records")

    return grouped


def resolve_pmids(args: argparse.Namespace, available_pmids: list[str]) -> list[str]:
    if args.pmid:
        return [args.pmid.strip()]

    if args.pmids:
        return [item.strip() for item in args.pmids.split(",") if item.strip()]

    pmids = sorted(available_pmids)

    if args.limit is not None:
        pmids = pmids[: args.limit]

    if not pmids:
        raise ValueError("No PMIDs with associations found for time extraction.")

    return pmids


def run_one_pmid(
    pmid: str,
    associations: list[dict],
    client: ILAASClient,
    model: str,
    max_output_tokens: int,
) -> dict:
    return run_time_extractor_for_pmid(
        pmid=pmid,
        segmented_document_path=paths.segmented_document_path(pmid),
        associations=associations,
        output_json=paths.exposure_temporal_output_path(pmid),
        output_state_json=paths.exposure_temporal_output_dir / f"{pmid}_state.json",
        raw_response_path=paths.exposure_temporal_output_dir / f"{pmid}_raw_response.txt",
        repair_response_path=paths.exposure_temporal_output_dir / f"{pmid}_repair_response.txt",
        reasoning_dir=paths.exposure_temporal_output_dir / "reasoning",
        client=client,
        model=model,
        max_output_tokens=max_output_tokens,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run exposure temporal (time) extractor agent."
    )

    parser.add_argument("--pmid", default="", help="Single PMID to process.")
    parser.add_argument("--pmids", default="", help="Comma-separated PMIDs to process.")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of PMIDs processed.")
    parser.add_argument(
        "--associations-path", default=str(DEFAULT_ASSOCIATIONS_PATH),
        help="Table d'associations deja enrichie (association_id, pmid, pollutant_specific, outcome_normalized, ...).",
    )
    parser.add_argument("--model", default=settings.ilaas_model, help="LLM model.")
    parser.add_argument("--timeout-seconds", type=int, default=240, help="LLM request timeout in seconds.")
    parser.add_argument("--max-output-tokens", type=int, default=1500, help="Maximum output tokens per association.")
    parser.add_argument(
        "--workers", type=int, default=4,
        help="Nombre de PMIDs traites en parallele (1 = sequentiel).",
    )

    args = parser.parse_args()

    paths.ensure_base_dirs()

    logger = setup_logger(
        name="run_time_extractor",
        log_file=paths.logs_dir / "run_time_extractor.log",
    )

    associations_path = Path(args.associations_path)

    if not associations_path.exists():
        raise FileNotFoundError(
            f"Table d'associations introuvable : {associations_path}. "
            "Lance d'abord build_ctd_pm_enrichment (ou passe --associations-path)."
        )

    associations_by_pmid = load_associations_by_pmid(associations_path)
    pmids = resolve_pmids(args, list(associations_by_pmid.keys()))

    client = ILAASClient(
        model=args.model,
        temperature=0.0,
        max_tokens=args.max_output_tokens,
        timeout_seconds=args.timeout_seconds,
    )

    total_associations = sum(len(associations_by_pmid.get(pmid, [])) for pmid in pmids)

    logger.info("=" * 80)
    logger.info("TIME EXTRACTOR")
    logger.info("=" * 80)
    logger.info(f"Associations table: {associations_path}")
    logger.info(f"PMIDs: {len(pmids)}")
    logger.info(f"Associations a traiter: {total_associations}")
    logger.info(f"Model: {args.model}")
    logger.info(f"Workers: {args.workers}")

    def process_one_pmid(pmid: str) -> dict:
        associations = associations_by_pmid.get(pmid, [])

        if not associations:
            summary = {
                "pmid": pmid, "status": "skipped", "n_associations": 0,
                "repair_used": False,
            }
            logger.info(f"SKIP PMID={pmid} | aucune association trouvee")
            return summary

        try:
            payload = run_one_pmid(
                pmid=pmid,
                associations=associations,
                client=client,
                model=args.model,
                max_output_tokens=args.max_output_tokens,
            )

            repair_used = payload.get("metadata", {}).get("json_repair_used", False)

            summary = {
                "pmid": pmid,
                "status": "success",
                "n_associations": len(payload.get("exposure_temporal_found", [])),
                "repair_used": repair_used,
            }

            logger.info(
                f"OK PMID={pmid} | associations={summary['n_associations']} | "
                f"repair_used={summary['repair_used']}"
            )

            return summary

        except Exception as exc:
            summary = {
                "pmid": pmid, "status": "failed", "n_associations": 0,
                "repair_used": False,
                "error_type": type(exc).__name__, "message": str(exc),
            }

            logger.exception(f"FAILED PMID={pmid}: {exc}")

            return summary

    summaries = run_pmids(pmids, process_one_pmid, max_workers=args.workers)

    succeeded = sum(1 for item in summaries if item["status"] == "success")
    failed = sum(1 for item in summaries if item["status"] == "failed")
    skipped = sum(1 for item in summaries if item["status"] == "skipped")
    total_processed_associations = sum(item["n_associations"] for item in summaries)
    total_repairs = sum(1 for item in summaries if item["repair_used"])

    logger.info("=" * 80)
    logger.info("TIME EXTRACTOR COMPLETE")
    logger.info("=" * 80)
    logger.info(f"PMIDs processed: {len(pmids)}")
    logger.info(f"Succeeded: {succeeded}")
    logger.info(f"Failed: {failed}")
    logger.info(f"Skipped (no associations): {skipped}")
    logger.info(f"Associations processed: {total_processed_associations}")
    logger.info(f"JSON repairs used: {total_repairs}")

    print("=" * 80)
    print("TIME EXTRACTOR COMPLETE")
    print("=" * 80)
    print(f"PMIDs processed: {len(pmids)}")
    print(f"Succeeded: {succeeded}")
    print(f"Failed: {failed}")
    print(f"Skipped (no associations): {skipped}")
    print(f"Associations processed: {total_processed_associations}")
    print(f"JSON repairs used: {total_repairs}")
    print("=" * 80)

    print("Per-PMID summary")
    print("-" * 80)

    for item in summaries:
        print(
            f"{item['pmid']} | status={item['status']} | "
            f"associations={item['n_associations']} | repair_used={item['repair_used']}"
        )


if __name__ == "__main__":
    main()
