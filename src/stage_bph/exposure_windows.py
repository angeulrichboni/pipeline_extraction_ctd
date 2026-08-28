from __future__ import annotations

import csv
import gzip
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import IO, Iterable

from .config import ProjectConfig
from .io_utils import csv_writer, open_text_output

POLLUTANTS = ("PM25", "PM10")

WINDOW_COLUMNS = [
    "individual_id", "persona_id", "household_id", "pollutant",
    "window_type", "window_start", "window_end", "year", "date",
    "bag_id", "valid_slots", "home_slots", "home_minutes",
    "mean_exposure", "home_mean_exposure", "max_exposure", "sum_exposure",
]

THRESHOLD_COLUMNS = [
    "individual_id", "persona_id", "household_id", "pollutant",
    "window_type", "window_start", "window_end", "year", "date", "bag_id",
    "mean_threshold_value", "max_threshold_value", "mil_threshold_value",
    "mean_exposure", "max_exposure", "mean_exceedance", "max_exceedance",
    "mil_exceedance", "instance_count", "above_threshold_slots",
    "proportion_above_threshold", "excess_mean", "excess_max", "excess_burden",
    "mil_min_proportion",
]


@dataclass
class WindowStats:
    individual_id: str
    persona_id: str
    household_id: str
    pollutant: str
    window_type: str
    window_start: str
    window_end: str
    year: str
    date_value: str
    bag_id: str
    valid_slots: int = 0
    home_slots: int = 0
    sum_exposure: float = 0.0
    home_sum_exposure: float = 0.0
    max_exposure: float = 0.0

    def update(self, exposure: float, is_home: bool) -> None:
        self.valid_slots += 1
        self.sum_exposure += exposure
        if exposure > self.max_exposure:
            self.max_exposure = exposure
        if is_home:
            self.home_slots += 1
            self.home_sum_exposure += exposure

    def to_row(self, step_minutes: int) -> list[str]:
        mean = self.sum_exposure / self.valid_slots if self.valid_slots else 0.0
        home_mean = self.home_sum_exposure / self.home_slots if self.home_slots else 0.0
        return [
            self.individual_id,
            self.persona_id,
            self.household_id,
            self.pollutant,
            self.window_type,
            self.window_start,
            self.window_end,
            self.year,
            self.date_value,
            self.bag_id,
            str(self.valid_slots),
            str(self.home_slots),
            str(self.home_slots * step_minutes),
            f"{mean:.6f}",
            f"{home_mean:.6f}",
            f"{self.max_exposure:.6f}",
            f"{self.sum_exposure:.6f}",
        ]


@dataclass
class InstanceThresholdStats:
    count: int = 0
    above_count: int = 0
    excess_burden: float = 0.0

    def update(self, exposure: float, threshold: float, step_hours: float) -> None:
        self.count += 1
        if exposure > threshold:
            self.above_count += 1
            self.excess_burden += (exposure - threshold) * step_hours


def open_text_input(path: Path) -> IO[str]:
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", newline="")
    return path.open("r", encoding="utf-8", newline="")


def _require_columns(fieldnames: Iterable[str] | None, required: set[str], path: Path) -> None:
    available = set(fieldnames or [])
    missing = sorted(required - available)
    if missing:
        raise ValueError(f"Colonnes manquantes dans {path}: {missing}")


def _daily_bounds(day_text: str) -> tuple[str, str]:
    day = date.fromisoformat(day_text)
    start = datetime.combine(day, time.min)
    end = datetime.combine(day, time(23, 45))
    return start.isoformat(timespec="minutes"), end.isoformat(timespec="minutes")


def _annual_bounds(year_text: str) -> tuple[str, str]:
    year = int(year_text)
    start = datetime(year, 1, 1, 0, 0)
    end = datetime(year, 12, 31, 23, 45)
    return start.isoformat(timespec="minutes"), end.isoformat(timespec="minutes")


def _pollutant_exposure(row: dict[str, str], pollutant: str) -> float:
    if pollutant == "PM25":
        return float(row["pm25_residential_exposure"])
    if pollutant == "PM10":
        return float(row["pm10_residential_exposure"])
    raise ValueError(f"Polluant inconnu: {pollutant}")


def _threshold(config: ProjectConfig, pollutant: str, window_type: str) -> float:
    guidelines = config.parameters["who_guidelines_2021"]
    if pollutant == "PM25" and window_type == "daily":
        return float(guidelines["pm25_24h"])
    if pollutant == "PM10" and window_type == "daily":
        return float(guidelines["pm10_24h"])
    if pollutant == "PM25" and window_type == "annual":
        return float(guidelines["pm25_annual"])
    if pollutant == "PM10" and window_type == "annual":
        return float(guidelines["pm10_annual"])
    raise ValueError(f"Seuil absent pour {pollutant}/{window_type}")


def _get_or_create_window(
    windows: dict[tuple[str, str, str, str], WindowStats],
    row: dict[str, str],
    pollutant: str,
    window_type: str,
) -> WindowStats:
    if window_type == "daily":
        date_value = row["date"]
        year = row["year"]
        start, end = _daily_bounds(date_value)
        bag_id = f"daily|{row['individual_id']}|{date_value}|{pollutant}"
        key = (row["individual_id"], pollutant, "daily", date_value)
    elif window_type == "annual":
        year = row["year"]
        date_value = ""
        start, end = _annual_bounds(year)
        bag_id = f"annual|{row['individual_id']}|{year}|{pollutant}"
        key = (row["individual_id"], pollutant, "annual", year)
    else:
        raise ValueError(f"Type de fenêtre inconnu: {window_type}")

    if key not in windows:
        windows[key] = WindowStats(
            individual_id=row["individual_id"],
            persona_id=row["persona_id"],
            household_id=row["household_id"],
            pollutant=pollutant,
            window_type=window_type,
            window_start=start,
            window_end=end,
            year=year,
            date_value=date_value,
            bag_id=bag_id,
        )
    return windows[key]


def generate_exposure_windows(
    config: ProjectConfig,
    exposure_path: Path,
    output_path: Path,
    *,
    gzip_output: bool = True,
) -> dict[str, int]:
    """Agrège les expositions 15 minutes en fenêtres journalières et annuelles."""
    required = {
        "individual_id", "persona_id", "household_id", "date", "year", "is_home",
        "pm25_residential_exposure", "pm10_residential_exposure",
    }
    windows: dict[tuple[str, str, str, str], WindowStats] = {}
    input_rows = 0

    with open_text_input(exposure_path) as handle:
        reader = csv.DictReader(handle)
        _require_columns(reader.fieldnames, required, exposure_path)
        for row in reader:
            input_rows += 1
            is_home = row["is_home"] == "1"
            for pollutant in POLLUTANTS:
                exposure = _pollutant_exposure(row, pollutant)
                _get_or_create_window(windows, row, pollutant, "daily").update(exposure, is_home)
                _get_or_create_window(windows, row, pollutant, "annual").update(exposure, is_home)

    daily_rows = 0
    annual_rows = 0
    with open_text_output(output_path, gzip_output) as handle:
        writer = csv_writer(handle)
        writer.writerow(WINDOW_COLUMNS)
        for key in sorted(windows):
            stats = windows[key]
            writer.writerow(stats.to_row(config.step_minutes))
            if stats.window_type == "daily":
                daily_rows += 1
            else:
                annual_rows += 1

    return {
        "input_rows": input_rows,
        "daily_window_rows": daily_rows,
        "annual_window_rows": annual_rows,
        "output_rows": daily_rows + annual_rows,
    }


def _raw_threshold_stats(
    config: ProjectConfig,
    exposure_path: Path,
) -> dict[str, InstanceThresholdStats]:
    required = {
        "individual_id", "date", "year", "is_home",
        "pm25_residential_exposure", "pm10_residential_exposure",
    }
    step_hours = config.step_minutes / 60.0
    stats: dict[str, InstanceThresholdStats] = {}

    with open_text_input(exposure_path) as handle:
        reader = csv.DictReader(handle)
        _require_columns(reader.fieldnames, required, exposure_path)
        for row in reader:
            for pollutant in POLLUTANTS:
                exposure = _pollutant_exposure(row, pollutant)
                for window_type, period in (("daily", row["date"]), ("annual", row["year"])):
                    bag_id = f"{window_type}|{row['individual_id']}|{period}|{pollutant}"
                    threshold = _threshold(config, pollutant, window_type)
                    stats.setdefault(bag_id, InstanceThresholdStats()).update(
                        exposure, threshold, step_hours
                    )
    return stats


def generate_exposure_thresholds(
    config: ProjectConfig,
    windows_path: Path,
    exposure_path: Path,
    output_path: Path,
    *,
    mil_min_proportion: float = 0.05,
    gzip_output: bool = True,
) -> dict[str, int | float]:
    """Applique les méthodes moyenne, max et MIL aux fenêtres 2A."""
    if not 0 <= mil_min_proportion <= 1:
        raise ValueError("mil_min_proportion doit être compris entre 0 et 1.")

    required = {
        "individual_id", "persona_id", "household_id", "pollutant", "window_type",
        "window_start", "window_end", "year", "date", "bag_id",
        "mean_exposure", "max_exposure",
    }
    instance_stats = _raw_threshold_stats(config, exposure_path)
    output_rows = 0
    mean_positive = 0
    max_positive = 0
    mil_positive = 0

    with open_text_input(windows_path) as windows_handle, open_text_output(output_path, gzip_output) as out_handle:
        reader = csv.DictReader(windows_handle)
        _require_columns(reader.fieldnames, required, windows_path)
        writer = csv_writer(out_handle)
        writer.writerow(THRESHOLD_COLUMNS)

        for row in reader:
            pollutant = row["pollutant"]
            window_type = row["window_type"]
            mean_threshold = _threshold(config, pollutant, window_type)
            max_threshold = mean_threshold
            mil_threshold = mean_threshold
            mean_exposure = float(row["mean_exposure"])
            max_exposure = float(row["max_exposure"])
            mean_exceedance = int(mean_exposure > mean_threshold)
            max_exceedance = int(max_exposure > max_threshold)

            raw = instance_stats.get(row["bag_id"], InstanceThresholdStats())
            proportion = raw.above_count / raw.count if raw.count else 0.0
            mil_exceedance = int(proportion >= mil_min_proportion and raw.count > 0)

            mean_positive += mean_exceedance
            max_positive += max_exceedance
            mil_positive += mil_exceedance
            output_rows += 1

            writer.writerow([
                row["individual_id"], row["persona_id"], row["household_id"],
                pollutant, window_type, row["window_start"], row["window_end"],
                row["year"], row["date"], row["bag_id"],
                f"{mean_threshold:.6f}", f"{max_threshold:.6f}", f"{mil_threshold:.6f}",
                f"{mean_exposure:.6f}", f"{max_exposure:.6f}",
                str(mean_exceedance), str(max_exceedance), str(mil_exceedance),
                str(raw.count), str(raw.above_count), f"{proportion:.6f}",
                f"{max(0.0, mean_exposure - mean_threshold):.6f}",
                f"{max(0.0, max_exposure - max_threshold):.6f}",
                f"{raw.excess_burden:.6f}", f"{mil_min_proportion:.6f}",
            ])

    return {
        "output_rows": output_rows,
        "mean_positive_rows": mean_positive,
        "max_positive_rows": max_positive,
        "mil_positive_rows": mil_positive,
        "mil_min_proportion": mil_min_proportion,
    }
