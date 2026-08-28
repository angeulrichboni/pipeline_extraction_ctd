from __future__ import annotations

import csv
from pathlib import Path
from types import SimpleNamespace

from stage_bph.exposure_windows import (
    generate_exposure_thresholds,
    generate_exposure_windows,
)


def _config() -> SimpleNamespace:
    return SimpleNamespace(
        step_minutes=15,
        parameters={
            "who_guidelines_2021": {
                "pm25_24h": 15.0,
                "pm10_24h": 45.0,
                "pm25_annual": 5.0,
                "pm10_annual": 15.0,
            }
        },
    )


def _write_exposures(path: Path) -> None:
    rows = [
        # Une journée complète artificielle de 4 créneaux pour test unitaire.
        ["I1", "P1", "H1", "2021-01-01T00:00", "2021-01-01", "2021", "1", 10, 20, 10, 20],
        ["I1", "P1", "H1", "2021-01-01T00:15", "2021-01-01", "2021", "1", 20, 50, 20, 50],
        ["I1", "P1", "H1", "2021-01-01T00:30", "2021-01-01", "2021", "0", 20, 50, 0, 0],
        ["I1", "P1", "H1", "2021-01-01T00:45", "2021-01-01", "2021", "1", 30, 60, 30, 60],
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "individual_id", "persona_id", "household_id", "timestamp", "date", "year",
            "is_home", "pm25_indoor", "pm10_indoor", "pm25_residential_exposure",
            "pm10_residential_exposure",
        ])
        writer.writerows(rows)


def test_generate_windows_and_thresholds(tmp_path: Path) -> None:
    exposures = tmp_path / "individual_exposures.csv"
    windows = tmp_path / "exposure_windows.csv"
    thresholds = tmp_path / "exposure_thresholds.csv"
    _write_exposures(exposures)

    report = generate_exposure_windows(_config(), exposures, windows, gzip_output=False)
    assert report["daily_window_rows"] == 2
    assert report["annual_window_rows"] == 2

    with windows.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    pm25_daily = next(r for r in rows if r["pollutant"] == "PM25" and r["window_type"] == "daily")
    assert float(pm25_daily["mean_exposure"]) == 15.0
    assert float(pm25_daily["max_exposure"]) == 30.0
    assert int(pm25_daily["home_minutes"]) == 45

    threshold_report = generate_exposure_thresholds(
        _config(), windows, exposures, thresholds, mil_min_proportion=0.25, gzip_output=False
    )
    assert threshold_report["output_rows"] == 4

    with thresholds.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    pm25_daily_threshold = next(
        r for r in rows if r["pollutant"] == "PM25" and r["window_type"] == "daily"
    )
    assert pm25_daily_threshold["mean_exceedance"] == "0"
    assert pm25_daily_threshold["max_exceedance"] == "1"
    assert pm25_daily_threshold["mil_exceedance"] == "1"
    assert int(pm25_daily_threshold["above_threshold_slots"]) == 2
