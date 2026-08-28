from __future__ import annotations

import csv
import gzip
from datetime import date
from pathlib import Path

from stage_bph.exposure_health_dataset import derive_profile, generate_exposure_health_dataset
from stage_bph.models import Individual


def _write(path: Path, headers: list[str], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)


def _read_gz(path: Path) -> list[dict[str, str]]:
    with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _sample_individual(**overrides) -> Individual:
    base = dict(
        individual_id="P5_01", persona_id="P5", sex="Homme",
        birth_date=date(1990, 1, 1), age_at_start=31,
        household_id="H02", household_role="adulte",
        presence_template="AdulteActif", work_status="office",
        smoking_status="never", baseline_asthma_mode="fixed_true",
        baseline_htn_mode="fixed_false", pregnancy_start=None,
        expected_delivery_date=None, parity_category="",
        is_first_pregnancy=None, pregnancy_presence_modifier="",
        parameter_status="TEST",
    )
    base.update(overrides)
    return Individual(**base)


def test_generate_exposure_health_dataset(tmp_path: Path) -> None:
    windows = tmp_path / "exposure_windows.csv"
    thresholds = tmp_path / "exposure_thresholds.csv"
    p0 = tmp_path / "individual_p0_schedule.csv"
    ctd = tmp_path / "ctd_icd_mapped_complete.csv"
    output = tmp_path / "exposure_health_model_dataset.csv.gz"

    _write(
        windows,
        [
            "individual_id", "persona_id", "household_id", "pollutant", "window_type",
            "window_start", "window_end", "year", "date", "bag_id", "valid_slots",
            "home_slots", "home_minutes", "mean_exposure", "home_mean_exposure",
            "max_exposure", "sum_exposure",
        ],
        [[
            "P5_01", "P5", "H02", "PM25", "daily", "2021-01-01T00:00",
            "2021-01-01T23:45", "2021", "2021-01-01", "daily|P5_01|2021-01-01|PM25",
            "96", "80", "1200", "20", "24", "80", "1920",
        ]],
    )
    _write(
        thresholds,
        [
            "individual_id", "persona_id", "household_id", "pollutant", "window_type",
            "window_start", "window_end", "year", "date", "bag_id", "mean_threshold_value",
            "max_threshold_value", "mil_threshold_value", "mean_exposure", "max_exposure",
            "mean_exceedance", "max_exceedance", "mil_exceedance", "instance_count",
            "above_threshold_slots", "proportion_above_threshold", "excess_mean", "excess_max",
            "excess_burden", "mil_min_proportion",
        ],
        [[
            "P5_01", "P5", "H02", "PM25", "daily", "2021-01-01T00:00",
            "2021-01-01T23:45", "2021", "2021-01-01", "daily|P5_01|2021-01-01|PM25",
            "15", "15", "15", "20", "80", "1", "1", "1", "96", "30", "0.3125",
            "5", "65", "60", "0.05",
        ]],
    )
    _write(
        p0,
        [
            "individual_id", "persona_id", "calendar_year", "age", "sex", "event_id",
            "event_name", "horizon", "p0_value", "rule_id", "condition", "scenario",
            "evidence_status", "use_status", "source", "scientific_note",
        ],
        [[
            "P5_01", "P5", "2021", "31", "Homme", "E02", "Hospitalisation pour asthme",
            "Annuel", "0.005", "R009", "Asthme préexistant", "CENTRAL", "TEST",
            "UTILISABLE", "source", "note",
        ]],
    )
    _write(
        ctd,
        [
            "association_id", "pmid", "pollutant_general", "pollutant_specific",
            "outcome_normalized", "measure_type", "effect_value_numeric",
            "effect_direction", "exposure_increment_value", "exposure_window_category",
            "exposure_duration_unit", "mapping_status", "icd_chapter", "icd_chapter_name",
            "normalized_health_concept",
        ],
        [
            ["a1", "123", "PM", "PM2.5", "asthma", "RR", "1.10", "increase", "10", "short_term", "day", "VALIDATED_ICD", "10", "Diseases of the respiratory system", "asthma"],
            ["a2", "124", "PM", "PM2.5", "stroke", "RR", "1.05", "increase", "10", "long_term", "year", "VALIDATED_ICD", "06", "Diseases of the nervous system", "stroke"],
        ],
    )

    individuals = {"P5_01": _sample_individual()}

    report = generate_exposure_health_dataset(
        windows_path=windows,
        thresholds_path=thresholds,
        p0_schedule_path=p0,
        ctd_path=ctd,
        output_path=output,
        individuals=individuals,
        negative_ratio=0.0,
    )
    rows = _read_gz(output)
    assert report["output_rows"] == 1
    assert rows[0]["link_label"] == "1"
    assert rows[0]["icd_chapter"] == "10"
    assert float(rows[0]["health_score"]) > 0
    assert rows[0]["p0_event_ids"] == "E02"

    # Famille B -- profil généralisé, dérivé du persona P5 (asthme préexistant).
    assert rows[0]["classe_age"] == "adulte"
    assert rows[0]["grossesse"] == "non"
    assert rows[0]["pathologie_preexistante"] == "respiratoire"

    # Famille A -- colonnes de trajectoire présentes même sans fichier trajectoire
    # (dégradation propre en chaîne vide, jamais d'erreur).
    assert "window_index" in rows[0]
    assert "cumulative_exposure" in rows[0]


def test_negative_rows_are_zeroed_and_labelled(tmp_path: Path) -> None:
    """Vérifie explicitement le comportement documenté de la fuite de cible :
    les lignes unknown_sampled_negative ont bien un score nul par construction
    -- ce test protège la documentation, pas une propriété désirable en soi."""
    windows = tmp_path / "exposure_windows.csv"
    thresholds = tmp_path / "exposure_thresholds.csv"
    p0 = tmp_path / "individual_p0_schedule.csv"
    ctd = tmp_path / "ctd_icd_mapped_complete.csv"
    output = tmp_path / "exposure_health_model_dataset.csv.gz"

    _write(
        windows,
        [
            "individual_id", "persona_id", "household_id", "pollutant", "window_type",
            "window_start", "window_end", "year", "date", "bag_id", "valid_slots",
            "home_slots", "home_minutes", "mean_exposure", "home_mean_exposure",
            "max_exposure", "sum_exposure",
        ],
        [[
            "P5_01", "P5", "H02", "PM25", "daily", "2021-01-01T00:00",
            "2021-01-01T23:45", "2021", "2021-01-01", "daily|P5_01|2021-01-01|PM25",
            "96", "80", "1200", "20", "24", "80", "1920",
        ]],
    )
    _write(
        thresholds,
        [
            "individual_id", "persona_id", "household_id", "pollutant", "window_type",
            "window_start", "window_end", "year", "date", "bag_id", "mean_threshold_value",
            "max_threshold_value", "mil_threshold_value", "mean_exposure", "max_exposure",
            "mean_exceedance", "max_exceedance", "mil_exceedance", "instance_count",
            "above_threshold_slots", "proportion_above_threshold", "excess_mean", "excess_max",
            "excess_burden", "mil_min_proportion",
        ],
        [[
            "P5_01", "P5", "H02", "PM25", "daily", "2021-01-01T00:00",
            "2021-01-01T23:45", "2021", "2021-01-01", "daily|P5_01|2021-01-01|PM25",
            "15", "15", "15", "20", "80", "1", "1", "1", "96", "30", "0.3125",
            "5", "65", "60", "0.05",
        ]],
    )
    _write(p0, ["individual_id", "persona_id", "calendar_year", "age", "sex", "event_id",
                "event_name", "horizon", "p0_value", "rule_id", "condition", "scenario",
                "evidence_status", "use_status", "source", "scientific_note"], [])
    _write(
        ctd,
        [
            "association_id", "pmid", "pollutant_general", "pollutant_specific",
            "outcome_normalized", "measure_type", "effect_value_numeric",
            "effect_direction", "exposure_increment_value", "exposure_window_category",
            "exposure_duration_unit", "mapping_status", "icd_chapter", "icd_chapter_name",
        ],
        [
            ["a1", "123", "PM", "PM2.5", "asthma", "RR", "1.10", "increase", "10", "short_term", "day", "VALIDATED_ICD", "10", "Diseases of the respiratory system"],
            ["a2", "124", "PM", "PM10", "stroke", "RR", "1.05", "increase", "10", "long_term", "year", "VALIDATED_ICD", "06", "Diseases of the nervous system"],
        ],
    )

    generate_exposure_health_dataset(
        windows_path=windows, thresholds_path=thresholds, p0_schedule_path=p0,
        ctd_path=ctd, output_path=output, negative_ratio=1.0,
        core_chapters_only=False,
    )
    rows = _read_gz(output)
    negatives = [r for r in rows if r["link_label"] == "0"]
    assert negatives, "au moins une ligne unknown_sampled_negative attendue"
    for row in negatives:
        assert row["window_evidence"] == "unknown_sampled_negative"
        assert float(row["health_score"]) == 0.0
        assert float(row["association_strength"]) == 0.0
        assert float(row["evidence_weight"]) == 0.0


def test_derive_profile_pregnancy_window() -> None:
    individual = _sample_individual(
        individual_id="P3_01", persona_id="P3",
        pregnancy_start=date(2021, 3, 1), expected_delivery_date=date(2021, 12, 1),
    )
    classe_age, grossesse, pathologie = derive_profile("P3", individual, "2021-06-15")
    assert classe_age == "adulte"
    assert grossesse == "oui"
    assert pathologie == "aucune"

    # Hors de la période de grossesse -> "non", jamais d'erreur.
    classe_age, grossesse, pathologie = derive_profile("P3", individual, "2020-01-01")
    assert grossesse == "non"

    # Sans config individuelle -> retombe sur "non" plutôt que d'échouer.
    classe_age, grossesse, pathologie = derive_profile("P3", None, "2021-06-15")
    assert grossesse == "non"
