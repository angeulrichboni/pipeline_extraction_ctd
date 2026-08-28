from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class P0Rule:
    rule_id: str
    event_id: str
    persona: str
    event_name: str
    age_min: int | None
    age_max: int | None
    sex: str
    condition: str
    horizon: str
    p0_value: float
    scenario: str
    evidence_status: str
    use_status: str
    source: str
    scientific_note: str

    def persona_matches(self, persona_id: str) -> bool:
        return persona_id in {part.strip() for part in self.persona.split("/")} or self.persona == persona_id

    def age_matches(self, age: int) -> bool:
        if self.age_min is not None and age < self.age_min:
            return False
        if self.age_max is not None and age > self.age_max:
            return False
        return True

    def sex_matches(self, sex: str) -> bool:
        return self.sex == "Tous" or self.sex == sex


class P0Reference:
    def __init__(self, rules: Iterable[P0Rule]) -> None:
        self.rules = list(rules)

    @classmethod
    def from_csv(cls, path: Path) -> "P0Reference":
        rules: list[P0Rule] = []
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                age_min = int(row["age_min"]) if row["age_min"].strip() else None
                age_max = int(row["age_max"]) if row["age_max"].strip() else None
                rules.append(
                    P0Rule(
                        rule_id=row["rule_id"],
                        event_id=row["event_id"],
                        persona=row["persona"],
                        event_name=row["event_name"],
                        age_min=age_min,
                        age_max=age_max,
                        sex=row["sex"],
                        condition=row["condition"],
                        horizon=row["horizon"],
                        p0_value=float(row["p0_value"]),
                        scenario=row["scenario"],
                        evidence_status=row["evidence_status"],
                        use_status=row["use_status"],
                        source=row["source"],
                        scientific_note=row["scientific_note"],
                    )
                )
        return cls(rules)

    def select(
        self,
        *,
        event_id: str,
        persona_id: str,
        age: int,
        sex: str,
        scenario_prefix: str = "CENTRAL",
        condition: str | None = None,
    ) -> P0Rule:
        candidates = [
            rule
            for rule in self.rules
            if rule.event_id == event_id
            and rule.persona_matches(persona_id)
            and rule.age_matches(age)
            and rule.sex_matches(sex)
            and rule.scenario.startswith(scenario_prefix)
            and "NE_PAS" not in rule.use_status
            and "SENSIBILITE" not in rule.use_status
            and "CALIBRATION" not in rule.use_status
        ]
        if condition is not None:
            exact = [rule for rule in candidates if rule.condition == condition]
            if exact:
                candidates = exact

        if not candidates:
            raise LookupError(
                f"Aucune règle p0 pour event={event_id}, persona={persona_id}, "
                f"age={age}, sex={sex}, condition={condition}."
            )

        # Priorité au sexe exact puis à la classe d'âge la plus étroite.
        candidates.sort(
            key=lambda rule: (
                0 if rule.sex == sex else 1,
                (rule.age_max if rule.age_max is not None else 999)
                - (rule.age_min if rule.age_min is not None else 0),
                rule.rule_id,
            )
        )
        return candidates[0]
