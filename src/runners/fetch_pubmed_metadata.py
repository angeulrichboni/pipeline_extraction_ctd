"""
CLI runner for PubMed metadata fetcher.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from src.config.paths import paths
from src.ingestion.pubmed_fetcher import run_pubmed_fetcher
from src.io.logging_utils import setup_logger


def default_prototype_dir() -> Path:
    return getattr(paths, "prototype_dir", Path("data/prototype"))


def default_pubmed_dir() -> Path:
    return default_prototype_dir() / "pubmed"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch PubMed metadata for PMIDs."
    )

    parser.add_argument(
        "--pmid-input",
        default=str(default_prototype_dir() / "pmids_test.txt"),
        help="PMID input file: .txt, .csv, .jsonl, or .json.",
    )

    parser.add_argument(
        "--output-dir",
        default=str(default_pubmed_dir()),
        help="PubMed output directory.",
    )

    parser.add_argument(
        "--results-jsonl",
        default=str(default_pubmed_dir() / "pubmed_test_results.jsonl"),
        help="Output PubMed results JSONL.",
    )

    parser.add_argument(
        "--results-csv",
        default=str(default_pubmed_dir() / "pubmed_test_results.csv"),
        help="Output PubMed results CSV.",
    )

    parser.add_argument(
        "--audit-json",
        default=str(default_pubmed_dir() / "pubmed_test_audit.json"),
        help="Output PubMed audit JSON.",
    )

    parser.add_argument(
        "--pmc-ids-txt",
        default=str(default_pubmed_dir() / "pmc_ids_test.txt"),
        help="Output PMCID list.",
    )

    parser.add_argument(
        "--missing-pmids-txt",
        default=str(default_pubmed_dir() / "pubmed_missing_pmids.txt"),
        help="Output missing PMID list.",
    )

    parser.add_argument(
        "--raw-dir",
        default=str(default_pubmed_dir() / "raw"),
        help="Directory for raw PubMed XML batches.",
    )

    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="PubMed fetch batch size.",
    )

    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=60,
        help="HTTP timeout in seconds.",
    )

    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="Maximum retries per batch.",
    )

    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=0.34,
        help="Sleep between NCBI requests.",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of PMIDs.",
    )

    args = parser.parse_args()

    paths.ensure_base_dirs()

    logger = setup_logger(
        name="fetch_pubmed_metadata",
        log_file=paths.logs_dir / "fetch_pubmed_metadata.log",
    )

    logger.info("=" * 80)
    logger.info("FETCH PUBMED METADATA")
    logger.info("=" * 80)
    logger.info(f"PMID input: {args.pmid_input}")
    logger.info(f"Output dir: {args.output_dir}")
    logger.info(f"Results JSONL: {args.results_jsonl}")
    logger.info(f"Results CSV: {args.results_csv}")
    logger.info(f"Audit JSON: {args.audit_json}")
    logger.info(f"PMC IDs TXT: {args.pmc_ids_txt}")
    logger.info(f"Missing PMIDs TXT: {args.missing_pmids_txt}")
    logger.info(f"Raw dir: {args.raw_dir}")
    logger.info(f"Batch size: {args.batch_size}")
    logger.info(f"Limit: {args.limit}")

    result = run_pubmed_fetcher(
        pmid_input=Path(args.pmid_input),
        output_dir=Path(args.output_dir),
        results_jsonl=Path(args.results_jsonl),
        results_csv=Path(args.results_csv),
        audit_json=Path(args.audit_json),
        pmc_ids_txt=Path(args.pmc_ids_txt),
        missing_pmids_txt=Path(args.missing_pmids_txt),
        raw_dir=Path(args.raw_dir),
        batch_size=args.batch_size,
        timeout_seconds=args.timeout_seconds,
        max_retries=args.max_retries,
        sleep_seconds=args.sleep_seconds,
        limit=args.limit,
    )

    audit = result["audit"]
    rows = result["rows"]
    missing_pmids = result["missing_pmids"]

    logger.info("=" * 80)
    logger.info("FETCH PUBMED METADATA COMPLETE")
    logger.info("=" * 80)
    logger.info(f"PMIDs requested: {audit['n_pmids_requested']}")
    logger.info(f"PubMed records: {audit['n_pubmed_records']}")
    logger.info(f"Missing PMIDs: {audit['n_missing_pmids']}")
    logger.info(f"With abstract: {audit['with_abstract']}")
    logger.info(f"Without abstract: {audit['without_abstract']}")
    logger.info(f"With PMCID: {audit['with_pmc_id']}")
    logger.info(f"Errors: {len(audit['errors'])}")

    print("=" * 80)
    print("FETCH PUBMED METADATA COMPLETE")
    print("=" * 80)
    print(f"PMIDs requested: {audit['n_pmids_requested']}")
    print(f"PubMed records: {audit['n_pubmed_records']}")
    print(f"Missing PMIDs: {audit['n_missing_pmids']}")
    print(f"With abstract: {audit['with_abstract']}")
    print(f"Without abstract: {audit['without_abstract']}")
    print(f"With PMCID: {audit['with_pmc_id']}")
    print(f"Errors: {len(audit['errors'])}")
    print(f"Results JSONL: {args.results_jsonl}")
    print(f"Results CSV: {args.results_csv}")
    print(f"PMC IDs TXT: {args.pmc_ids_txt}")
    print(f"Audit JSON: {args.audit_json}")
    print("=" * 80)

    print("Per-PMID summary")
    print("-" * 80)

    for row in rows:
        print(
            f"{row['pmid']} | "
            f"year={row['year']} | "
            f"pmc={row['pmc_id']} | "
            f"abstract={row['has_abstract']} | "
            f"title_chars={len(row['title'])} | "
            f"abstract_chars={len(row['abstract'])}"
        )

    if missing_pmids:
        print("=" * 80)
        print("MISSING PMIDs")
        print("-" * 80)

        for pmid in missing_pmids:
            print(pmid)

    if audit["errors"]:
        print("=" * 80)
        print("ERRORS")
        print("-" * 80)

        for error in audit["errors"]:
            print(
                f"batch={error.get('batch_index')} | "
                f"{error.get('error_type')}: {error.get('message')}"
            )


if __name__ == "__main__":
    main()