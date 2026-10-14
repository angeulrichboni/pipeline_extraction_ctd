"""
Compare empiriquement plusieurs configurations (chunk_size, overlap) sur de
vrais articles longs, pour justifier le choix de segmentation par un
resultat mesure plutot que par un principe general.

Methode : pour chaque article et chaque configuration testee, le texte brut
est redecoupe en fenetres glissantes de taille chunk_size (en caracteres)
avec le chevauchement donne (decoupage simple, sans tenir compte des
sections -- volontairement, pour isoler l'effet de la taille/chevauchement
independamment du decoupage par section deja utilise en production). Le
Pollutant Extractor (reel, importe depuis le projet) est lance en
Map-Reduce sur chaque chunk, puis les resultats sont fusionnes/dedupliques
avec la meme fonction que celle utilisee en production.

Usage :
    python3 12_chunk_size_comparison.py --pmids 20123607,17938744 \
        --configs 4000:250,8000:500,12000:750

Source du texte brut (dans cet ordre de priorite) :
    1. data/processed/llm_inputs/llm_inputs.jsonl (si present)
    2. reconstruction a partir des focus_chunks deja segmentes
       (data/processed/segmented_documents/{pmid}_segmented.json)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.config.paths import paths
from src.config.settings import settings
from src.llm.client import ILAASClient
from src.agents.pollutant_extractor import build_pollutant_prompt, normalize_pollutant_payload

DATA_ROOT = Path("data/processed")  # ajuster si CTD_DATA_ROOT differe


def load_raw_text_from_llm_inputs(pmid: str) -> str | None:
    path = DATA_ROOT / "llm_inputs" / "llm_inputs.jsonl"

    if not path.exists():
        return None

    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue

            if str(row.get("pmid", "")) != str(pmid):
                continue

            for key in ["text", "full_text", "document_text", "content"]:
                if row.get(key):
                    return str(row[key])

    return None


def load_raw_text_from_segmented(pmid: str) -> str | None:
    path = paths.segmented_document_path(pmid)

    if not path.exists():
        return None

    payload = json.loads(path.read_text(encoding="utf-8"))

    parts = []

    title = payload.get("title") or payload.get("article_title") or ""
    abstract = payload.get("abstract") or ""

    if title:
        parts.append(str(title))
    if abstract:
        parts.append(str(abstract))

    for key in ["focus_chunks", "chunks", "selected_chunks", "full_text_chunks"]:
        value = payload.get(key)
        if isinstance(value, list) and value:
            for item in value:
                text = item.get("chunk_text") or item.get("text") or ""
                if text:
                    parts.append(str(text))
            break

    if not parts:
        return None

    return "\n\n".join(parts)


def load_raw_text(pmid: str) -> tuple[str, str]:
    """Renvoie (texte, source_utilisee)."""
    text = load_raw_text_from_llm_inputs(pmid)
    if text:
        return text, "llm_inputs.jsonl"

    text = load_raw_text_from_segmented(pmid)
    if text:
        return text, "segmented_documents (reconstruit depuis focus_chunks -- "\
                      "peut contenir de legeres duplications aux frontieres de chevauchement)"

    raise FileNotFoundError(f"Aucun texte brut trouve pour le PMID {pmid}.")


def sliding_window_chunks(text: str, chunk_size: int, overlap: int) -> list[str]:
    if overlap >= chunk_size:
        raise ValueError("overlap doit etre strictement inferieur a chunk_size.")

    chunks = []
    start = 0
    step = chunk_size - overlap

    while start < len(text):
        chunk = text[start : start + chunk_size]
        if chunk.strip():
            chunks.append(chunk)
        start += step

    return chunks


def run_config_on_pmid(
    pmid: str,
    text: str,
    chunk_size: int,
    overlap: int,
    client: ILAASClient,
    model: str,
    max_output_tokens: int,
) -> dict[str, Any]:
    chunks = sliding_window_chunks(text, chunk_size, overlap)

    combined_pollutants: list[Any] = []
    n_failed_chunks = 0

    for chunk_index, chunk_text in enumerate(chunks, start=1):
        messages = build_pollutant_prompt(pmid=pmid, document_text=chunk_text)

        try:
            parsed_payload, _first_response, _repair_response = client.chat_json(
                messages=messages,
                model=model,
                max_tokens=max_output_tokens,
                temperature=0.0,
                repair_on_fail=True,
            )
        except Exception as exc:
            # Un chunk qui echoue (ex. raisonnement du modele trop long,
            # tronque avant la fin du JSON) ne doit pas faire perdre les
            # resultats des autres chunks de cette configuration.
            n_failed_chunks += 1
            print(f"    [!] chunk {chunk_index}/{len(chunks)} : echec ({type(exc).__name__}), ignore")
            continue

        combined_pollutants.extend(parsed_payload.get("pollutants_found", []))

    normalized = normalize_pollutant_payload({
        "pollutants_found": combined_pollutants,
        "warnings": [],
        "errors": [],
    })

    unique_pollutants = {
        item.get("pollutant_specific") for item in normalized["pollutants_found"]
    }

    return {
        "pmid": pmid,
        "chunk_size": chunk_size,
        "overlap": overlap,
        "n_chunks": len(chunks),
        "n_chunks_failed": n_failed_chunks,
        "n_pollutants_unique": len(unique_pollutants),
        "pollutants": sorted(p for p in unique_pollutants if p),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pmids", required=True, help="PMIDs separes par virgule (articles longs de preference).")
    parser.add_argument(
        "--configs", default="4000:250,8000:500,12000:750",
        help="Configurations a tester, format chunk_size:overlap separees par virgule.",
    )
    parser.add_argument("--model", default=settings.ilaas_model)
    parser.add_argument(
        "--max-output-tokens", type=int, default=6000,
        help="Limite de tokens de sortie par appel (defaut 6000 -- le raisonnement CoT peut "
             "occasionnellement devenir verbeux sur des decisions de categorisation ambigues).",
    )
    args = parser.parse_args()

    pmids = [p.strip() for p in args.pmids.split(",") if p.strip()]

    configs = []
    for raw in args.configs.split(","):
        size_str, overlap_str = raw.split(":")
        configs.append((int(size_str), int(overlap_str)))

    client = ILAASClient(model=args.model, temperature=0.0, max_tokens=args.max_output_tokens)

    results = []

    for pmid in pmids:
        text, source = load_raw_text(pmid)
        print(f"PMID {pmid} : {len(text)} caracteres (source : {source})")

        for chunk_size, overlap in configs:
            result = run_config_on_pmid(
                pmid, text, chunk_size, overlap, client, args.model, args.max_output_tokens
            )
            results.append(result)
            failed_note = f", {result['n_chunks_failed']} echec(s)" if result["n_chunks_failed"] else ""
            print(
                f"  chunk_size={chunk_size:6d} overlap={overlap:4d} -> "
                f"{result['n_chunks']:3d} chunks{failed_note}, {result['n_pollutants_unique']:2d} polluants uniques"
            )

    print()
    print("=" * 100)
    print("RESUME PAR CONFIGURATION (moyenne sur tous les PMIDs testes)")
    print("=" * 100)

    for chunk_size, overlap in configs:
        subset = [r for r in results if r["chunk_size"] == chunk_size and r["overlap"] == overlap]
        avg_chunks = sum(r["n_chunks"] for r in subset) / len(subset)
        avg_pollutants = sum(r["n_pollutants_unique"] for r in subset) / len(subset)
        print(
            f"chunk_size={chunk_size:6d} overlap={overlap:4d} -> "
            f"{avg_chunks:.1f} chunks en moyenne, {avg_pollutants:.1f} polluants uniques en moyenne"
        )

    out_path = Path("chunk_size_comparison_results.json")
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nResultats detailles sauvegardes : {out_path.resolve()}")


if __name__ == "__main__":
    main()