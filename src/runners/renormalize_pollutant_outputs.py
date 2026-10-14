"""Normalise à nouveau les fichiers du pollutant extractor.

La commande relit les objets existants, applique
``normalize_pollutant_payload`` et regroupe les variantes de notation d'un
même polluant, par exemple ``PM(2.5)`` et ``PM2.5``. Aucun appel LLM n'est
réalisé.

Usage :
    python -m src.runners.renormalize_pollutant_outputs
    python -m src.runners.renormalize_pollutant_outputs --dry-run
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.config.paths import paths
from src.agents.pollutant_extractor import normalize_pollutant_payload


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Re-normalise les sorties pollutant_extractor deja produites (pas d'appel LLM)."
    )
    parser.add_argument(
        "--output-dir",
        default=str(paths.pollutant_output_dir),
        help="Dossier des sorties pollutant_extractor a corriger.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Affiche ce qui changerait sans reecrire les fichiers.",
    )

    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    files = sorted(output_dir.glob("*_pollutants.json"))

    print(f"Fichiers trouves : {len(files)}")

    changed = 0
    unchanged = 0
    items_merged = 0
    items_relabeled = 0

    def labels(items: list[dict]) -> list[tuple[str, str]]:
        return [
            (item.get("pollutant_general", ""), item.get("pollutant_specific", ""))
            for item in items
        ]

    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))

        before_items = payload.get("pollutants_found", [])
        before_count = len(before_items)
        before_labels = labels(before_items)

        normalized = normalize_pollutant_payload(
            {
                "pollutants_found": before_items,
                "warnings": payload.get("warnings", []),
                "errors": payload.get("errors", []),
            }
        )

        after_items = normalized["pollutants_found"]
        after_count = len(after_items)
        after_labels = labels(after_items)

        # Change reel si le nombre d'items a bouge (fusion) OU si les
        # etiquettes pollutant_general/pollutant_specific ont change sans
        # fusion (cas d'un item isole, ex. "PM(2.5)" seul dans le fichier).
        merged = before_count - after_count
        relabeled = 0 if merged else int(before_labels != after_labels)

        if merged or relabeled:
            changed += 1
            items_merged += merged
            items_relabeled += relabeled

            if merged:
                print(
                    f"  {payload.get('pmid')} : {before_count} -> {after_count} "
                    f"items ({merged} fusionne(s))"
                )
            else:
                print(f"  {payload.get('pmid')} : etiquette(s) corrigee(s) sans fusion")

            if not args.dry_run:
                payload["pollutants_found"] = after_items
                payload["warnings"] = normalized["warnings"]
                payload["errors"] = normalized["errors"]
                payload.setdefault("metadata", {})["renormalized"] = True
                payload["metadata"]["n_pollutants_found"] = after_count

                path.write_text(
                    json.dumps(payload, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
        else:
            unchanged += 1

    print()
    print("=" * 80)
    print(f"Fichiers modifies   : {changed}")
    print(f"Fichiers inchanges  : {unchanged}")
    print(f"Items fusionnes (total)  : {items_merged}")
    print(f"Fichiers ré-étiquetés sans fusion : {items_relabeled}")
    if args.dry_run:
        print("(dry-run : aucun fichier reellement modifie)")


if __name__ == "__main__":
    main()
