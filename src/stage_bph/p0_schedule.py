from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from .calendar_utils import age_on
from .config import ProjectConfig
from .health import initialize_health_states
from .p0 import P0Reference


COLUMNS = [
    "individual_id", "persona_id", "calendar_year", "age", "sex", "event_id",
    "event_name", "horizon", "p0_value", "rule_id", "condition", "scenario",
    "evidence_status", "use_status", "source", "scientific_note",
]


def generate_p0_schedule(config: ProjectConfig, output_path: Path) -> int:
    reference = P0Reference.from_csv(
        config.root_dir / "config" / "p0_reference.csv"
    )
    health_states = initialize_health_states(
        config.individuals, reference, config.start_datetime.date(), config.seed
    )
    count = 0
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(COLUMNS)

        for individual in sorted(config.individuals.values(), key=lambda x: x.individual_id):
            state = health_states[individual.individual_id]
            for year in range(config.start_datetime.year, config.end_datetime.year + 1):
                current_date = date(year, 1, 1)
                age = age_on(individual.birth_date, current_date)
                event_ids: list[tuple[str, str | None]] = []
                if state.baseline_asthma and individual.persona_id in {"P1", "P5"}:
                    event_ids.append(("E02", "Asthme préexistant"))
                if individual.persona_id in {"P2", "P4"}:
                    event_ids.extend([("E03", None), ("E04", None)])

                for event_id, condition in event_ids:
                    rule = reference.select(
                        event_id=event_id,
                        persona_id=individual.persona_id,
                        age=age,
                        sex=individual.sex,
                        condition=condition,
                    )
                    writer.writerow([
                        individual.individual_id, individual.persona_id, year, age,
                        individual.sex, event_id, rule.event_name, rule.horizon,
                        f"{rule.p0_value:.10f}", rule.rule_id, rule.condition,
                        rule.scenario, rule.evidence_status, rule.use_status,
                        rule.source, rule.scientific_note,
                    ])
                    count += 1

            if individual.persona_id == "P3" and individual.pregnancy_start is not None:
                pregnancy_age = age_on(individual.birth_date, individual.pregnancy_start)
                preterm_rule = reference.select(
                    event_id="E05",
                    persona_id="P3",
                    age=pregnancy_age,
                    sex=individual.sex,
                    condition="Grossesse unique",
                )
                preeclampsia_condition = (
                    "Première grossesse" if individual.is_first_pregnancy else "Grossesse ultérieure"
                )
                preeclampsia_rule = reference.select(
                    event_id="E08",
                    persona_id="P3",
                    age=pregnancy_age,
                    sex=individual.sex,
                    condition=preeclampsia_condition,
                )
                for rule in (preterm_rule, preeclampsia_rule):
                    writer.writerow([
                        individual.individual_id, individual.persona_id,
                        individual.pregnancy_start.year, pregnancy_age, individual.sex,
                        rule.event_id, rule.event_name, rule.horizon,
                        f"{rule.p0_value:.10f}", rule.rule_id, rule.condition,
                        rule.scenario, rule.evidence_status, rule.use_status,
                        rule.source, rule.scientific_note,
                    ])
                    count += 1
    return count
