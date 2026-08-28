from __future__ import annotations

import json
import logging
import shutil
import zlib
from collections import defaultdict
from dataclasses import asdict
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from .calendar_utils import age_on, annex_day_type, iter_dates
from .config import ProjectConfig
from .emissions import generate_daily_concentrations
from .health import initialize_health_states
from .io_utils import csv_writer, open_text_output
from .p0 import P0Reference
from .presence import build_daily_presence, pregnancy_phase

LOGGER = logging.getLogger(__name__)


CONCENTRATION_COLUMNS = [
    "household_id", "timestamp", "date", "year", "day_type", "slot_15min",
    "emission_scenario", "pm25_indoor", "pm10_indoor", "background_pm25",
    "cooking_increment_pm25", "tobacco_increment_pm25", "biomass_increment_pm25",
    "pm10_mode", "pm10_ratio", "parameter_status",
]

EXPOSURE_COLUMNS = [
    "individual_id", "persona_id", "household_id", "timestamp", "date", "year",
    "age", "sex", "room", "is_home", "presence_template", "work_status",
    "smoking_status", "pregnancy_phase", "gestational_week", "baseline_asthma",
    "baseline_hypertension", "asthma_rule_id", "hypertension_rule_id",
    "pm25_indoor", "pm10_indoor", "pm25_residential_exposure",
    "pm10_residential_exposure",
]

EVENT_COLUMNS = [
    "event_id", "household_id", "event_date", "source_type", "start_slot",
    "peak_slot", "peak_increment_pm25", "evidence_status", "scientific_note",
]

DAILY_COLUMNS = [
    "household_id", "date", "year", "emission_scenario", "pm25_mean_24h",
    "pm25_max_15min", "pm10_mean_24h", "pm10_max_15min",
    "pm25_who_24h_exceeded", "pm10_who_24h_exceeded", "event_count",
]

ANNUAL_COLUMNS = [
    "household_id", "year", "emission_scenario", "pm25_annual_mean",
    "pm10_annual_mean", "pm25_who_annual_exceeded", "pm10_who_annual_exceeded",
    "days_observed", "events_observed",
]


def _output_path(output_dir: Path, stem: str, gzip_output: bool) -> Path:
    return output_dir / f"{stem}.csv.gz" if gzip_output else output_dir / f"{stem}.csv"


def _collect_parameter_warnings(config: ProjectConfig) -> list[str]:
    warnings: list[str] = []
    for household in config.households.values():
        if any(token in household.parameter_status for token in ("PROVISIONAL", "ASSUMPTION", "EXTREME")):
            warnings.append(
                f"{household.household_id}: parameter_status={household.parameter_status}"
            )
    for section, value in config.parameters.items():
        if isinstance(value, dict):
            status = str(value.get("status", ""))
            if any(token in status for token in ("PROVISIONAL", "ASSUMPTION", "SOURCE_TO_RETRIEVE")):
                warnings.append(f"scientific_parameters.{section}: status={status}")
    return sorted(set(warnings))


def generate_trajectories(
    config: ProjectConfig,
    output_dir: Path,
    *,
    start_datetime: datetime | None = None,
    end_datetime: datetime | None = None,
    gzip_output: bool = True,
    log_every_days: int = 90,
    strict_provenance: bool = False,
) -> dict[str, Any]:
    start = start_datetime or config.start_datetime
    end = end_datetime or config.end_datetime
    if start.time() != time(0, 0) or end.time() != time(23, 45):
        LOGGER.warning(
            "La période ne couvre pas des journées complètes; les résumés 24 h seront partiels."
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    provenance_warnings = _collect_parameter_warnings(config)
    if strict_provenance and provenance_warnings:
        raise RuntimeError(
            "Paramètres provisoires détectés en mode strict:\n- " + "\n- ".join(provenance_warnings)
        )
    for warning in provenance_warnings:
        LOGGER.warning("Provenance scientifique: %s", warning)

    # Snapshot des configurations utilisées.
    snapshot_dir = output_dir / "config_snapshot"
    snapshot_dir.mkdir(exist_ok=True)
    for filename in (
        "households.csv", "individuals.csv", "scientific_parameters.json",
        "p0_reference.csv", "p0_rules.csv",
    ):
        shutil.copy2(config.root_dir / "config" / filename, snapshot_dir / filename)

    p0_reference = P0Reference.from_csv(config.root_dir / "config" / "p0_reference.csv")
    health_states = initialize_health_states(
        config.individuals, p0_reference, start.date(), config.seed
    )

    occupants_by_household: dict[str, list] = defaultdict(list)
    for individual in config.individuals.values():
        occupants_by_household[individual.household_id].append(individual)
    for occupants in occupants_by_household.values():
        occupants.sort(key=lambda person: person.individual_id)

    paths = {
        "household_concentrations": _output_path(output_dir, "household_concentrations", gzip_output),
        "individual_exposures": _output_path(output_dir, "individual_exposures", gzip_output),
        "household_events": _output_path(output_dir, "household_events", gzip_output),
        "daily_household_summary": output_dir / "daily_household_summary.csv",
        "annual_household_summary": output_dir / "annual_household_summary.csv",
        "initial_health_states": output_dir / "initial_health_states.csv",
        "quality_report": output_dir / "quality_report.json",
    }

    with paths["initial_health_states"].open("w", encoding="utf-8", newline="") as handle:
        writer = csv_writer(handle)
        writer.writerow([
            "individual_id", "baseline_asthma", "baseline_hypertension",
            "asthma_rule_id", "hypertension_rule_id",
        ])
        for individual_id in sorted(health_states):
            state = health_states[individual_id]
            writer.writerow([
                state.individual_id, int(state.baseline_asthma),
                int(state.baseline_hypertension), state.asthma_rule_id,
                state.hypertension_rule_id,
            ])

    total_concentration_rows = 0
    total_exposure_rows = 0
    total_event_rows = 0
    annual_aggregates: dict[tuple[str, int], dict[str, float]] = defaultdict(
        lambda: {"pm25_sum": 0.0, "pm10_sum": 0.0, "count": 0.0, "days": 0.0, "events": 0.0}
    )

    with (
        open_text_output(paths["household_concentrations"], gzip_output) as concentration_handle,
        open_text_output(paths["individual_exposures"], gzip_output) as exposure_handle,
        open_text_output(paths["household_events"], gzip_output) as event_handle,
        paths["daily_household_summary"].open("w", encoding="utf-8", newline="") as daily_handle,
    ):
        concentration_writer = csv_writer(concentration_handle)
        exposure_writer = csv_writer(exposure_handle)
        event_writer = csv_writer(event_handle)
        daily_writer = csv_writer(daily_handle)
        concentration_writer.writerow(CONCENTRATION_COLUMNS)
        exposure_writer.writerow(EXPOSURE_COLUMNS)
        event_writer.writerow(EVENT_COLUMNS)
        daily_writer.writerow(DAILY_COLUMNS)

        dates = list(iter_dates(start.date(), end.date()))
        for household_index, household_id in enumerate(sorted(config.households), start=1):
            household = config.households[household_id]
            occupants = occupants_by_household[household_id]
            household_seed = config.seed + zlib.crc32(household_id.encode("utf-8"))
            rng = np.random.default_rng(household_seed)
            previous_background: float | None = None
            source_state = {"cooking": 0.0, "tobacco": 0.0, "biomass": 0.0}

            LOGGER.info(
                "Logement %s (%d/%d), %d occupants, scénario=%s",
                household_id, household_index, len(config.households),
                len(occupants), household.emission_scenario,
            )

            for day_index, day in enumerate(dates, start=1):
                daily_presence = {
                    individual.individual_id: build_daily_presence(
                        individual, day, config.parameters
                    )
                    for individual in occupants
                }
                daily = generate_daily_concentrations(
                    household=household,
                    occupants=occupants,
                    day=day,
                    presence=daily_presence,
                    parameters=config.parameters,
                    rng=rng,
                    previous_background=previous_background,
                    source_state=source_state,
                )
                previous_background = daily.background_end
                source_state = daily.source_state_end

                for event in daily.events:
                    event_writer.writerow([
                        event.event_id, event.household_id, event.event_date.isoformat(),
                        event.source_type, event.start_slot, event.peak_slot,
                        f"{event.peak_increment_pm25:.6f}", event.evidence_status,
                        event.scientific_note,
                    ])
                total_event_rows += len(daily.events)

                pm25_mean = float(np.mean(daily.pm25))
                pm10_mean = float(np.mean(daily.pm10))
                pm25_max = float(np.max(daily.pm25))
                pm10_max = float(np.max(daily.pm10))
                guidelines = config.parameters["who_guidelines_2021"]
                daily_writer.writerow([
                    household_id, day.isoformat(), day.year, household.emission_scenario,
                    f"{pm25_mean:.6f}", f"{pm25_max:.6f}",
                    f"{pm10_mean:.6f}", f"{pm10_max:.6f}",
                    int(pm25_mean > float(guidelines["pm25_24h"])),
                    int(pm10_mean > float(guidelines["pm10_24h"])),
                    len(daily.events),
                ])

                annual = annual_aggregates[(household_id, day.year)]
                annual["pm25_sum"] += float(np.sum(daily.pm25))
                annual["pm10_sum"] += float(np.sum(daily.pm10))
                annual["count"] += 96
                annual["days"] += 1
                annual["events"] += len(daily.events)

                for slot in range(96):
                    timestamp = datetime.combine(day, time.min) + timedelta(minutes=slot * 15)
                    if timestamp < start or timestamp > end:
                        continue
                    concentration_writer.writerow([
                        household_id, timestamp.isoformat(timespec="minutes"), day.isoformat(),
                        day.year, annex_day_type(timestamp), slot,
                        household.emission_scenario, f"{daily.pm25[slot]:.6f}",
                        f"{daily.pm10[slot]:.6f}", f"{daily.background_pm25[slot]:.6f}",
                        f"{daily.cooking_increment[slot]:.6f}",
                        f"{daily.tobacco_increment[slot]:.6f}",
                        f"{daily.biomass_increment[slot]:.6f}", household.pm10_mode,
                        f"{household.pm10_ratio:.6f}", household.parameter_status,
                    ])
                    total_concentration_rows += 1

                    for individual in occupants:
                        room = daily_presence[individual.individual_id][slot]
                        is_home = room != "absent"
                        age = age_on(individual.birth_date, day)
                        phase, gestational_week = pregnancy_phase(individual, day)
                        state = health_states[individual.individual_id]
                        pm25_exposure = float(daily.pm25[slot]) if is_home else 0.0
                        pm10_exposure = float(daily.pm10[slot]) if is_home else 0.0
                        exposure_writer.writerow([
                            individual.individual_id, individual.persona_id, household_id,
                            timestamp.isoformat(timespec="minutes"), day.isoformat(), day.year,
                            age, individual.sex, room, int(is_home),
                            individual.presence_template, individual.work_status,
                            individual.smoking_status, phase,
                            "" if gestational_week is None else gestational_week,
                            int(state.baseline_asthma), int(state.baseline_hypertension),
                            state.asthma_rule_id, state.hypertension_rule_id,
                            f"{daily.pm25[slot]:.6f}", f"{daily.pm10[slot]:.6f}",
                            f"{pm25_exposure:.6f}", f"{pm10_exposure:.6f}",
                        ])
                        total_exposure_rows += 1

                if log_every_days > 0 and (
                    day_index % log_every_days == 0 or day_index == len(dates)
                ):
                    LOGGER.info(
                        "  %s: %d/%d jours, concentrations=%s, expositions=%s",
                        household_id, day_index, len(dates),
                        f"{total_concentration_rows:,}", f"{total_exposure_rows:,}",
                    )

    with paths["annual_household_summary"].open("w", encoding="utf-8", newline="") as handle:
        writer = csv_writer(handle)
        writer.writerow(ANNUAL_COLUMNS)
        guidelines = config.parameters["who_guidelines_2021"]
        for (household_id, year), values in sorted(annual_aggregates.items()):
            count = values["count"]
            pm25_mean = values["pm25_sum"] / count
            pm10_mean = values["pm10_sum"] / count
            household = config.households[household_id]
            writer.writerow([
                household_id, year, household.emission_scenario,
                f"{pm25_mean:.6f}", f"{pm10_mean:.6f}",
                int(pm25_mean > float(guidelines["pm25_annual"])),
                int(pm10_mean > float(guidelines["pm10_annual"])),
                int(values["days"]), int(values["events"]),
            ])

    expected_days = (end.date() - start.date()).days + 1
    expected_concentration_rows = len(config.households) * expected_days * 96
    expected_exposure_rows = len(config.individuals) * expected_days * 96
    quality_report = {
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "counts": {
            "households": len(config.households),
            "individuals": len(config.individuals),
            "days": expected_days,
            "household_concentration_rows": total_concentration_rows,
            "expected_household_concentration_rows": expected_concentration_rows,
            "individual_exposure_rows": total_exposure_rows,
            "expected_individual_exposure_rows": expected_exposure_rows,
            "household_event_rows": total_event_rows,
        },
        "checks": {
            "concentration_row_count_ok": total_concentration_rows == expected_concentration_rows,
            "exposure_row_count_ok": total_exposure_rows == expected_exposure_rows,
            "absence_rule": "pm25_residential_exposure=0 and pm10_residential_exposure=0 when room=absent",
            "shared_concentration_rule": "one household concentration is reused for all occupants at the same timestamp",
            "pm10_rule": "legacy fixed ratio 1.53; source remains incomplete",
        },
        "provenance_warnings": provenance_warnings,
        "files": {key: str(value) for key, value in paths.items()},
    }
    paths["quality_report"].write_text(
        json.dumps(quality_report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return quality_report
