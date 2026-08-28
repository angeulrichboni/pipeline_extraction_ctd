from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from .calendar_utils import annex_day_type, slot_index
from .models import Individual
from . import presence_templates

PIECES = presence_templates.PIECES
LEGACY_TEMPLATES = presence_templates.TYPES_PRESENCE
ALL_TEMPLATES = (*LEGACY_TEMPLATES, "RetraiteHome")


def _fill(schedule: list[str], start: int, end: int, piece: str) -> None:
    if piece not in PIECES:
        raise ValueError(f"Pièce invalide: {piece}")
    for slot in range(start, end):
        schedule[slot] = piece


def _build_retiree_weekday() -> list[str]:
    schedule = ["absent"] * 96
    _fill(schedule, 0, 28, "chambre")       # 00:00-07:00
    _fill(schedule, 28, 30, "cuisine")      # 07:00-07:30
    _fill(schedule, 30, 32, "sdb")          # 07:30-08:00
    _fill(schedule, 32, 40, "sejour")       # 08:00-10:00
    _fill(schedule, 40, 46, "absent")       # sortie 10:00-11:30
    _fill(schedule, 46, 50, "cuisine")      # préparation déjeuner
    _fill(schedule, 50, 56, "sejour")       # déjeuner / séjour
    _fill(schedule, 56, 60, "chambre")      # repos
    _fill(schedule, 60, 68, "absent")       # activité extérieure 15:00-17:00
    _fill(schedule, 68, 76, "sejour")       # 17:00-19:00
    _fill(schedule, 76, 80, "cuisine")      # dîner
    _fill(schedule, 80, 92, "sejour")       # soirée
    _fill(schedule, 92, 96, "chambre")      # 23:00-24:00
    return schedule


def _build_retiree_weekend() -> list[str]:
    schedule = ["absent"] * 96
    _fill(schedule, 0, 32, "chambre")       # 00:00-08:00
    _fill(schedule, 32, 34, "cuisine")
    _fill(schedule, 34, 36, "sdb")
    _fill(schedule, 36, 48, "sejour")
    _fill(schedule, 48, 52, "cuisine")
    _fill(schedule, 52, 64, "sejour")
    _fill(schedule, 64, 70, "absent")       # sortie 16:00-17:30
    _fill(schedule, 70, 76, "sejour")
    _fill(schedule, 76, 80, "cuisine")
    _fill(schedule, 80, 92, "sejour")
    _fill(schedule, 92, 96, "chambre")
    return schedule


RETIREE_WEEKDAY = _build_retiree_weekday()
RETIREE_WEEKEND = _build_retiree_weekend()


def pregnancy_phase(individual: Individual, current_date: date) -> tuple[str, int | None]:
    if individual.pregnancy_start is None or individual.expected_delivery_date is None:
        return "not_pregnant", None

    if individual.pregnancy_start <= current_date <= individual.expected_delivery_date:
        days = (current_date - individual.pregnancy_start).days
        week = days // 7 + 1
        if week <= 13:
            return "trimester_1", week
        if week <= 27:
            return "trimester_2", week
        return "trimester_3", week

    postpartum_end = individual.expected_delivery_date + timedelta(weeks=10)
    if individual.expected_delivery_date < current_date <= postpartum_end:
        return "postpartum_10w", None
    return "not_pregnant", None


def _effective_template(
    individual: Individual,
    timestamp: datetime,
    parameters: dict[str, Any],
) -> str:
    template = individual.presence_template
    modifier = parameters.get("pregnancy_presence_modifier", {})
    if (
        individual.pregnancy_presence_modifier == "late_pregnancy_home"
        and modifier.get("enabled", False)
        and individual.pregnancy_start is not None
        and individual.expected_delivery_date is not None
    ):
        phase, week = pregnancy_phase(individual, timestamp.date())
        start_week = int(modifier.get("start_gestational_week", 34))
        if (phase == "trimester_3" and week is not None and week >= start_week) or phase.startswith("postpartum"):
            return str(modifier.get("replacement_template", "RetraiteHome"))
    return template


def get_piece(
    individual: Individual,
    timestamp: datetime,
    parameters: dict[str, Any],
) -> str:
    template = _effective_template(individual, timestamp, parameters)
    day_type = annex_day_type(timestamp)
    slot = slot_index(timestamp, 15)

    if template in LEGACY_TEMPLATES:
        return presence_templates.get_piece(template, day_type, slot)
    if template == "RetraiteHome":
        return RETIREE_WEEKEND[slot] if day_type == "weekend" else RETIREE_WEEKDAY[slot]
    raise KeyError(f"Template de présence inconnu: {template}")


def build_daily_presence(
    individual: Individual,
    day: date,
    parameters: dict[str, Any],
) -> list[str]:
    pieces: list[str] = []
    for slot in range(96):
        timestamp = datetime.combine(day, datetime.min.time()) + timedelta(minutes=slot * 15)
        pieces.append(get_piece(individual, timestamp, parameters))
    return pieces
