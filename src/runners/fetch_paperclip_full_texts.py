"""
CLI runner for Paperclip full-text fetcher.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from src.config.paths import paths
from src.ingestion.paperclip_fetcher import run_paperclip_fetcher
from src.io.logging_utils import setup_logger


def default_prototype_dir() -> Path:
    return getattr(paths, "prototype_dir", Path("data/prototype"))


def default_pubmed_dir() -> Path:
    return default_prototype_dir() / "pubmed"


def default_paperclip_dir() -> Path:
    return default_prototype_dir() / "paperclip"


def parse_pmids(value: str) -> list[str]:
    if not value:
        return []

    return [
        item.strip()
        for item in value.split(",")
        if item.strip()
    ]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch Paperclip full texts using PubMed PMCIDs."
    )

    parser.add_argument(
        "--input-manifest",
        default=str(default_prototype_dir() / "documents_manifest_test.csv"),
        help="Input documents/CTD manifest CSV/JSON/JSONL.",
    )

    parser.add_argument(
        "--pubmed-jsonl",
        default=str(default_pubmed_dir() / "pubmed_test_results.jsonl"),
        help="PubMed results JSONL.",
    )

    parser.add_argument(
        "--pubmed-dir",
        default=str(default_pubmed_dir()),
        help="PubMed output directory containing per-PMID JSON files.",
    )

    parser.add_argument(
        "--output-manifest-csv",
        default=str(
            default_paperclip_dir() / "documents_manifest_test_with_paperclip.csv"
        ),
        help="Output manifest enriched with Paperclip fields.",
    )

    parser.add_argument(
        "--results-jsonl",
        default=str(default_paperclip_dir() / "paperclip_test_results.jsonl"),
        help="Output Paperclip result JSONL.",
    )

    parser.add_argument(
        "--audit-json",
        default=str(default_paperclip_dir() / "paperclip_test_audit.json"),
        help="Output Paperclip audit JSON.",
    )

    parser.add_argument(
        "--full-text-dir",
        default=str(default_paperclip_dir() / "full_texts"),
        help="Directory for parsed full text files.",
    )

    parser.add_argument(
        "--raw-dir",
        default=str(default_paperclip_dir() / "raw"),
        help="Directory for raw Paperclip responses.",
    )

    parser.add_argument(
        "--base-url",
        default="",
        help=(
            "Paperclip base URL. If omitted, uses settings.paperclip_base_url "
            "or PAPERCLIP_BASE_URL."
        ),
    )

    parser.add_argument(
        "--api-key",
        default="",
        help=(
            "Paperclip API key. If omitted, uses settings.paperclip_api_key "
            "or PAPERCLIP_API_KEY."
        ),
    )

    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=120,
        help="HTTP timeout in seconds.",
    )

    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="Maximum retries per Paperclip call.",
    )

    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=1.0,
        help="Sleep between requests.",
    )

    parser.add_argument(
        "--no-reuse-existing",
        action="store_true",
        help="Do not reuse existing full_text/raw files; force API fetch.",
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
        help="Limit number of rows.",
    )

    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Nombre de PMIDs traites en parallele (1 = sequentiel, comme avant).",
    )

    args = parser.parse_args()

    paths.ensure_base_dirs()

    logger = setup_logger(
        name="fetch_paperclip_full_texts",
        log_file=paths.logs_dir / "fetch_paperclip_full_texts.log",
    )

    pmids_filter = parse_pmids(args.pmids)

    logger.info("=" * 80)
    logger.info("FETCH PAPERCLIP FULL TEXTS")
    logger.info("=" * 80)
    logger.info(f"Input manifest: {args.input_manifest}")
    logger.info(f"PubMed JSONL: {args.pubmed_jsonl}")
    logger.info(f"PubMed dir: {args.pubmed_dir}")
    logger.info(f"Output manifest CSV: {args.output_manifest_csv}")
    logger.info(f"Results JSONL: {args.results_jsonl}")
    logger.info(f"Audit JSON: {args.audit_json}")
    logger.info(f"Full text dir: {args.full_text_dir}")
    logger.info(f"Raw dir: {args.raw_dir}")
    logger.info(f"Base URL provided: {bool(args.base_url)}")
    logger.info(f"Reuse existing: {not args.no_reuse_existing}")
    logger.info(f"PMIDs filter: {pmids_filter if pmids_filter else 'all'}")
    logger.info(f"Limit: {args.limit}")

    result = run_paperclip_fetcher(
        input_manifest=Path(args.input_manifest),
        pubmed_jsonl=Path(args.pubmed_jsonl),
        pubmed_dir=Path(args.pubmed_dir),
        output_manifest_csv=Path(args.output_manifest_csv),
        results_jsonl=Path(args.results_jsonl),
        audit_json=Path(args.audit_json),
        full_text_dir=Path(args.full_text_dir),
        raw_dir=Path(args.raw_dir),
        base_url=args.base_url or None,
        api_key=args.api_key or None,
        timeout_seconds=args.timeout_seconds,
        max_retries=args.max_retries,
        sleep_seconds=args.sleep_seconds,
        reuse_existing=not args.no_reuse_existing,
        pmids_filter=pmids_filter or None,
        limit=args.limit,
        max_workers=args.workers,
    )

    audit = result["audit"]
    rows = result["results"]

    logger.info("=" * 80)
    logger.info("FETCH PAPERCLIP FULL TEXTS COMPLETE")
    logger.info("=" * 80)
    logger.info(f"Rows processed: {audit['n_rows_processed']}")
    logger.info(f"Paperclip attempted: {audit['paperclip_attempted']}")
    logger.info(f"Success full text: {audit['success_full_text']}")
    logger.info(f"Abstract only: {audit['abstract_only']}")
    logger.info(f"No PMCID: {audit['no_pmc_id']}")
    logger.info(f"Status distribution: {audit['status_distribution']}")
    logger.info(f"Errors: {len(audit['errors'])}")

    print("=" * 80)
    print("FETCH PAPERCLIP FULL TEXTS COMPLETE")
    print("=" * 80)
    print(f"Rows processed: {audit['n_rows_processed']}")
    print(f"Paperclip attempted: {audit['paperclip_attempted']}")
    print(f"Success full text: {audit['success_full_text']}")
    print(f"Abstract only: {audit['abstract_only']}")
    print(f"No PMCID: {audit['no_pmc_id']}")
    print(f"Status distribution: {audit['status_distribution']}")
    print(f"Errors: {len(audit['errors'])}")
    print(f"Output manifest CSV: {args.output_manifest_csv}")
    print(f"Results JSONL: {args.results_jsonl}")
    print(f"Audit JSON: {args.audit_json}")
    print("=" * 80)

    print("Per-PMID summary")
    print("-" * 80)

    for row in rows:
        print(
            f"{row['pmid']} | "
            f"pmc={row['pmc_id']} | "
            f"status={row['paperclip_status']} | "
            f"full_text={row['has_full_text']} | "
            f"chars={row['paperclip_content_chars']} | "
            f"path={row['full_text_path']}"
        )

    if audit["errors"]:
        print("=" * 80)
        print("ERRORS")
        print("-" * 80)

        for error in audit["errors"]:
            print(
                f"{error.get('pmid')} | "
                f"pmc={error.get('pmc_id')} | "
                f"{error.get('error_type')}: {error.get('message')}"
            )


if __name__ == "__main__":
    main()