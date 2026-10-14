"""Centralized project paths; CTD_DATA_ROOT selects the active output root."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProjectPaths:
    project_root: Path
    data_dir: Path
    raw_dir: Path
    processed_dir: Path

    # `prototype_dir` is the name used throughout the codebase; it currently
    # points at data/processed (kept as its own field for readability).
    prototype_dir: Path

    segmented_documents_dir: Path

    pollutant_output_dir: Path
    outcome_output_dir: Path
    effect_measure_output_dir: Path
    association_output_dir: Path
    population_output_dir: Path
    exposure_temporal_output_dir: Path
    multi_pmid_output_dir: Path
    final_quality_control_dir: Path
    final_inspection_dir: Path
    icd_output_dir: Path

    logs_dir: Path

    def ensure_base_dirs(self) -> None:
        dirs = [
            self.data_dir,
            self.raw_dir,
            self.processed_dir,
            self.segmented_documents_dir,
            self.pollutant_output_dir,
            self.outcome_output_dir,
            self.effect_measure_output_dir,
            self.association_output_dir,
            self.population_output_dir,
            self.exposure_temporal_output_dir,
            self.multi_pmid_output_dir,
            self.final_quality_control_dir,
            self.final_inspection_dir,
            self.icd_output_dir,
            self.logs_dir,
        ]

        for path in dirs:
            path.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Directory aliases used by a handful of runners.
    # ------------------------------------------------------------------

    @property
    def final_quality_control_output_dir(self) -> Path:
        return self.final_quality_control_dir

    @property
    def final_inspection_output_dir(self) -> Path:
        return self.final_inspection_dir

    @property
    def multi_pmid_runner_output_dir(self) -> Path:
        return self.multi_pmid_output_dir

    # ------------------------------------------------------------------
    # Segmented documents
    # ------------------------------------------------------------------

    def segmented_document_path(self, pmid: str | int) -> Path:
        return self.segmented_documents_dir / f"{pmid}_segmented.json"

    @property
    def segmented_manifest_test_csv(self) -> Path:
        return self.segmented_documents_dir / "segmented_documents_manifest.csv"

    # ------------------------------------------------------------------
    # Per-PMID agent outputs
    # ------------------------------------------------------------------

    def pollutant_output_path(self, pmid: str | int) -> Path:
        return self.pollutant_output_dir / f"{pmid}_pollutants.json"

    def outcome_output_path(self, pmid: str | int) -> Path:
        return self.outcome_output_dir / f"{pmid}_outcomes.json"

    def effect_measure_output_path(self, pmid: str | int) -> Path:
        return self.effect_measure_output_dir / f"{pmid}_effect_measures.json"

    def association_json_path(self, pmid: str | int) -> Path:
        return self.association_output_dir / f"{pmid}_associations.json"

    def association_csv_path(self, pmid: str | int) -> Path:
        return self.association_output_dir / f"{pmid}_associations.csv"

    def population_output_path(self, pmid: str | int) -> Path:
        return self.population_output_dir / f"{pmid}_population.json"

    def exposure_temporal_output_path(self, pmid: str | int) -> Path:
        return self.exposure_temporal_output_dir / f"{pmid}_exposure_temporal.json"

    # ------------------------------------------------------------------
    # Merge / QC outputs
    # ------------------------------------------------------------------

    @property
    def associations_all_test_csv(self) -> Path:
        return self.multi_pmid_output_dir / "associations_all_test.csv"

    @property
    def associations_clean_test_csv(self) -> Path:
        return self.final_quality_control_dir / "associations_clean_test.csv"

    @property
    def associations_rejected_test_csv(self) -> Path:
        return self.final_quality_control_dir / "associations_rejected_test.csv"


def find_project_root() -> Path:
    """src/config/paths.py -> project root is parents[2]."""
    return Path(__file__).resolve().parents[2]


def build_paths() -> ProjectPaths:
    project_root = find_project_root()

    data_dir = project_root / "data"
    raw_dir = data_dir / "raw"

    active_data_root = Path(os.getenv("CTD_DATA_ROOT", str(data_dir / "processed")))

    if not active_data_root.is_absolute():
        active_data_root = project_root / active_data_root

    processed_dir = active_data_root
    prototype_dir = processed_dir

    segmented_documents_dir = processed_dir / "segmented_documents"

    agent_outputs_dir = processed_dir / "agent_outputs"
    pollutant_output_dir = agent_outputs_dir / "pollutant_extractor"
    outcome_output_dir = agent_outputs_dir / "outcome_extractor"
    effect_measure_output_dir = agent_outputs_dir / "effect_measure_extractor"
    association_output_dir = agent_outputs_dir / "association_builder"
    population_output_dir = agent_outputs_dir / "population_extractor"
    exposure_temporal_output_dir = agent_outputs_dir / "time_extractor"
    multi_pmid_output_dir = agent_outputs_dir / "multi_pmid_runner"
    final_quality_control_dir = agent_outputs_dir / "final_quality_control"
    final_inspection_dir = agent_outputs_dir / "final_inspection"
    icd_output_dir = processed_dir / "icd"

    logs_dir = processed_dir / "logs"

    return ProjectPaths(
        project_root=project_root,
        data_dir=data_dir,
        raw_dir=raw_dir,
        processed_dir=processed_dir,
        prototype_dir=prototype_dir,
        segmented_documents_dir=segmented_documents_dir,
        pollutant_output_dir=pollutant_output_dir,
        outcome_output_dir=outcome_output_dir,
        effect_measure_output_dir=effect_measure_output_dir,
        association_output_dir=association_output_dir,
        population_output_dir=population_output_dir,
        exposure_temporal_output_dir=exposure_temporal_output_dir,
        multi_pmid_output_dir=multi_pmid_output_dir,
        final_quality_control_dir=final_quality_control_dir,
        final_inspection_dir=final_inspection_dir,
        icd_output_dir=icd_output_dir,
        logs_dir=logs_dir,
    )


paths = build_paths()