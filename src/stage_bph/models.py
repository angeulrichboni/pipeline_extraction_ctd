from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass(frozen=True)
class Household:
    household_id: str
    occupant_count: int
    household_type: str
    housing_profile: str
    volume_m3: float
    air_change_rate_h: float
    emission_scenario: str
    smoking_allowed: bool
    cigarettes_min_day: int
    cigarettes_max_day: int
    pm10_mode: str
    pm10_ratio: float
    parameter_status: str


@dataclass(frozen=True)
class Individual:
    individual_id: str
    persona_id: str
    sex: str
    birth_date: date
    age_at_start: int
    household_id: str
    household_role: str
    presence_template: str
    work_status: str
    smoking_status: str
    baseline_asthma_mode: str
    baseline_htn_mode: str
    pregnancy_start: Optional[date]
    expected_delivery_date: Optional[date]
    parity_category: str
    is_first_pregnancy: Optional[bool]
    pregnancy_presence_modifier: str
    parameter_status: str


@dataclass(frozen=True)
class HealthState:
    individual_id: str
    baseline_asthma: bool
    baseline_hypertension: bool
    asthma_rule_id: str
    hypertension_rule_id: str


@dataclass(frozen=True)
class DomesticEvent:
    event_id: str
    household_id: str
    event_date: date
    source_type: str
    start_slot: int
    peak_slot: int
    peak_increment_pm25: float
    evidence_status: str
    scientific_note: str
