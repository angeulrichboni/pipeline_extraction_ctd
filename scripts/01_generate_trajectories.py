#!/usr/bin/env python3
"""Chapitre 3, étage 1 (partie a) — simulation résidentielle.

Génère les concentrations de logement et les expositions individuelles
sur la période complète (par défaut) ou un nombre de jours limité (--days,
pour test rapide).
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stage_bph.config import load_project_config  # noqa: E402
from stage_bph.generator import generate_trajectories  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Génère les concentrations des logements et les expositions individuelles."
    )
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs")
    parser.add_argument(
        "--days", type=int, default=None,
        help="Limiter le nombre de jours pour un test. Omettre pour les cinq années complètes.",
    )
    parser.add_argument("--plain-csv", action="store_true", help="Désactiver gzip.")
    parser.add_argument("--strict-provenance", action="store_true")
    parser.add_argument("--log-every-days", type=int, default=90)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    config = load_project_config(ROOT)
    end = None
    if args.days is not None:
        if args.days <= 0:
            raise SystemExit("--days doit être positif.")
        end = config.start_datetime + timedelta(days=args.days) - timedelta(minutes=15)
    report = generate_trajectories(
        config, args.output_dir,
        end_datetime=end, gzip_output=not args.plain_csv,
        log_every_days=args.log_every_days, strict_provenance=args.strict_provenance,
    )
    print("\n=== ÉTAPE 1/6 — TRAJECTOIRES TERMINÉES ===")
    for key, value in report["counts"].items():
        print(f"{key}: {value}")
    print(f"Rapport: {args.output_dir / 'quality_report.json'}")


if __name__ == "__main__":
    main()
