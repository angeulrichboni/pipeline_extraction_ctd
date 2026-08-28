"""Couche de trajectoire longitudinale — Chapitre 3, étage 2.

Ce module ne recalcule aucune concentration. Il exploite la séquence des
résultats déjà produits par exposure_windows.generate_exposure_thresholds
pour reconstituer, pour chaque flux d'exposition (individu × polluant ×
échelle), l'histoire de son exposition jusqu'à la fenêtre courante.

Principe de méthode central : ces variables décrivent un fait physique —
combien de polluant a été reçu, depuis combien de temps, avec quelle
tendance. Elles ne dépendent d'aucune catégorie de santé et sont donc
calculées une seule fois par flux, indépendamment du chapitre ICD-10
auquel elles seront associées plus tard (chapitre 4).

Règles de gestion retenues (voir docs/PIPELINE.md, chapitre 3) :
  - consecutive_exceedances repart à 0 dès qu'une fenêtre repasse sous le
    seuil ; max_consecutive_exceedances_to_date ne redescend jamais.
  - Les premières fenêtres d'un flux, sans historique suffisant, reçoivent
    des valeurs par défaut explicites (0, ou "insuffisant"), jamais de
    valeur manquante.
  - exposure_slope_7j (fenêtres daily) : pente sur 7 fenêtres glissantes.
  - exposure_trend_direction (fenêtres annual) : direction catégorielle
    sur les 3 dernières fenêtres disponibles — une pente numérique sur
    aussi peu de points donnerait une fausse précision.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import IO

from .io_utils import csv_writer, open_text_output

SLOPE_WINDOW_DAILY = 7
TREND_WINDOW_ANNUAL = 3

TRAJECTORY_COLUMNS = [
    "bag_id", "individual_id", "pollutant", "window_type",
    "window_start", "window_index",
    "cumulative_exposure", "cumulative_excess_burden",
    "consecutive_exceedances", "max_consecutive_exceedances_to_date",
    "exposure_slope_7j", "exposure_trend_direction",
]


@dataclass
class _ThresholdRow:
    bag_id: str
    individual_id: str
    pollutant: str
    window_type: str
    window_start: str
    sum_exposure: float
    excess_burden: float
    mil_exceedance: bool


def open_text_input(path: Path) -> IO[str]:
    import gzip
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", newline="")
    return path.open("r", encoding="utf-8", newline="")


def _load_sorted_flows(
    thresholds_path: Path,
    windows_path: Path,
) -> dict[tuple[str, str, str], list[_ThresholdRow]]:
    """Regroupe les fenêtres par flux (individu, polluant, échelle), triées par date."""
    sum_exposure_by_bag: dict[str, float] = {}
    with open_text_input(windows_path) as handle:
        for row in csv.DictReader(handle):
            sum_exposure_by_bag[row["bag_id"]] = float(row["sum_exposure"])

    flows: dict[tuple[str, str, str], list[_ThresholdRow]] = {}
    with open_text_input(thresholds_path) as handle:
        for row in csv.DictReader(handle):
            key = (row["individual_id"], row["pollutant"], row["window_type"])
            flows.setdefault(key, []).append(
                _ThresholdRow(
                    bag_id=row["bag_id"],
                    individual_id=row["individual_id"],
                    pollutant=row["pollutant"],
                    window_type=row["window_type"],
                    window_start=row["window_start"],
                    sum_exposure=sum_exposure_by_bag.get(row["bag_id"], 0.0),
                    excess_burden=float(row["excess_burden"]),
                    mil_exceedance=row["mil_exceedance"] == "1",
                )
            )
    for rows in flows.values():
        rows.sort(key=lambda item: item.window_start)
    return flows


def _direction(values: list[float]) -> str:
    if len(values) < 2:
        return "insuffisant"
    delta = values[-1] - values[0]
    if abs(delta) < 1e-9:
        return "stable"
    return "hausse" if delta > 0 else "baisse"


def _slope(values: list[float]) -> float | None:
    """Pente simple (dernier - premier) / (n - 1) sur la fenêtre glissante fournie."""
    if len(values) < 2:
        return None
    return (values[-1] - values[0]) / (len(values) - 1)


def generate_exposure_trajectory(
    thresholds_path: Path,
    windows_path: Path,
    output_path: Path,
    *,
    gzip_output: bool = True,
) -> dict[str, int]:
    """Calcule la couche de trajectoire à partir des fenêtres déjà qualifiées."""
    flows = _load_sorted_flows(thresholds_path, windows_path)

    output_rows = 0
    with open_text_output(output_path, gzip_output) as handle:
        writer = csv_writer(handle)
        writer.writerow(TRAJECTORY_COLUMNS)

        for (individual_id, pollutant, window_type), rows in sorted(flows.items()):
            cumulative_exposure = 0.0
            cumulative_excess_burden = 0.0
            consecutive = 0
            max_consecutive = 0
            recent_means: list[float] = []
            recent_annual_means: list[float] = []

            for index, row in enumerate(rows):
                cumulative_exposure += row.sum_exposure
                cumulative_excess_burden += row.excess_burden

                if row.mil_exceedance:
                    consecutive += 1
                    max_consecutive = max(max_consecutive, consecutive)
                else:
                    consecutive = 0

                if window_type == "daily":
                    recent_means.append(row.sum_exposure)
                    if len(recent_means) > SLOPE_WINDOW_DAILY:
                        recent_means.pop(0)
                    slope = _slope(recent_means)
                    slope_text = f"{slope:.6f}" if slope is not None else ""
                    trend_text = ""
                else:
                    recent_annual_means.append(row.sum_exposure)
                    if len(recent_annual_means) > TREND_WINDOW_ANNUAL:
                        recent_annual_means.pop(0)
                    slope_text = ""
                    trend_text = _direction(recent_annual_means)

                writer.writerow([
                    row.bag_id, individual_id, pollutant, window_type,
                    row.window_start, index,
                    f"{cumulative_exposure:.6f}", f"{cumulative_excess_burden:.6f}",
                    consecutive, max_consecutive,
                    slope_text, trend_text,
                ])
                output_rows += 1

    return {"output_rows": output_rows, "flow_count": len(flows)}
