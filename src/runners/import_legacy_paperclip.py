"""
CLI runner : recupere des textes complets Paperclip deja telecharges lors
d'un run precedent (avant la refonte de l'architecture), pour les PMIDs
presents dans la nouvelle liste de candidats -- evite de rappeler Paperclip
pour ce qui a deja ete recupere une fois.

Ne fait que copier des fichiers existants sur le disque de l'utilisateur ;
aucun appel reseau. `reuse_existing=True` (deja actif par defaut dans
fetch_paperclip_full_texts) detectera ensuite ces fichiers copies et ne
rappellera pas Paperclip pour les PMIDs concernes.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from src.config.paths import paths
from src.ingestion.pubmed_fetcher import load_pmids

FULL_TEXT_NAME_PATTERNS = [
    "{pmid}.txt",
    "{pmid}_full_text.txt",
    "{pmid}_paperclip_full_text.txt",
]

RAW_NAME_PATTERNS = [
    "{pmid}_content_raw.txt",
    "{pmid}_raw.txt",
]


def find_legacy_file(legacy_dir: Path, pmid: str, patterns: list[str]) -> Path | None:
    for pattern in patterns:
        candidate = legacy_dir / pattern.format(pmid=pmid)
        if candidate.exists():
            return candidate

    return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Copie les full texts Paperclip deja recuperes lors d'un run "
            "precedent, pour les PMIDs de la nouvelle liste de candidats."
        )
    )

    parser.add_argument(
        "--legacy-full-text-dir",
        required=True,
        help="Ancien dossier paperclip/full_texts (avant refonte).",
    )
    parser.add_argument(
        "--legacy-raw-dir",
        default=None,
        help="Ancien dossier paperclip/raw (optionnel).",
    )
    parser.add_argument(
        "--pmid-input",
        required=True,
        help="Fichier txt/csv/jsonl/json contenant les PMIDs a recuperer (ex. pm_exposure_candidates.csv).",
    )
    parser.add_argument(
        "--full-text-dir",
        default=str(paths.processed_dir / "paperclip" / "full_texts"),
    )
    parser.add_argument(
        "--raw-dir",
        default=str(paths.processed_dir / "paperclip" / "raw"),
    )

    args = parser.parse_args()

    pmids = load_pmids(Path(args.pmid_input))

    full_text_dir = Path(args.full_text_dir)
    raw_dir = Path(args.raw_dir)
    full_text_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    legacy_full_text_dir = Path(args.legacy_full_text_dir)
    legacy_raw_dir = Path(args.legacy_raw_dir) if args.legacy_raw_dir else None

    found = 0
    raw_found = 0
    missing: list[str] = []

    for pmid in pmids:
        source = find_legacy_file(legacy_full_text_dir, pmid, FULL_TEXT_NAME_PATTERNS)

        if source is None:
            missing.append(pmid)
            continue

        shutil.copy2(source, full_text_dir / f"{pmid}.txt")
        found += 1

        if legacy_raw_dir is not None:
            raw_source = find_legacy_file(legacy_raw_dir, pmid, RAW_NAME_PATTERNS)
            if raw_source is not None:
                shutil.copy2(raw_source, raw_dir / f"{pmid}_content_raw.txt")
                raw_found += 1

    print("=" * 80)
    print("IMPORT LEGACY PAPERCLIP")
    print("=" * 80)
    print(f"PMIDs demandes                          : {len(pmids)}")
    print(f"Full texts trouves et copies             : {found}")
    print(f"Raw responses trouvees et copiees        : {raw_found}")
    print(f"Manquants (a recuperer via Paperclip)    : {len(missing)}")

    if missing:
        missing_path = full_text_dir.parent / "legacy_paperclip_missing_pmids.txt"
        missing_path.write_text("\n".join(missing))
        print(f"Liste des PMIDs manquants : {missing_path}")


if __name__ == "__main__":
    main()
