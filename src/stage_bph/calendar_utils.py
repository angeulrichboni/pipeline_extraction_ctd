from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Iterator


def iter_timestamps(start: datetime, end: datetime, step_minutes: int) -> Iterator[datetime]:
    if step_minutes <= 0:
        raise ValueError("step_minutes doit être strictement positif.")
    current = start
    step = timedelta(minutes=step_minutes)
    while current <= end:
        yield current
        current += step


def iter_dates(start: date, end: date) -> Iterator[date]:
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def slot_index(timestamp: datetime, step_minutes: int = 15) -> int:
    minutes = timestamp.hour * 60 + timestamp.minute
    if minutes % step_minutes != 0:
        raise ValueError(f"Timestamp hors grille de {step_minutes} minutes: {timestamp}")
    slot = minutes // step_minutes
    max_slots = 24 * 60 // step_minutes
    if not 0 <= slot < max_slots:
        raise ValueError(f"Slot invalide: {slot}")
    return slot


def annex_day_type(timestamp: datetime) -> str:
    """Retourne semaine/weekend selon les annexes B.

    Le scénario week-end commence le vendredi à 18 h et se termine le dimanche à 18 h.
    La date réelle est utilisée, contrairement à l'ancien calcul jour % 7.
    """
    weekday = timestamp.weekday()  # lundi=0, dimanche=6
    if weekday <= 3:
        return "semaine"
    if weekday == 4:
        return "weekend" if timestamp.hour >= 18 else "semaine"
    if weekday == 5:
        return "weekend"
    return "weekend" if timestamp.hour < 18 else "semaine"


def age_on(birth_date: date, current_date: date) -> int:
    return current_date.year - birth_date.year - (
        (current_date.month, current_date.day) < (birth_date.month, birth_date.day)
    )


def fraction_of_year(start: datetime, end: datetime) -> float:
    if end < start:
        raise ValueError("La fin précède le début.")
    return (end - start).total_seconds() / (365.2425 * 24 * 3600)
