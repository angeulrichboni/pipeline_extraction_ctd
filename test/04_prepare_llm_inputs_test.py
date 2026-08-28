#!/usr/bin/env python3
"""
Prépare les inputs LLM du prototype.

Entrée:
    data/prototype/paperclip/documents_manifest_test_with_paperclip.csv

Sorties:
    data/prototype/llm_inputs/{pmid}.json
    data/prototype/llm_inputs/llm_inputs_test.jsonl
    data/prototype/llm_inputs/llm_inputs_manifest_test.csv
    data/prototype/llm_inputs/llm_inputs_audit_test.json

Objectif:
    Construire un document JSON propre par PMID en combinant:
        - contexte CTD
        - métadonnées PubMed
        - abstract PubMed
        - full text Paperclip si disponible

Décision:
    Aucun appel LLM ici.
    Ce script prépare seulement les entrées du futur système multi-agents LangGraph.
"""

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------

PROTOTYPE_DIR = Path("data/prototype")

DEFAULT_INPUT_MANIFEST = (
    PROTOTYPE_DIR
    / "paperclip"
    / "documents_manifest_test_with_paperclip.csv"
)

OUT_DIR = PROTOTYPE_DIR / "llm_inputs"
OUT_JSONL = OUT_DIR / "llm_inputs_test.jsonl"
OUT_MANIFEST = OUT_DIR / "llm_inputs_manifest_test.csv"
OUT_AUDIT = OUT_DIR / "llm_inputs_audit_test.json"

OUT_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------
# Utilitaires
# ---------------------------------------------------------------------

def safe_str(value: Any) -> str:
    if value is None:
        return ""

    value = str(value)

    if value.lower() == "nan":
        return ""

    return value.strip()


def parse_bool(value: Any) -> bool:
    value = safe_str(value).lower()

    if value in {"true", "1", "yes", "y"}:
        return True

    if value in {"false", "0", "no", "n", ""}:
        return False

    return False


def read_text_file(path_value: Any) -> str:
    path_str = safe_str(path_value)

    if not path_str:
        return ""

    path = Path(path_str)

    if not path.exists():
        return ""

    return path.read_text(encoding="utf-8", errors="replace").strip()


def json_loads_if_possible(value: Any) -> Any:
    """
    Certaines colonnes PubMed comme authors, mesh_terms, keywords peuvent être
    stockées comme chaînes JSON dans le CSV.
    """
    text = safe_str(value)

    if not text:
        return []

    try:
        return json.loads(text)
    except Exception:
        return text


def compact_whitespace(text: str) -> str:
    """
    Nettoyage léger, sans modifier le contenu scientifique.
    """
    lines = []

    for line in text.splitlines():
        line = line.strip()
        if line:
            lines.append(line)

    return "\n".join(lines).strip()


def build_ctd_context(row: pd.Series) -> dict[str, Any]:
    return {
        "source_pollutant": safe_str(row.get("source_pollutant")),
        "source_file": safe_str(row.get("source_file")),

        "stressor_agent": safe_str(row.get("stressor_agent")),
        "stressor_agent_primary": safe_str(row.get("stressor_agent_primary")),

        "receptors": safe_str(row.get("receptors")),
        "receptors_primary": safe_str(row.get("receptors_primary")),

        "outcome_ctd": safe_str(row.get("outcome_ctd")),
        "outcome_ctd_primary": safe_str(row.get("outcome_ctd_primary")),

        "country": safe_str(row.get("country")),
        "country_primary": safe_str(row.get("country_primary")),

        "medium": safe_str(row.get("medium")),
        "exposure_marker": safe_str(row.get("exposure_marker")),
        "anatomy": safe_str(row.get("anatomy")),

        "associated_study_title_ctd": safe_str(
            row.get("associated_study_title_ctd")
        ),
        "author_summary_ctd": safe_str(row.get("author_summary_ctd")),
    }


def build_pubmed_context(row: pd.Series) -> dict[str, Any]:
    abstract = safe_str(row.get("abstract"))

    return {
        "title": safe_str(row.get("title")),
        "year": safe_str(row.get("year")),
        "journal": safe_str(row.get("journal")),
        "doi": safe_str(row.get("doi")),
        "pmc_id": safe_str(row.get("pmc_id")),

        "abstract": abstract,
        "has_abstract": bool(abstract),

        "authors": json_loads_if_possible(row.get("authors")),
        "mesh_terms": json_loads_if_possible(row.get("mesh_terms")),
        "keywords": json_loads_if_possible(row.get("keywords")),
        "publication_types": json_loads_if_possible(
            row.get("publication_types")
        ),

        "pubmed_status": safe_str(row.get("pubmed_status")),
    }


def build_paperclip_context(row: pd.Series, full_text: str) -> dict[str, Any]:
    paperclip_status = safe_str(row.get("paperclip_status"))
    full_text_path = safe_str(row.get("full_text_path"))

    return {
        "paperclip_attempted": parse_bool(row.get("paperclip_attempted")),
        "paperclip_status": paperclip_status,
        "has_full_text": bool(full_text),
        "full_text_path": full_text_path,
        "raw_content_path": safe_str(row.get("raw_content_path")),
        "paperclip_content_chars": len(full_text),
    }


def build_document_text(
    title: str,
    abstract: str,
    full_text: str,
) -> tuple[str, str]:
    """
    Construit le texte documentaire analysable.

    Si full text disponible:
        document_text = title + abstract PubMed + full text Paperclip

    Sinon:
        document_text = title + abstract PubMed

    Retour:
        document_text, text_source
    """
    parts = []

    if title:
        parts.append("### TITLE\n" + title)

    if abstract:
        parts.append("### PUBMED ABSTRACT\n" + abstract)

    if full_text:
        parts.append("### PAPERCLIP FULL TEXT\n" + full_text)
        text_source = "full_text"
    else:
        text_source = "abstract_only"

    document_text = "\n\n".join(parts).strip()
    document_text = compact_whitespace(document_text)

    return document_text, text_source


def build_llm_input(row: pd.Series) -> dict[str, Any]:
    pmid = safe_str(row.get("pmid"))

    if not pmid:
        raise ValueError("Missing PMID in manifest row.")

    full_text = read_text_file(row.get("full_text_path"))

    ctd_context = build_ctd_context(row)
    pubmed = build_pubmed_context(row)
    paperclip = build_paperclip_context(row, full_text)

    document_text, text_source = build_document_text(
        title=pubmed["title"],
        abstract=pubmed["abstract"],
        full_text=full_text,
    )

    payload = {
        "pmid": pmid,
        "created_at": datetime.now().isoformat(timespec="seconds"),

        "ctd_context": ctd_context,
        "pubmed": pubmed,
        "paperclip": paperclip,

        "text_source": text_source,
        "document_text": document_text,

        "stats": {
            "title_chars": len(pubmed["title"]),
            "abstract_chars": len(pubmed["abstract"]),
            "full_text_chars": len(full_text),
            "document_text_chars": len(document_text),
        },

        "llm_processing_plan": {
            "intended_pipeline": "LangGraph multi-agent extraction",
            "agents": [
                "document_parser",
                "pollutant_extractor",
                "outcome_extractor",
                "effect_measure_extractor",
                "exposure_unit_extractor",
                "association_builder",
                "deduplication_agent",
                "quality_control_agent",
            ],
            "output_rule": "one scientific association = one row",
            "non_significant_results": "keep",
            "deduplication_rule": (
                "merge only if scientific key fields are identical; "
                "otherwise keep as distinct associations"
            ),
        },
    }

    return payload


def write_json(path: Path, obj: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(obj, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False))
            f.write("\n")


def clean_output_dir(fresh: bool) -> None:
    if not fresh:
        return

    for path in OUT_DIR.glob("*.json"):
        path.unlink()

    for path in OUT_DIR.glob("*.jsonl"):
        path.unlink()

    for path in OUT_DIR.glob("*.csv"):
        path.unlink()


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepare prototype LLM inputs."
    )

    parser.add_argument(
        "--manifest",
        default=str(DEFAULT_INPUT_MANIFEST),
        help="Path to documents_manifest_test_with_paperclip.csv",
    )

    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Delete previous LLM input outputs before running.",
    )

    parser.add_argument(
        "--no-document-text-in-jsonl",
        action="store_true",
        help=(
            "Do not include document_text in the JSONL file. "
            "Individual PMID JSON files always include it."
        ),
    )

    args = parser.parse_args()

    manifest_path = Path(args.manifest)

    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing manifest: {manifest_path}")

    clean_output_dir(args.fresh)

    manifest = pd.read_csv(manifest_path, dtype=str).fillna("")

    if "pmid" not in manifest.columns:
        raise ValueError("Input manifest must contain a 'pmid' column.")

    payloads = []
    manifest_rows = []

    for _, row in manifest.iterrows():
        payload = build_llm_input(row)

        pmid = payload["pmid"]
        out_path = OUT_DIR / f"{pmid}.json"

        write_json(out_path, payload)

        payloads.append(payload)

        manifest_rows.append(
            {
                "pmid": pmid,
                "source_pollutant": payload["ctd_context"]["source_pollutant"],
                "stressor_agent_primary": payload["ctd_context"][
                    "stressor_agent_primary"
                ],
                "outcome_ctd_primary": payload["ctd_context"][
                    "outcome_ctd_primary"
                ],
                "receptors_primary": payload["ctd_context"][
                    "receptors_primary"
                ],
                "country_primary": payload["ctd_context"]["country_primary"],

                "title": payload["pubmed"]["title"],
                "year": payload["pubmed"]["year"],
                "journal": payload["pubmed"]["journal"],
                "doi": payload["pubmed"]["doi"],
                "pmc_id": payload["pubmed"]["pmc_id"],

                "text_source": payload["text_source"],
                "has_abstract": payload["pubmed"]["has_abstract"],
                "has_full_text": payload["paperclip"]["has_full_text"],
                "paperclip_status": payload["paperclip"][
                    "paperclip_status"
                ],

                "abstract_chars": payload["stats"]["abstract_chars"],
                "full_text_chars": payload["stats"]["full_text_chars"],
                "document_text_chars": payload["stats"][
                    "document_text_chars"
                ],

                "llm_input_path": str(out_path),
            }
        )

    # JSONL compact ou complet
    jsonl_rows = []

    for payload in payloads:
        if args.no_document_text_in_jsonl:
            compact = payload.copy()
            compact.pop("document_text", None)
            jsonl_rows.append(compact)
        else:
            jsonl_rows.append(payload)

    write_jsonl(OUT_JSONL, jsonl_rows)

    out_manifest_df = pd.DataFrame(manifest_rows)
    out_manifest_df.to_csv(OUT_MANIFEST, index=False)

    audit = {
        "run_date": datetime.now().isoformat(timespec="seconds"),
        "input_manifest": str(manifest_path),
        "n_inputs": len(payloads),

        "with_abstract": int(
            sum(p["pubmed"]["has_abstract"] for p in payloads)
        ),
        "with_full_text": int(
            sum(p["paperclip"]["has_full_text"] for p in payloads)
        ),
        "abstract_only": int(
            sum(p["text_source"] == "abstract_only" for p in payloads)
        ),

        "min_document_text_chars": int(
            min(p["stats"]["document_text_chars"] for p in payloads)
        ) if payloads else 0,
        "max_document_text_chars": int(
            max(p["stats"]["document_text_chars"] for p in payloads)
        ) if payloads else 0,
        "avg_document_text_chars": (
            sum(p["stats"]["document_text_chars"] for p in payloads)
            / max(1, len(payloads))
        ),

        "outputs": {
            "llm_inputs_dir": str(OUT_DIR),
            "jsonl": str(OUT_JSONL),
            "manifest": str(OUT_MANIFEST),
            "audit": str(OUT_AUDIT),
        },

        "next_step": (
            "Test document segmentation, then LangGraph multi-agent "
            "extraction on 1-2 PMIDs."
        ),
    }

    write_json(OUT_AUDIT, audit)

    print("=" * 80)
    print("LLM INPUT PREPARATION COMPLETE")
    print("=" * 80)
    print(json.dumps(audit, indent=2, ensure_ascii=False))
    print("=" * 80)


if __name__ == "__main__":
    main()