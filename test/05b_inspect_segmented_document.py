#!/usr/bin/env python3
"""
Inspecte un document segmenté avant extraction LLM.

Exemple:
    python pipeline/05b_inspect_segmented_document.py --pmid 20123607

Entrée:
    data/prototype/segmented_documents/{pmid}_segmented.json
"""

import argparse
import json
from pathlib import Path


SEGMENTED_DIR = Path("data/prototype/segmented_documents")


def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Missing segmented file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def preview(text: str, n: int = 500) -> str:
    text = " ".join(str(text).split())
    if len(text) <= n:
        return text
    return text[:n] + "..."


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect segmented document.")
    parser.add_argument("--pmid", required=True, help="PMID to inspect")
    parser.add_argument(
        "--preview-chars",
        type=int,
        default=500,
        help="Number of preview chars per section",
    )

    args = parser.parse_args()

    path = SEGMENTED_DIR / f"{args.pmid}_segmented.json"
    doc = load_json(path)

    print("=" * 100)
    print(f"SEGMENTED DOCUMENT INSPECTION — PMID {args.pmid}")
    print("=" * 100)

    print("\nDOCUMENT PARTS")
    print("-" * 100)
    for key, value in doc["document_parts"].items():
        print(f"{key}: {value}")

    print("\nSEGMENTATION STATS")
    print("-" * 100)
    for key, value in doc["segmentation_stats"].items():
        print(f"{key}: {value}")

    print("\nCTD CONTEXT")
    print("-" * 100)
    ctd = doc.get("ctd_context", {})
    for key in [
        "source_pollutant",
        "stressor_agent",
        "stressor_agent_primary",
        "receptors",
        "receptors_primary",
        "outcome_ctd",
        "outcome_ctd_primary",
        "country",
        "country_primary",
    ]:
        print(f"{key}: {ctd.get(key, '')}")

    print("\nPUBMED")
    print("-" * 100)
    pubmed = doc.get("pubmed", {})
    print(f"title: {pubmed.get('title', '')}")
    print(f"year: {pubmed.get('year', '')}")
    print(f"journal: {pubmed.get('journal', '')}")
    print(f"doi: {pubmed.get('doi', '')}")
    print(f"pmc_id: {pubmed.get('pmc_id', '')}")

    print("\nSECTIONS DETECTED")
    print("-" * 100)
    sections = doc.get("sections", [])
    for s in sections:
        print(
            f"{s.get('section_id')} | "
            f"{s.get('section_type')} | "
            f"{s.get('chars')} chars | "
            f"{s.get('heading')}"
        )

    print("\nFOCUS SECTIONS")
    print("-" * 100)
    focus_sections = doc.get("focus_sections", [])
    for f in focus_sections:
        print(
            f"{f.get('focus_id')} | "
            f"{f.get('section_type')} | "
            f"{f.get('chars')} chars | "
            f"{f.get('heading')}"
        )
        hits = f.get("keyword_hits", {})

        if isinstance(hits, dict):
            pollutant_hits = hits.get("pollutant_hits", [])
            effect_hits = hits.get("effect_hits", [])
            association_hits = hits.get("association_hits", [])

            if pollutant_hits:
                print(f"  pollutant_hits: {pollutant_hits[:10]}")
            if effect_hits:
                print(f"  effect_hits: {effect_hits[:10]}")
            if association_hits:
                print(f"  association_hits: {association_hits[:10]}")

        elif isinstance(hits, list):
            if hits:
                print(f"  keyword_hits: {hits[:10]}")
        print(f"  preview: {preview(f.get('text', ''), args.preview_chars)}")
        print("-" * 100)

    print("\nFOCUS CHUNKS")
    print("-" * 100)
    chunks = doc.get("focus_chunks", [])
    for c in chunks:
        print(
            f"{c.get('chunk_id')} | "
            f"{c.get('chars')} chars | "
            f"{c.get('start_char')}–{c.get('end_char')}"
        )

    print("=" * 100)


if __name__ == "__main__":
    main()