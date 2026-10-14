from __future__ import annotations

from src.agents.effect_measure_extractor import deduplicate_effect_measures
from src.agents.pollutant_extractor import deduplicate_pollutants
from src.quality_control.final_cleaner import make_qc_decision
from src.runners.run_pipeline import STAGES


def test_pollutant_reduce_prefers_highest_confidence_for_same_role() -> None:
    low = {
        "pollutant_specific": "PM2.5",
        "pollutant_role": "target",
        "confidence": 0.4,
        "evidence_sentence": "PM2.5 was measured.",
    }
    high = {
        "pollutant_specific": "PM 2.5",
        "pollutant_role": "target",
        "confidence": 0.9,
        "evidence_sentence": "PM2.5 was measured in ambient air.",
    }

    assert deduplicate_pollutants([low, high]) == [high]


def test_effect_reduce_keeps_distinct_numeric_estimates() -> None:
    base = {
        "pollutant_mention": "PM2.5",
        "outcome_mention": "asthma",
        "measure_type": "OR",
        "ci_lower": "1.01",
        "ci_upper": "1.30",
        "p_value": "0.02",
        "analysis_method": "logistic regression",
        "measure_role": "direct_effect_estimate",
        "keep_for_association_builder": True,
        "confidence": 0.8,
        "evidence_sentence": "First estimate.",
    }

    effects = deduplicate_effect_measures(
        [{**base, "effect_value": "1.15"}, {**base, "effect_value": "1.20"}]
    )
    assert len(effects) == 2


def test_generic_pm_can_be_accepted_but_ambiguous_exposure_is_reviewed() -> None:
    base = {
        "measure_type": "OR",
        "measure_name": "OR",
        "measure_role": "direct_effect_estimate",
        "effect_value": "1.20",
        "ci_lower": "1.05",
        "ci_upper": "1.37",
        "p_value": "",
        "statistical_significance": "significant",
        "outcome_core": "asthma",
        "outcome_role": "primary_outcome",
        "is_human_study": True,
        "evidence_sentence": "PM was associated with asthma.",
        "is_project_target": True,
        "include_in_main_project_analysis": True,
    }

    accepted = make_qc_decision(
        {
            **base,
            "pollutant_general": "PM",
            "pollutant_specific": "particulate matter",
            "pollutant_original_mention": "PM",
            "pollutant_role": "target",
        }
    )
    reviewed = make_qc_decision(
        {
            **base,
            "pollutant_general": "air contaminant",
            "pollutant_specific": "unclassified airborne exposure",
            "pollutant_original_mention": "unclassified airborne exposure",
            "pollutant_role": "ambiguous",
            "is_project_target": False,
        }
    )

    assert accepted["qc_decision"] == "accept"
    assert accepted["qc_include_in_clean_main_analysis"] is True
    assert reviewed["qc_decision"] == "review"


def test_population_and_time_run_before_agent_csv_export() -> None:
    keys = [stage.key for stage in STAGES]
    export_index = keys.index("agent_csv_exports")

    assert keys.index("population_location") < export_index
    assert keys.index("exposure_temporal") < export_index
    assert export_index < keys.index("final_dataset")
