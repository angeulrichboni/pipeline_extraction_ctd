#!/usr/bin/env python3
"""Chapitre 5 (nouveau) — sous-graphe mecanistique statique polluant -> gene -> maladie/phenotype."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stage_bph.mechanistic_subgraph import build_mechanistic_subgraph  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Construit les triplets mecanistiques statiques (gene, phenotype) a partir de "
                    "ctd_icd_mapped_complete.csv (sortie du chapitre 1)."
    )
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs")
    parser.add_argument("--ctd", type=Path, default=None, help="Sortie de l'etape 2 (ctd_icd_mapped_complete.csv).")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--gzip", action="store_true", help="Compresser la sortie en .csv.gz")
    args = parser.parse_args()

    ctd_path = args.ctd or args.output_dir / "ctd_icd_mapped_complete.csv"
    output_path = args.output or args.output_dir / (
        "mechanistic_subgraph_triplets.csv.gz" if args.gzip else "mechanistic_subgraph_triplets.csv"
    )

    if not ctd_path.exists():
        raise FileNotFoundError(
            f"CTD/ICD introuvable : {ctd_path}. Lancer d'abord scripts/02_map_ctd_to_icd.py, "
            "ou passer --ctd /chemin/vers/fichier.csv"
        )

    report = build_mechanistic_subgraph(
        ctd_path=ctd_path,
        output_path=output_path,
        gzip_output=args.gzip,
    )
    print("=== CHAPITRE 5 — SOUS-GRAPHE MÉCANISTIQUE TERMINÉ ===")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()