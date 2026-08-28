from __future__ import annotations

import zlib
from datetime import date

import numpy as np

from .calendar_utils import age_on
from .models import HealthState, Individual
from .p0 import P0Reference


def _fixed_mode(mode: str) -> bool | None:
    if mode == "fixed_true":
        return True
    if mode == "fixed_false":
        return False
    if mode == "sample_from_p0":
        return None
    raise ValueError(f"Mode d'état initial inconnu: {mode}")


def initialize_health_states(
    individuals: dict[str, Individual],
    p0_reference: P0Reference,
    start_date: date,
    seed: int,
) -> dict[str, HealthState]:
    states: dict[str, HealthState] = {}
    for individual_id in sorted(individuals):
        individual = individuals[individual_id]
        rng = np.random.default_rng(seed + zlib.crc32(individual_id.encode("utf-8")))
        age = age_on(individual.birth_date, start_date)

        asthma_fixed = _fixed_mode(individual.baseline_asthma_mode)
        asthma_rule_id = "DESIGN_FIXED_FALSE" if asthma_fixed is False else "DESIGN_FIXED_TRUE"
        if asthma_fixed is None:
            rule = p0_reference.select(
                event_id="E01",
                persona_id=individual.persona_id,
                age=age,
                sex=individual.sex,
            )
            baseline_asthma = bool(rng.random() < rule.p0_value)
            asthma_rule_id = rule.rule_id
        else:
            baseline_asthma = asthma_fixed

        htn_fixed = _fixed_mode(individual.baseline_htn_mode)
        htn_rule_id = "DESIGN_FIXED_FALSE" if htn_fixed is False else "DESIGN_FIXED_TRUE"
        if htn_fixed is None:
            rule = p0_reference.select(
                event_id="BASELINE_HTN",
                persona_id=individual.persona_id,
                age=age,
                sex=individual.sex,
            )
            baseline_hypertension = bool(rng.random() < rule.p0_value)
            htn_rule_id = rule.rule_id
        else:
            baseline_hypertension = htn_fixed

        states[individual_id] = HealthState(
            individual_id=individual_id,
            baseline_asthma=baseline_asthma,
            baseline_hypertension=baseline_hypertension,
            asthma_rule_id=asthma_rule_id,
            hypertension_rule_id=htn_rule_id,
        )
    return states
