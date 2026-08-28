"""
CLI runner for document segmentation / preprocessing.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from src.config.paths import paths
from src.io.logging_utils import setup_logger
from src.preprocessing.document_segmenter import run_document_segmentation


def get_default_llm_inputs_dir() -> Path:
    return getattr(
        paths,
        "llm_inputs_dir",
        paths.prototype_dir / "llm_inputs",
    )


def get_default_segmented_dir() -> Path:
    return getattr(
        paths,
        "segmented_documents_dir",
        paths.prototype_dir / "segmented_documents",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run document segmentation / preprocessing."
    )

    parser.add_argument(
        "--input-jsonl",
        default=str(get_default_llm_inputs_dir() / "llm_inputs_test.jsonl"),
        help="Input LLM JSONL file.",
    )

    parser.add_argument(
        "--output-dir",
        default=str(get_default_segmented_dir()),
        help="Output segmented documents directory.",
    )

    parser.add_argument(
        "--manifest-csv",
        default=str(
            get_default_segmented_dir() / "segmented_documents_manifest_test.csv"
        ),
        help="Output segmentation manifest CSV.",
    )

    parser.add_argument(
        "--audit-json",
        default=str(
            get_default_segmented_dir() / "segmented_documents_audit_test.json"
        ),
        help="Output segmentation audit JSON.",
    )

    parser.add_argument(
        "--chunk-size",
        type=int,
        default=8000,
        help="Chunk size in characters.",
    )

    parser.add_argument(
        "--chunk-overlap",
        type=int,
        default=500,
        help="Chunk overlap in characters.",
    )

    parser.add_argument(
        "--keep-references",
        action="store_true",
        help="Do not remove references section.",
    )

    args = parser.parse_args()

    paths.ensure_base_dirs()

    input_jsonl = Path(args.input_jsonl)
    output_dir = Path(args.output_dir)
    manifest_csv = Path(args.manifest_csv)
    audit_json = Path(args.audit_json)

    logger = setup_logger(
        name="run_document_segmentation",
        log_file=paths.logs_dir / "run_document_segmentation.log",
    )

    logger.info("=" * 80)
    logger.info("DOCUMENT SEGMENTATION")
    logger.info("=" * 80)
    logger.info(f"Input JSONL: {input_jsonl}")
    logger.info(f"Output dir: {output_dir}")
    logger.info(f"Manifest CSV: {manifest_csv}")
    logger.info(f"Audit JSON: {audit_json}")
    logger.info(f"Chunk size: {args.chunk_size}")
    logger.info(f"Chunk overlap: {args.chunk_overlap}")
    logger.info(f"Remove references: {not args.keep_references}")

    result = run_document_segmentation(
        input_jsonl=input_jsonl,
        output_dir=output_dir,
        manifest_csv=manifest_csv,
        audit_json=audit_json,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
        remove_references=not args.keep_references,
    )

    audit = result["audit"]
    summaries = result["summaries"]

    logger.info("=" * 80)
    logger.info("DOCUMENT SEGMENTATION COMPLETE")
    logger.info("=" * 80)
    logger.info(f"Documents: {audit['n_documents']}")
    logger.info(f"With full text: {audit['with_full_text']}")
    logger.info(f"Abstract only: {audit['abstract_only']}")
    logger.info(f"Total sections detected: {audit['total_sections_detected']}")
    logger.info(f"Total focus sections: {audit['total_focus_sections']}")
    logger.info(f"Total focus chunks: {audit['total_focus_chunks']}")
    logger.info(f"Errors: {len(audit['errors'])}")

    print("=" * 80)
    print("DOCUMENT SEGMENTATION COMPLETE")
    print("=" * 80)
    print(f"Input JSONL: {input_jsonl}")
    print(f"Documents: {audit['n_documents']}")
    print(f"With full text: {audit['with_full_text']}")
    print(f"Abstract only: {audit['abstract_only']}")
    print(f"Total sections detected: {audit['total_sections_detected']}")
    print(f"Total focus sections: {audit['total_focus_sections']}")
    print(f"Total focus chunks: {audit['total_focus_chunks']}")
    print(f"Min focus text chars: {audit['min_focus_text_chars']}")
    print(f"Max focus text chars: {audit['max_focus_text_chars']}")
    print(f"Avg focus text chars: {audit['avg_focus_text_chars']}")
    print(f"Errors: {len(audit['errors'])}")
    print(f"Manifest: {manifest_csv}")
    print(f"Audit: {audit_json}")
    print("=" * 80)

    print("Per-document summary")
    print("-" * 80)

    for row in summaries:
        print(
            f"{row['pmid']} | "
            f"source={row['text_source']} | "
            f"abstract={row['has_abstract']} | "
            f"full_text={row['has_full_text']} | "
            f"sections={row['sections_detected']} | "
            f"focus_sections={row['focus_sections']} | "
            f"focus_chunks={row['focus_chunks']} | "
            f"focus_chars={row['focus_text_chars']}"
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