#!/usr/bin/env python3
"""Chapitre 3, étage 2 — couche de trajectoire longitudinale.

Étage nouvellement ajouté au pipeline : calcule, pour chaque flux
(individu × polluant × échelle), l'historique de son exposition —
cumul, répétition, tendance — indépendamment de toute catégorie ICD.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stage_bph.exposure_trajectory import generate_exposure_trajectory  # noqa: E402


def _existing(output_dir: Path, name: str) -> Path:
    gz = output_dir / f"{name}.csv.gz"
    plain = output_dir / f"{name}.csv"
    return gz if gz.exists() else plain


def main() -> None:
    parser = argparse.ArgumentParser(description="Chapitre 3, étage 2 — trajectoire longitudinale.")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs")
    parser.add_argument("--thresholds", type=Path, default=None)
    parser.add_argument("--windows", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--plain-csv", action="store_true")
    args = parser.parse_args()

    thresholds_path = args.thresholds or _existing(args.output_dir, "exposure_thresholds")
    windows_path = args.windows or _existing(args.output_dir, "exposure_windows")
    output_path = args.output or args.output_dir / ("exposure_trajectory.csv" if args.plain_csv else "exposure_trajectory.csv.gz")
    if not thresholds_path.exists():
        raise FileNotFoundError(thresholds_path)
    if not windows_path.exists():
        raise FileNotFoundError(windows_path)

    report = generate_exposure_trajectory(
        thresholds_path, windows_path, output_path, gzip_output=not args.plain_csv,
    )
    report["output_path"] = str(output_path)
    print("=== ÉTAPE 6/7 — TRAJECTOIRE LONGITUDINALE TERMINÉE ===")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
