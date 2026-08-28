"""
CLI runner for LLM input builder.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from src.config.paths import paths
from src.io.logging_utils import setup_logger
from src.preprocessing.llm_input_builder import run_llm_input_builder


def default_prototype_dir() -> Path:
    return getattr(paths, "prototype_dir", Path("data/prototype"))


def default_manifest_path() -> Path:
    return default_prototype_dir() / "paperclip" / "documents_manifest_test_with_paperclip.csv"


def default_pubmed_dir() -> Path:
    return default_prototype_dir() / "pubmed"


def default_paperclip_dir() -> Path:
    return default_prototype_dir() / "paperclip" / "full_texts"


def default_llm_inputs_dir() -> Path:
    return getattr(paths, "llm_inputs_dir", default_prototype_dir() / "llm_inputs")


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
        description="Prepare canonical LLM inputs from CTD, PubMed and Paperclip."
    )

    parser.add_argument(
        "--manifest",
        default=str(default_manifest_path()),
        help="CTD/PMID manifest CSV/JSON/JSONL.",
    )

    parser.add_argument(
        "--pubmed-dir",
        default=str(default_pubmed_dir()),
        help="Directory containing PubMed metadata JSON files.",
    )

    parser.add_argument(
        "--paperclip-dir",
        default=str(default_paperclip_dir()),
        help="Directory containing Paperclip full text files.",
    )

    parser.add_argument(
        "--output-jsonl",
        default=str(default_llm_inputs_dir() / "llm_inputs_test.jsonl"),
        help="Output LLM input JSONL.",
    )

    parser.add_argument(
        "--manifest-csv",
        default=str(default_llm_inputs_dir() / "llm_inputs_manifest_test.csv"),
        help="Output LLM input manifest CSV.",
    )

    parser.add_argument(
        "--audit-json",
        default=str(default_llm_inputs_dir() / "llm_inputs_audit_test.json"),
        help="Output LLM input audit JSON.",
    )

    parser.add_argument(
        "--pmids",
        default="",
        help="Comma-separated PMIDs to include.",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of PMIDs.",
    )

    args = parser.parse_args()

    paths.ensure_base_dirs()

    output_jsonl = Path(args.output_jsonl)
    manifest_csv = Path(args.manifest_csv)
    audit_json = Path(args.audit_json)

    logger = setup_logger(
        name="prepare_llm_inputs",
        log_file=paths.logs_dir / "prepare_llm_inputs.log",
    )

    pmids_filter = parse_pmids(args.pmids)

    logger.info("=" * 80)
    logger.info("PREPARE LLM INPUTS")
    logger.info("=" * 80)
    logger.info(f"Manifest: {args.manifest}")
    logger.info(f"PubMed dir: {args.pubmed_dir}")
    logger.info(f"Paperclip dir: {args.paperclip_dir}")
    logger.info(f"Output JSONL: {output_jsonl}")
    logger.info(f"Manifest CSV: {manifest_csv}")
    logger.info(f"Audit JSON: {audit_json}")
    logger.info(f"PMIDs filter: {pmids_filter if pmids_filter else 'all'}")
    logger.info(f"Limit: {args.limit}")

    result = run_llm_input_builder(
        manifest_path=Path(args.manifest),
        pubmed_dir=Path(args.pubmed_dir),
        paperclip_dir=Path(args.paperclip_dir),
        output_jsonl=output_jsonl,
        manifest_csv=manifest_csv,
        audit_json=audit_json,
        pmids_filter=pmids_filter or None,
        limit=args.limit,
    )

    audit = result["audit"]
    summaries = result["summaries"]

    logger.info("=" * 80)
    logger.info("PREPARE LLM INPUTS COMPLETE")
    logger.info("=" * 80)
    logger.info(f"Rows: {audit['n_llm_input_rows']}")
    logger.info(f"With full text: {audit['with_full_text']}")
    logger.info(f"Abstract only: {audit['abstract_only']}")
    logger.info(f"Missing abstract: {audit['missing_abstract']}")
    logger.info(f"Errors: {len(audit['errors'])}")

    print("=" * 80)
    print("PREPARE LLM INPUTS COMPLETE")
    print("=" * 80)
    print(f"Rows: {audit['n_llm_input_rows']}")
    print(f"With full text: {audit['with_full_text']}")
    print(f"Abstract only: {audit['abstract_only']}")
    print(f"Missing abstract: {audit['missing_abstract']}")
    print(f"Text source distribution: {audit['text_source_distribution']}")
    print(f"Paperclip status distribution: {audit['paperclip_status_distribution']}")
    print(f"Errors: {len(audit['errors'])}")
    print(f"JSONL: {output_jsonl}")
    print(f"Manifest CSV: {manifest_csv}")
    print(f"Audit JSON: {audit_json}")
    print("=" * 80)

    print("Per-PMID summary")
    print("-" * 80)

    for row in summaries:
        print(
            f"{row['pmid']} | "
            f"source={row['text_source']} | "
            f"abstract={row['has_abstract']} | "
            f"full_text={row['has_full_text']} | "
            f"pmc={row['pmc_id']} | "
            f"paperclip={row['paperclip_status']} | "
            f"title_chars={row['title_chars']} | "
            f"abstract_chars={row['abstract_chars']} | "
            f"full_text_chars={row['full_text_chars']} | "
            f"document_chars={row['document_text_chars']}"
        )

    if audit["errors"]:
        print("=" * 80)
        print("ERRORS")
        print("-" * 80)

        for error in audit["errors"]:
            print(
                f"{error.get('pmid')} | "
                f"{error.get('error_type')}: {error.get('message')}"
            )


if __name__ == "__main__":
    main()