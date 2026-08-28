#!/usr/bin/env python3
"""Chapitre 3, étage 1 (partie b) — fenêtres 24 h et annuelles."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stage_bph.config import load_project_config  # noqa: E402
from stage_bph.exposure_windows import generate_exposure_windows  # noqa: E402


def _default_exposure_path(output_dir: Path) -> Path:
    gz = output_dir / "individual_exposures.csv.gz"
    plain = output_dir / "individual_exposures.csv"
    return gz if gz.exists() else plain


def main() -> None:
    parser = argparse.ArgumentParser(description="Chapitre 3 — fenêtres d'exposition 24h/annuelles.")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs")
    parser.add_argument("--input", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--plain-csv", action="store_true")
    args = parser.parse_args()

    config = load_project_config(ROOT)
    input_path = args.input or _default_exposure_path(args.output_dir)
    output_path = args.output or args.output_dir / ("exposure_windows.csv" if args.plain_csv else "exposure_windows.csv.gz")
    if not input_path.exists():
        raise FileNotFoundError(input_path)

    report = generate_exposure_windows(config, input_path, output_path, gzip_output=not args.plain_csv)
    report["output_path"] = str(output_path)
    print("=== ÉTAPE 4/6 — FENÊTRES D'EXPOSITION TERMINÉES ===")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
