"""Applique le référentiel ICD-10 aux associations extraites du pipeline.

Le moteur privilégie une règle propre au PMID, puis une règle générale pour
l'outcome normalisé. Toutes les décisions proviennent du référentiel audité
``config/icd_mapping_reference.csv`` ; aucun chapitrage lexical de secours
n'est appliqué.

Les fichiers sont écrits par défaut dans ``data/processed/icd/`` ou dans le
sous-dossier ``icd/`` de ``CTD_DATA_ROOT`` lorsque cette variable est définie.
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from config.paths import paths  # noqa: E402
from icd.engine import OUTPUT_FIELDS, apply_mapping  # noqa: E402
from icd.reference import load_reference, validate_reference  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mapping CTD → ICD-10.")
    parser.add_argument("--input", type=Path, required=True, help="Dataset d’associations à enrichir avec le mapping ICD-10.")
    parser.add_argument("--reference", type=Path, default=ROOT / "config" / "icd_mapping_reference.csv")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=paths.icd_output_dir,
        help=f"Répertoire des sorties ICD-10 (défaut : {paths.icd_output_dir}).",
    )
    parser.add_argument("--strict", action="store_true", help="Échoue si des outcomes PM restent non résolus.")
    return parser.parse_args()


def _write_csv(path: Path, headers: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    conflicts = validate_reference(args.reference)
    _write_csv(args.output_dir / "mapping_conflicts.csv", ["error_type", "rule_id", "message"], conflicts)
    if conflicts:
        print(f"Référence invalide : {len(conflicts)} conflit(s).", file=sys.stderr)
        return 2

    reference, reference_rows = load_reference(args.reference)

    with args.input.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        input_fields = reader.fieldnames or []
        input_rows = list(reader)

    output_rows = [apply_mapping(row, reference) for row in input_rows]
    output_fields = list(input_fields)
    for field in OUTPUT_FIELDS:
        if field not in output_fields:
            output_fields.append(field)

    _write_csv(args.output_dir / "ctd_icd_mapped_complete.csv", output_fields, output_rows)

    pm_rows = [row for row in output_rows if row.get("pollutant_specific") in {"PM2.5", "PM10"}]
    status_counts = Counter(row["mapping_status"] for row in pm_rows)
    unresolved = [row for row in pm_rows if row["mapping_status"] == "UNMAPPED_REVIEW"]
    _write_csv(args.output_dir / "mapping_unresolved.csv", output_fields, unresolved)

    metrics = [
        {"metric": "input_rows", "value": str(len(input_rows))},
        {"metric": "output_rows", "value": str(len(output_rows))},
        {"metric": "pm_rows", "value": str(len(pm_rows))},
        {"metric": "reference_rules", "value": str(len(reference_rows))},
        {"metric": "unresolved_pm_rows", "value": str(len(unresolved))},
    ]
    for status, count in sorted(status_counts.items()):
        metrics.append({"metric": f"pm_status.{status}", "value": str(count)})
    _write_csv(args.output_dir / "mapping_quality_report.csv", ["metric", "value"], metrics)

    print("=== MAPPING CTD → ICD-10 TERMINÉ ===")
    print(f"Lignes entrée / sortie : {len(input_rows):,} / {len(output_rows):,}")
    print(f"Lignes PM               : {len(pm_rows):,}")
    print(f"Règles de référence     : {len(reference_rows):,}")
    print(f"Lignes PM non résolues  : {len(unresolved):,}")
    for status, count in sorted(status_counts.items()):
        print(f"  {status:<24} {count:>8,}")

    if args.strict and unresolved:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
