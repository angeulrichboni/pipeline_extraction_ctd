#!/usr/bin/env python3
"""Chapitre 3, étage 1 (partie b) — dépassements Moyenne / Maximum / MIL."""
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
from stage_bph.exposure_windows import generate_exposure_thresholds  # noqa: E402


def _existing(output_dir: Path, name: str) -> Path:
    gz = output_dir / f"{name}.csv.gz"
    plain = output_dir / f"{name}.csv"
    return gz if gz.exists() else plain


def main() -> None:
    parser = argparse.ArgumentParser(description="Chapitre 3 — Moyenne, Maximum, MIL.")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs")
    parser.add_argument("--windows", type=Path, default=None)
    parser.add_argument("--exposures", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--mil-min-proportion", type=float, default=0.05)
    parser.add_argument("--plain-csv", action="store_true")
    args = parser.parse_args()

    config = load_project_config(ROOT)
    windows_path = args.windows or _existing(args.output_dir, "exposure_windows")
    exposures_path = args.exposures or _existing(args.output_dir, "individual_exposures")
    output_path = args.output or args.output_dir / ("exposure_thresholds.csv" if args.plain_csv else "exposure_thresholds.csv.gz")
    if not windows_path.exists():
        raise FileNotFoundError(windows_path)
    if not exposures_path.exists():
        raise FileNotFoundError(exposures_path)

    report = generate_exposure_thresholds(
        config, windows_path, exposures_path, output_path,
        mil_min_proportion=args.mil_min_proportion, gzip_output=not args.plain_csv,
    )
    report["output_path"] = str(output_path)
    print("=== ÉTAPE 5/7 — DÉPASSEMENTS MOYENNE/MAX/MIL TERMINÉS ===")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
