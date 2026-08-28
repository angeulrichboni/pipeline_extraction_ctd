from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .models import Household, Individual


@dataclass(frozen=True)
class ProjectConfig:
    root_dir: Path
    households: dict[str, Household]
    individuals: dict[str, Individual]
    parameters: dict[str, Any]

    @property
    def start_datetime(self) -> datetime:
        return datetime.fromisoformat(self.parameters["simulation"]["start"])

    @property
    def end_datetime(self) -> datetime:
        return datetime.fromisoformat(self.parameters["simulation"]["end"])

    @property
    def step_minutes(self) -> int:
        return int(self.parameters["simulation"]["step_minutes"])

    @property
    def seed(self) -> int:
        return int(self.parameters["simulation"]["seed"])


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "oui"}:
        return True
    if normalized in {"false", "0", "no", "non", ""}:
        return False
    raise ValueError(f"Valeur booléenne invalide: {value!r}")


def _parse_optional_date(value: str) -> date | None:
    value = value.strip()
    return date.fromisoformat(value) if value else None


def _parse_optional_bool(value: str) -> bool | None:
    value = value.strip()
    return _parse_bool(value) if value else None


def load_households(path: Path) -> dict[str, Household]:
    result: dict[str, Household] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            household = Household(
                household_id=row["household_id"],
                occupant_count=int(row["occupant_count"]),
                household_type=row["household_type"],
                housing_profile=row["housing_profile"],
                volume_m3=float(row["volume_m3"]),
                air_change_rate_h=float(row["air_change_rate_h"]),
                emission_scenario=row["emission_scenario"],
                smoking_allowed=_parse_bool(row["smoking_allowed"]),
                cigarettes_min_day=int(row["cigarettes_min_day"]),
                cigarettes_max_day=int(row["cigarettes_max_day"]),
                pm10_mode=row["pm10_mode"],
                pm10_ratio=float(row["pm10_ratio"]),
                parameter_status=row["parameter_status"],
            )
            if household.household_id in result:
                raise ValueError(f"Household dupliqué: {household.household_id}")
            result[household.household_id] = household
    return result


def load_individuals(path: Path) -> dict[str, Individual]:
    result: dict[str, Individual] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            individual = Individual(
                individual_id=row["individual_id"],
                persona_id=row["persona_id"],
                sex=row["sex"],
                birth_date=date.fromisoformat(row["birth_date"]),
                age_at_start=int(row["age_at_start"]),
                household_id=row["household_id"],
                household_role=row["household_role"],
                presence_template=row["presence_template"],
                work_status=row["work_status"],
                smoking_status=row["smoking_status"],
                baseline_asthma_mode=row["baseline_asthma_mode"],
                baseline_htn_mode=row["baseline_htn_mode"],
                pregnancy_start=_parse_optional_date(row["pregnancy_start"]),
                expected_delivery_date=_parse_optional_date(row["expected_delivery_date"]),
                parity_category=row["parity_category"],
                is_first_pregnancy=_parse_optional_bool(row["is_first_pregnancy"]),
                pregnancy_presence_modifier=row["pregnancy_presence_modifier"],
                parameter_status=row["parameter_status"],
            )
            if individual.individual_id in result:
                raise ValueError(f"Individu dupliqué: {individual.individual_id}")
            result[individual.individual_id] = individual
    return result


def validate_project_config(config: ProjectConfig) -> None:
    if config.step_minutes != 15:
        raise ValueError("Les annexes de présence exigent actuellement un pas de 15 minutes.")
    if config.end_datetime < config.start_datetime:
        raise ValueError("La date de fin précède la date de début.")
    if len(config.individuals) != 30:
        raise ValueError(f"30 individus attendus, {len(config.individuals)} trouvés.")

    household_counts = {household_id: 0 for household_id in config.households}
    persona_counts: dict[str, int] = {}
    for individual in config.individuals.values():
        if individual.household_id not in config.households:
            raise ValueError(
                f"Le logement {individual.household_id} de {individual.individual_id} n'existe pas."
            )
        household_counts[individual.household_id] += 1
        persona_counts[individual.persona_id] = persona_counts.get(individual.persona_id, 0) + 1

        computed_age = config.start_datetime.date().year - individual.birth_date.year - (
            (config.start_datetime.date().month, config.start_datetime.date().day)
            < (individual.birth_date.month, individual.birth_date.day)
        )
        if computed_age != individual.age_at_start:
            raise ValueError(
                f"Âge incohérent pour {individual.individual_id}: "
                f"config={individual.age_at_start}, calculé={computed_age}."
            )

    for household_id, expected in (
        (household_id, household.occupant_count)
        for household_id, household in config.households.items()
    ):
        actual = household_counts[household_id]
        if actual != expected:
            raise ValueError(
                f"Taille incohérente pour {household_id}: attendue={expected}, réelle={actual}."
            )
        if actual not in {2, 5}:
            raise ValueError(f"Le logement {household_id} doit avoir 2 ou 5 occupants.")

    expected_personas = {"P1", "P2", "P3", "P4", "P5"}
    if set(persona_counts) != expected_personas:
        raise ValueError(f"Personas invalides: {persona_counts}")
    if any(count != 6 for count in persona_counts.values()):
        raise ValueError(f"Six individus par persona attendus: {persona_counts}")


def load_project_config(root_dir: Path) -> ProjectConfig:
    root_dir = root_dir.resolve()
    parameters = json.loads(
        (root_dir / "config" / "scientific_parameters.json").read_text(encoding="utf-8")
    )
    config = ProjectConfig(
        root_dir=root_dir,
        households=load_households(root_dir / "config" / "households.csv"),
        individuals=load_individuals(root_dir / "config" / "individuals.csv"),
        parameters=parameters,
    )
    validate_project_config(config)
    return config
