"""
CLI runner : corrige study_country dans les sorties population_extractor deja
produites (variantes non fusionnees : USA/US/U.S./United States, UK/England/
Scotland, Netherlands/The Netherlands, Korea/South Korea/Republic of Korea).
Aucun appel LLM.

Usage :
    python -m src.runners.renormalize_population_outputs
    python -m src.runners.renormalize_population_outputs --dry-run
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.config.paths import paths
from src.agents.population_extractor import normalize_country_value


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Re-normalise study_country dans les sorties population_extractor deja produites (pas d'appel LLM)."
    )
    parser.add_argument(
        "--output-dir",
        default=str(paths.population_output_dir),
        help="Dossier des sorties population_extractor a corriger.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Affiche ce qui changerait sans reecrire les fichiers.",
    )

    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    files = sorted(output_dir.glob("*_population.json"))

    print(f"Fichiers trouves : {len(files)}")

    changed = 0
    unchanged = 0

    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))

        before = payload.get("study_country", "not_reported")
        after = normalize_country_value(before)

        if after != before:
            changed += 1
            print(f"  {payload.get('pmid')} : {before!r} -> {after!r}")

            if not args.dry_run:
                payload["study_country"] = after
                payload.setdefault("metadata", {})["renormalized"] = True

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
    if args.dry_run:
        print("(dry-run : aucun fichier reellement modifie)")


if __name__ == "__main__":
    main()