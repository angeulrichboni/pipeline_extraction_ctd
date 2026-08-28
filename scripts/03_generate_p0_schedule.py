#!/usr/bin/env python3
"""Chapitre 2 — calendrier individuel des risques de base p0."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stage_bph.config import load_project_config  # noqa: E402
from stage_bph.p0_schedule import generate_p0_schedule  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Chapitre 2 — calendrier p0 individuel.")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs")
    args = parser.parse_args()

    config = load_project_config(ROOT)
    output = args.output_dir / "individual_p0_schedule.csv"
    count = generate_p0_schedule(config, output)
    print("=== ÉTAPE 3/6 — CALENDRIER p0 TERMINÉ ===")
    print(f"{count} règles individuelles écrites dans {output}")


if __name__ == "__main__":
    main()
