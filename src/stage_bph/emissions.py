from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import numpy as np

from .calendar_utils import annex_day_type
from .models import DomesticEvent, Household, Individual


@dataclass
class DailyEmissionResult:
    pm25: np.ndarray
    pm10: np.ndarray
    background_pm25: np.ndarray
    cooking_increment: np.ndarray
    tobacco_increment: np.ndarray
    biomass_increment: np.ndarray
    events: list[DomesticEvent]
    background_end: float
    source_state_end: dict[str, float]


def _effective_decay_factor(
    half_life_minutes: float,
    air_change_rate_h: float,
    step_minutes: int,
) -> float:
    if half_life_minutes <= 0:
        raise ValueError("La demi-vie doit être positive.")
    intrinsic_rate_h = math.log(2.0) / (half_life_minutes / 60.0)
    total_rate_h = intrinsic_rate_h + max(0.0, air_change_rate_h)
    return math.exp(-total_rate_h * (step_minutes / 60.0))


def _any_home(presence: dict[str, list[str]], start: int, end: int) -> bool:
    return any(
        pieces[slot] != "absent"
        for pieces in presence.values()
        for slot in range(start, min(end + 1, len(pieces)))
    )


def _present_smoker_slots(
    occupants: list[Individual],
    presence: dict[str, list[str]],
) -> list[int]:
    slots: set[int] = set()
    for individual in occupants:
        if individual.smoking_status != "current":
            continue
        for slot, piece in enumerate(presence[individual.individual_id]):
            if piece != "absent":
                slots.add(slot)
    return sorted(slots)


def _daily_background(
    *,
    mean: float,
    sd: float,
    ar1: float,
    previous_value: float | None,
    rng: np.random.Generator,
    slots: int = 96,
) -> np.ndarray:
    if not 0 <= ar1 < 1:
        raise ValueError(f"AR(1) invalide: {ar1}")
    result = np.empty(slots, dtype=float)
    current = float(previous_value if previous_value is not None else rng.normal(mean, sd))
    innovation_sd = sd * math.sqrt(max(1e-12, 1.0 - ar1 * ar1))
    for slot in range(slots):
        current = mean + ar1 * (current - mean) + float(rng.normal(0.0, innovation_sd))
        current = max(0.0, current)
        result[slot] = current
    return result


def _add_event(
    *,
    events: list[DomesticEvent],
    injections: np.ndarray,
    household: Household,
    day: date,
    source_type: str,
    peak_slot: int,
    peak: float,
    evidence_status: str,
    note: str,
    sequence: int,
) -> None:
    # Deux injections successives créent une montée puis un pic, avec une amplitude
    # unique tirée une seule fois pour l'événement.
    start_slot = max(0, peak_slot - 1)
    injections[start_slot] += 0.35 * peak
    injections[peak_slot] += 0.65 * peak
    events.append(
        DomesticEvent(
            event_id=f"{household.household_id}_{day.isoformat()}_{source_type}_{sequence:02d}",
            household_id=household.household_id,
            event_date=day,
            source_type=source_type,
            start_slot=start_slot,
            peak_slot=peak_slot,
            peak_increment_pm25=peak,
            evidence_status=evidence_status,
            scientific_note=note,
        )
    )


def generate_daily_concentrations(
    *,
    household: Household,
    occupants: list[Individual],
    day: date,
    presence: dict[str, list[str]],
    parameters: dict[str, Any],
    rng: np.random.Generator,
    previous_background: float | None,
    source_state: dict[str, float] | None = None,
) -> DailyEmissionResult:
    step_minutes = int(parameters["simulation"]["step_minutes"])
    if step_minutes != 15:
        raise ValueError("Le générateur actuel attend 96 créneaux de 15 minutes.")

    scenario = household.emission_scenario
    background_cfg = parameters["background"][scenario]
    background = _daily_background(
        mean=float(background_cfg["mean"]),
        sd=float(background_cfg["sd"]),
        ar1=float(background_cfg["ar1"]),
        previous_value=previous_background,
        rng=rng,
    )

    injections = {
        "cooking": np.zeros(96, dtype=float),
        "tobacco": np.zeros(96, dtype=float),
        "biomass": np.zeros(96, dtype=float),
    }
    events: list[DomesticEvent] = []

    if scenario == "cooking":
        cooking_cfg = parameters["cooking"]
        for sequence, window in enumerate(cooking_cfg["windows"], start=1):
            start = int(window["start_slot"])
            end = int(window["end_slot"])
            timestamp = datetime.combine(day, datetime.min.time()) + timedelta(minutes=start * 15)
            day_type = annex_day_type(timestamp)
            probability = float(
                window["prob_weekend"] if day_type == "weekend" else window["prob_weekday"]
            )
            if _any_home(presence, start, end) and rng.random() < probability:
                peak_slot = int(rng.integers(start, end + 1))
                peak = float(rng.uniform(window["peak_low"], window["peak_high"]))
                _add_event(
                    events=events,
                    injections=injections["cooking"],
                    household=household,
                    day=day,
                    source_type=f"cooking_{window['name']}",
                    peak_slot=peak_slot,
                    peak=peak,
                    evidence_status=str(cooking_cfg["status"]),
                    note="Amplitude unique par épisode; décroissance contrôlée par ventilation.",
                    sequence=sequence,
                )

    if scenario == "tobacco" and household.smoking_allowed:
        tobacco_cfg = parameters["tobacco"]
        eligible_slots = _present_smoker_slots(occupants, presence)
        if eligible_slots:
            low = household.cigarettes_min_day
            high = household.cigarettes_max_day
            count = min(int(rng.integers(low, high + 1)), len(eligible_slots))
            selected = sorted(rng.choice(eligible_slots, size=count, replace=False).tolist())
            for sequence, peak_slot in enumerate(selected, start=1):
                peak = float(rng.uniform(tobacco_cfg["peak_low"], tobacco_cfg["peak_high"]))
                _add_event(
                    events=events,
                    injections=injections["tobacco"],
                    household=household,
                    day=day,
                    source_type="tobacco_cigarette",
                    peak_slot=int(peak_slot),
                    peak=peak,
                    evidence_status=str(tobacco_cfg["status"]),
                    note="Paramètres hérités et configurables; source numérique à renforcer.",
                    sequence=sequence,
                )

    if scenario == "biomass_extreme":
        biomass_cfg = parameters["biomass_extreme"]
        if day.month in {int(month) for month in biomass_cfg["active_months"]}:
            for sequence, window in enumerate(biomass_cfg["windows"], start=1):
                start = int(window["start_slot"])
                end = int(window["end_slot"])
                if _any_home(presence, start, end) and rng.random() < float(biomass_cfg["probability_per_window"]):
                    peak_slot = int(rng.integers(start, end + 1))
                    peak = max(0.0, float(rng.normal(biomass_cfg["peak_mean"], biomass_cfg["peak_sd"])))
                    _add_event(
                        events=events,
                        injections=injections["biomass"],
                        household=household,
                        day=day,
                        source_type="biomass_heating_extreme",
                        peak_slot=peak_slot,
                        peak=peak,
                        evidence_status=str(biomass_cfg["status"]),
                        note="Scénario extrême, saison de chauffage uniquement; non représentatif d'un logement bordelais courant.",
                        sequence=sequence,
                    )

    state = {"cooking": 0.0, "tobacco": 0.0, "biomass": 0.0}
    if source_state:
        state.update({key: float(value) for key, value in source_state.items()})

    cooking_cfg = parameters["cooking"]
    decay = {
        "cooking": _effective_decay_factor(
            float(cooking_cfg["decay_half_life_minutes"]), household.air_change_rate_h, step_minutes
        ),
        "tobacco": _effective_decay_factor(
            float(parameters["tobacco"]["decay_half_life_minutes"]), household.air_change_rate_h, step_minutes
        ),
        "biomass": _effective_decay_factor(
            float(parameters["biomass_extreme"]["decay_half_life_minutes"]), household.air_change_rate_h, step_minutes
        ),
    }

    increments = {key: np.zeros(96, dtype=float) for key in state}
    pm25 = np.empty(96, dtype=float)
    pm10 = np.empty(96, dtype=float)

    for slot in range(96):
        for source in state:
            state[source] = state[source] * decay[source] + float(injections[source][slot])
            increments[source][slot] = state[source]
        total = max(0.0, float(background[slot] + sum(state.values())))
        pm25[slot] = total
        if household.pm10_mode == "legacy_fixed":
            pm10[slot] = total * household.pm10_ratio
        else:
            raise ValueError(f"Mode PM10 non implémenté: {household.pm10_mode}")

    return DailyEmissionResult(
        pm25=pm25,
        pm10=pm10,
        background_pm25=background,
        cooking_increment=increments["cooking"],
        tobacco_increment=increments["tobacco"],
        biomass_increment=increments["biomass"],
        events=events,
        background_end=float(background[-1]),
        source_state_end={key: float(value) for key, value in state.items()},
    )
