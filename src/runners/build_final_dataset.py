"""
CLI runner : fusion finale. Derniere etape du pipeline (voir README section
4.15). Remplace la fusion manuelle faite jusqu'ici dans fusion_data.ipynb par
un runner testable et rejouable.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from src.preprocessing.final_dataset_merge import build_final_dataset

DATA_ROOT = Path(os.getenv("CTD_DATA_ROOT", "data/processed_full"))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fusionne les associations enrichies CTD avec population/localisation et temporalite d'exposition."
    )

    parser.add_argument(
        "--main-path",
        default=str(DATA_ROOT / "enrichment" / "main_associations_enriched.csv"),
        help="Table d'associations deja enrichie CTD (genes/maladies/phenotypes).",
    )
    parser.add_argument(
        "--population-path",
        default=str(DATA_ROOT / "agent_csv_outputs" / "05_population_location_extractor_output.csv"),
        help="Sortie de export_agent_csv_outputs pour population_extractor (optionnelle).",
    )
    parser.add_argument(
        "--temporal-path",
        default=str(DATA_ROOT / "agent_csv_outputs" / "06_exposure_temporal_extractor_output.csv"),
        help="Sortie de export_agent_csv_outputs pour time_extractor (optionnelle).",
    )
    parser.add_argument(
        "--output-path",
        default=str(DATA_ROOT / "final" / "ctd_extraction_final.csv"),
        help="Table finale consolidee.",
    )

    args = parser.parse_args()

    audit = build_final_dataset(
        main_path=Path(args.main_path),
        population_path=Path(args.population_path),
        temporal_path=Path(args.temporal_path),
        output_path=Path(args.output_path),
    )

    audit_path = Path(args.output_path).with_suffix(".audit.json")
    audit_path.write_text(json.dumps(audit, indent=2, ensure_ascii=False))

    print("=" * 80)
    print("FUSION FINALE")
    print("=" * 80)
    for key, value in audit.items():
        print(f"{key:32s} {value}")
    print(f"\nAudit : {audit_path}")


if __name__ == "__main__":
    main()