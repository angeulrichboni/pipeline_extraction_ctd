"""
Fusion finale : rassemble dans une seule table

- les associations polluant/outcome deja enrichies CTD (genes, maladies,
  phenotypes, deja fusionnes par build_ctd_pm_enrichment.py) ;
- la population/localisation par PMID (run_population_extractor) ;
- la temporalite d'exposition par association (run_time_extractor).

C'est du code deterministe (pandas merge), pas d'appel LLM. Chaque jointure
est optionnelle : si un fichier source n'existe pas encore (etape pas encore
lancee), il est simplement ignore et note dans l'audit, plutot que de faire
planter toute la fusion.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

POPULATION_RENAME = {
    "evidence_sentence": "population_location_evidence",
    "source_section": "population_location_source_section",
    "confidence": "population_location_confidence",
    "status": "population_location_status",
}


def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, low_memory=False)


def join_population_location(
    main_df: pd.DataFrame,
    population_path: Path,
    audit: dict[str, Any],
) -> pd.DataFrame:
    if not population_path.exists():
        audit["population_join"] = "skipped_file_not_found"
        return main_df

    pop_df = _read_csv(population_path)
    pop_df["pmid"] = pop_df["pmid"].astype(str)
    pop_df = pop_df.rename(columns=POPULATION_RENAME)
    # Securite : population est une donnee par PMID, jamais par association ;
    # si une colonne association_id s'y glisse (vide ou non), on la retire
    # pour ne pas entrer en collision avec celle de main_df a la fusion.
    pop_df = pop_df.drop(columns=["association_id"], errors="ignore")

    rows_before = len(main_df)
    merged = main_df.merge(pop_df, on="pmid", how="left", validate="m:1")

    audit["population_join"] = "done"
    audit["population_rows_available"] = int(len(pop_df))
    audit["rows_before_population_join"] = int(rows_before)
    audit["rows_after_population_join"] = int(len(merged))

    return merged


def join_exposure_temporal(
    main_df: pd.DataFrame,
    temporal_path: Path,
    audit: dict[str, Any],
) -> pd.DataFrame:
    if not temporal_path.exists():
        audit["temporal_join"] = "skipped_file_not_found"
        return main_df

    temp_df = _read_csv(temporal_path)
    temp_df["association_id"] = temp_df["association_id"].astype(str)
    # "pmid" est deja present dans main_df ; on l'enleve cote temporel pour
    # eviter un doublon pmid_x/pmid_y apres la jointure.
    temp_df = temp_df.drop(columns=["pmid"], errors="ignore")

    if "association_id" not in main_df.columns:
        audit["temporal_join"] = "skipped_no_association_id_in_main"
        return main_df

    main_df = main_df.copy()
    main_df["association_id"] = main_df["association_id"].astype(str)

    rows_before = len(main_df)
    merged = main_df.merge(temp_df, on="association_id", how="left", validate="m:1")

    audit["temporal_join"] = "done"
    audit["temporal_rows_available"] = int(len(temp_df))
    audit["rows_before_temporal_join"] = int(rows_before)
    audit["rows_after_temporal_join"] = int(len(merged))

    return merged


def build_final_dataset(
    main_path: Path,
    population_path: Path,
    temporal_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    main_df = _read_csv(main_path)
    main_df["pmid"] = main_df["pmid"].astype(str)

    audit: dict[str, Any] = {
        "main_path": str(main_path),
        "main_rows": int(len(main_df)),
        "main_cols": int(len(main_df.columns)),
    }

    merged = join_population_location(main_df, population_path, audit)
    merged = join_exposure_temporal(merged, temporal_path, audit)

    audit["final_rows"] = int(len(merged))
    audit["final_cols"] = int(len(merged.columns))
    audit["row_count_preserved"] = bool(len(merged) == len(main_df))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(output_path, index=False)
    audit["output_path"] = str(output_path)

    return audit