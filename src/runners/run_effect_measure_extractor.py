"""
CLI runner for effect measure extractor agent.
"""

from __future__ import annotations

import argparse

from src.config.paths import paths
from src.config.settings import settings
from src.io.csv_io import read_csv_rows
from src.io.logging_utils import setup_logger
from src.llm.client import ILAASClient
from src.agents.effect_measure_extractor import run_effect_measure_extractor_for_pmid
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
        raise ValueError("No PMIDs found for effect measure extraction.")

    return pmids


def run_one_pmid(
    pmid: str,
    client: ILAASClient,
    model: str,
    max_output_tokens: int,
) -> dict:
    return run_effect_measure_extractor_for_pmid(
        pmid=pmid,
        segmented_document_path=paths.segmented_document_path(pmid),
        pollutant_json_path=paths.pollutant_output_path(pmid),
        outcome_json_path=paths.outcome_output_path(pmid),
        output_json=paths.effect_measure_output_path(pmid),
        output_state_json=paths.effect_measure_output_dir / f"{pmid}_state.json",
        raw_response_path=paths.effect_measure_output_dir / f"{pmid}_raw_response.txt",
        repair_response_path=paths.effect_measure_output_dir / f"{pmid}_repair_response.txt",
        reasoning_dir=paths.effect_measure_output_dir / "reasoning",
        client=client,
        model=model,
        max_output_tokens=max_output_tokens,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run effect measure extractor agent."
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
        default=3500,
        help="Maximum output tokens for effect measure extractor.",
    )

    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=300,
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
        name="run_effect_measure_extractor",
        log_file=paths.logs_dir / "run_effect_measure_extractor.log",
    )

    pmids = resolve_pmids(args)

    client = ILAASClient(
        model=args.model,
        temperature=0.0,
        max_tokens=args.max_output_tokens,
        timeout_seconds=args.timeout_seconds,
    )

    logger.info("=" * 80)
    logger.info("EFFECT MEASURE EXTRACTOR")
    logger.info("=" * 80)
    logger.info(f"PMIDs: {len(pmids)}")
    logger.info(f"Model: {args.model}")
    logger.info(f"Chunking: Map-Reduce (1 appel LLM par chunk segmente, pas de troncature)")
    logger.info(f"Max output tokens: {args.max_output_tokens}")
    logger.info(f"Workers: {args.workers}")

    def process_one_pmid(pmid: str) -> dict:
        try:
            payload = run_one_pmid(
                pmid=pmid,
                client=client,
                model=args.model,
                max_output_tokens=args.max_output_tokens,
            )

            effects = payload.get("effect_measures_found", [])
            kept_effects = [
                effect for effect in effects
                if bool(effect.get("keep_for_association_builder"))
            ]
            warnings = payload.get("warnings", [])
            errors = payload.get("errors", [])
            repair_used = payload.get("metadata", {}).get("json_repair_used", False)
            previous_pollutants_loaded = payload.get("metadata", {}).get(
                "previous_pollutants_loaded",
                0,
            )
            previous_outcomes_loaded = payload.get("metadata", {}).get(
                "previous_outcomes_loaded",
                0,
            )

            summary = {
                "pmid": pmid,
                "status": "success",
                "effect_measures_found": len(effects),
                "kept_effects": len(kept_effects),
                "warnings": len(warnings),
                "errors": len(errors),
                "repair_used": repair_used,
                "previous_pollutants_loaded": previous_pollutants_loaded,
                "previous_outcomes_loaded": previous_outcomes_loaded,
            }

            logger.info(
                f"OK PMID={pmid} | effects={summary['effect_measures_found']} | "
                f"kept={summary['kept_effects']} | "
                f"warnings={summary['warnings']} | "
                f"errors={summary['errors']} | "
                f"repair_used={summary['repair_used']} | "
                f"previous_pollutants={summary['previous_pollutants_loaded']} | "
                f"previous_outcomes={summary['previous_outcomes_loaded']}"
            )

            return summary

        except Exception as exc:
            summary = {
                "pmid": pmid,
                "status": "failed",
                "effect_measures_found": 0,
                "kept_effects": 0,
                "warnings": 0,
                "errors": 1,
                "repair_used": False,
                "previous_pollutants_loaded": 0,
                "previous_outcomes_loaded": 0,
                "error_type": type(exc).__name__,
                "message": str(exc),
            }

            logger.exception(f"FAILED PMID={pmid}: {exc}")

            return summary

    summaries = run_pmids(pmids, process_one_pmid, max_workers=args.workers)

    total_effects = sum(item["effect_measures_found"] for item in summaries)
    total_kept = sum(item["kept_effects"] for item in summaries)
    total_warnings = sum(item["warnings"] for item in summaries)
    total_errors = sum(item["errors"] for item in summaries)
    total_repairs = sum(1 for item in summaries if item["repair_used"])

    logger.info("=" * 80)
    logger.info("EFFECT MEASURE EXTRACTOR COMPLETE")
    logger.info("=" * 80)
    logger.info(f"PMIDs processed: {len(pmids)}")
    logger.info(f"Effect measures found: {total_effects}")
    logger.info(f"Kept for association builder: {total_kept}")
    logger.info(f"Warnings: {total_warnings}")
    logger.info(f"Errors: {total_errors}")
    logger.info(f"JSON repairs used: {total_repairs}")

    print("=" * 80)
    print("EFFECT MEASURE EXTRACTOR COMPLETE")
    print("=" * 80)
    print(f"PMIDs processed: {len(pmids)}")
    print(f"Effect measures found: {total_effects}")
    print(f"Kept for association builder: {total_kept}")
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
            f"effects={item['effect_measures_found']} | "
            f"kept={item['kept_effects']} | "
            f"warnings={item['warnings']} | "
            f"errors={item['errors']} | "
            f"repair_used={item['repair_used']} | "
            f"previous_pollutants={item['previous_pollutants_loaded']} | "
            f"previous_outcomes={item['previous_outcomes_loaded']}"
        )


if __name__ == "__main__":
    main()