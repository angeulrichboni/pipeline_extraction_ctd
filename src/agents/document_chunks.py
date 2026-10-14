"""Prépare les segments documentaires transmis aux extracteurs LLM.

Chaque segment produit par ``run_document_segmentation`` est envoyé séparément
au modèle. Les résultats d'un même PMID sont ensuite réunis et dédupliqués par
l'extracteur appelant. Ce traitement couvre le document complet tout en gardant
des requêtes bornées et des preuves textuelles rattachées à leur segment.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def extract_title_and_abstract(payload: dict[str, Any]) -> tuple[str, str]:
    metadata = payload.get("metadata") or {}

    title = (
        payload.get("title")
        or payload.get("article_title")
        or payload.get("document_title")
        or metadata.get("title")
        or ""
    )

    abstract = (
        payload.get("abstract")
        or payload.get("pubmed_abstract")
        or metadata.get("abstract")
        or ""
    )

    return str(title).strip(), str(abstract).strip()


def extract_document_chunks(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Renvoie la liste des chunks deja produits par la segmentation.

    Repli sur un chunk synthetique unique (titre + abstract) si le document
    n'a pas de texte complet segmente (cas abstract-only)."""

    for key in ["focus_chunks", "chunks", "selected_chunks", "full_text_chunks"]:
        value = payload.get(key)

        if not isinstance(value, list) or not value:
            continue

        chunks: list[dict[str, Any]] = []

        for index, item in enumerate(value, start=1):
            if not isinstance(item, dict):
                continue

            text = str(item.get("chunk_text") or item.get("text") or "").strip()

            if not text:
                continue

            chunks.append(
                {
                    "chunk_index": item.get("chunk_index", index),
                    "section_title": str(item.get("section_title") or "unknown_section"),
                    "chunk_text": text,
                }
            )

        if chunks:
            return chunks

    title, abstract = extract_title_and_abstract(payload)

    fallback_parts = []

    if title:
        fallback_parts.append(f"[TITLE]\n{title}")

    if abstract:
        fallback_parts.append(f"[ABSTRACT]\n{abstract}")

    fallback_text = "\n\n".join(fallback_parts).strip()

    if not fallback_text:
        return []

    return [
        {
            "chunk_index": 1,
            "section_title": "abstract_only",
            "chunk_text": fallback_text,
        }
    ]


def build_chunk_text_with_context(
    title: str,
    abstract: str,
    chunk: dict[str, Any],
) -> str:
    """Prefixe chaque chunk avec titre + abstract (petits, toujours utiles
    pour le contexte) avant de l'envoyer au LLM."""

    parts = []

    if title:
        parts.append(f"[TITLE]\n{title}")

    if abstract:
        parts.append(f"[ABSTRACT]\n{abstract}")

    parts.append(f"[SECTION: {chunk['section_title']}]\n{chunk['chunk_text']}")

    return "\n\n".join(parts)


def write_reasoning_file(
    reasoning_dir: Path,
    pmid: str,
    agent_name: str,
    entries: list[dict[str, Any]],
) -> str:
    """Ecrit le raisonnement CoT de chaque chunk dans un fichier a part,
    nomme explicitement par PMID et par agent -- jamais melange avec la
    sortie structuree propre consommee par le reste du pipeline."""

    if not entries:
        return ""

    reasoning_dir.mkdir(parents=True, exist_ok=True)
    path = reasoning_dir / f"{pmid}_{agent_name}_reasoning.json"

    path.write_text(
        json.dumps(
            {"pmid": pmid, "agent": agent_name, "chunks": entries},
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    return str(path)
