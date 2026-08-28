from __future__ import annotations

import csv
import gzip
import json
from pathlib import Path
from typing import IO, Iterator


def _open_csv(path: Path) -> IO[str]:
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", newline="")
    return path.open("r", encoding="utf-8", newline="")


def validate_exposure_file(path: Path, expected_pm10_ratio: float = 1.53) -> dict[str, object]:
    row_count = 0
    absence_violations = 0
    negative_violations = 0
    ratio_violations = 0
    shared_concentration_violations = 0

    previous_key: tuple[str, str] | None = None
    previous_concentration: tuple[float, float] | None = None

    with _open_csv(path) as handle:
        for row in csv.DictReader(handle):
            row_count += 1
            pm25 = float(row["pm25_indoor"])
            pm10 = float(row["pm10_indoor"])
            exp25 = float(row["pm25_residential_exposure"])
            exp10 = float(row["pm10_residential_exposure"])
            is_home = row["is_home"] == "1"

            if min(pm25, pm10, exp25, exp10) < 0:
                negative_violations += 1
            if not is_home and (abs(exp25) > 1e-9 or abs(exp10) > 1e-9):
                absence_violations += 1
            if pm25 > 0 and abs(pm10 / pm25 - expected_pm10_ratio) > 1e-5:
                ratio_violations += 1

            key = (row["household_id"], row["timestamp"])
            concentration = (pm25, pm10)
            if key == previous_key and concentration != previous_concentration:
                shared_concentration_violations += 1
            previous_key = key
            previous_concentration = concentration

    return {
        "row_count": row_count,
        "absence_violations": absence_violations,
        "negative_violations": negative_violations,
        "pm10_ratio_violations": ratio_violations,
        "shared_concentration_violations": shared_concentration_violations,
        "ok": all(
            value == 0
            for value in (
                absence_violations,
                negative_violations,
                ratio_violations,
                shared_concentration_violations,
            )
        ),
    }


def validate_output_directory(output_dir: Path) -> dict[str, object]:
    quality_path = output_dir / "quality_report.json"
    if not quality_path.exists():
        raise FileNotFoundError(quality_path)
    quality = json.loads(quality_path.read_text(encoding="utf-8"))

    candidates = [
        output_dir / "individual_exposures.csv.gz",
        output_dir / "individual_exposures.csv",
    ]
    exposure_path = next((path for path in candidates if path.exists()), None)
    if exposure_path is None:
        raise FileNotFoundError("individual_exposures.csv(.gz) absent")

    exposure_validation = validate_exposure_file(exposure_path)
    result = {
        "quality_report": quality,
        "exposure_validation": exposure_validation,
        "ok": bool(
            quality["checks"]["concentration_row_count_ok"]
            and quality["checks"]["exposure_row_count_ok"]
            and exposure_validation["ok"]
        ),
    }
    (output_dir / "post_validation_report.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result
