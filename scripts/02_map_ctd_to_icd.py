#!/usr/bin/env python3
"""Chapitre 1 — Mapping CTD vers ICD-10 (OMS, release 2019).

Remplace l'ancien sous-projet zippé icd_mapping_final_2026_01 : le moteur
de mapping vit maintenant dans stage_bph.icd_mapping, comme un module du
pipeline unique, et non plus comme un projet séparé.

Le moteur applique une règle spécifique au PMID en priorité, puis une
règle générale pour l'outcome. Aucune règle de chapitrage par mots-clés :
toute décision provient de config/icd_mapping_reference.csv (545 règles
auditées), jamais d'une heuristique lexicale.

Cible ICD-10 directe (plus de passage par ICD-11) : les codes/chapitres
de la référence ont été traduits depuis l'ancienne cible ICD-11 via les
tables de correspondance officielles de l'OMS (lookup code-à-code pour
les règles à code précis, pont chapitre officiel sinon). Voir
docs/reference/icd11_to_icd10_migration_report.csv pour le détail
ligne par ligne de cette traduction.
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stage_bph.icd_mapping.engine import OUTPUT_FIELDS, apply_mapping  # noqa: E402
from stage_bph.icd_mapping.reference import load_reference, validate_reference  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Chapitre 1 — mapping CTD → ICD-10.")
    parser.add_argument("--input", type=Path, required=True, help="Fichier CTD brut (ctd_extraction.csv).")
    parser.add_argument("--reference", type=Path, default=ROOT / "config" / "icd_mapping_reference.csv")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs")
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
    chapter_counts = Counter(row["icd_chapter"] for row in pm_rows if row["icd_chapter"])
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

    print("=== ÉTAPE 2/6 — MAPPING CTD → ICD-10 TERMINÉ ===")
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
