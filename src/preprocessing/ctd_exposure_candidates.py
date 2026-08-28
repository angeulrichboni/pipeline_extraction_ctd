"""
Preprocessing : identifie, pour chacun des 4 polluants suivis par le projet,
les etudes d'exposition CTD ou ce polluant est mentionne comme Stressor
Agent, et les PMIDs correspondants.

Les 4 fichiers CTD_*_exposure*.csv partagent la meme structure (colonnes
Reference/Stressor Agent/Receptors/...), avec un vocabulaire controle CTD
dans "Stressor Agent" (ex. "Particulate Matter", "Ozone", "Nitrogen
Dioxide", "Nitric Oxide") : on peut donc matcher sur le nom canonique du
polluant, pipe-separe, dans ce champ.

Seul PM (D052638) a, en plus de l'exposure, des exports genes/ixns/
phenotype/diseases dans ce projet (voir ctd_pm_human_dataset.py, qui
reutilise `build_exposure_candidates("pm", ...)` de ce module pour ne pas
dupliquer cette logique). O3/NO2/NO n'ont que l'exposure : ce module est
leur seule source de selection de PMIDs pour le moment.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

POLLUTANTS: dict[str, dict[str, Any]] = {
    "pm": {
        "ctd_id": "D052638",
        "exposure_pattern": "CTD_D052638_exposure*.csv",
        "keywords": [
            "particulate matter",
            "pm2.5",
            "pm 2.5",
            "pm10",
            "pm 10",
            "pm1",
            "pm 1",
            "fine particulate",
            "fine particles",
            "coarse particles",
            "ultrafine particle",
            "ultrafine particles",
        ],
    },
    "o3": {
        "ctd_id": "D010126",
        "exposure_pattern": "CTD_D010126_exposure*.csv",
        "keywords": ["ozone"],
    },
    "no2": {
        "ctd_id": "D009585",
        "exposure_pattern": "CTD_D009585_exposure*.csv",
        "keywords": ["nitrogen dioxide"],
    },
    "no": {
        "ctd_id": "D009569",
        "exposure_pattern": "CTD_D009569_exposure*.csv",
        "keywords": ["nitric oxide"],
    },
}


def clean_text(value: Any) -> str:
    if pd.isna(value):
        return ""

    text = str(value).strip()

    if text.lower() in {"nan", "none", "null"}:
        return ""

    return text


def matches_keywords(value: Any, keywords: list[str]) -> bool:
    text = clean_text(value).lower()
    return any(keyword in text for keyword in keywords)


def read_ctd_csv(pattern: str, raw_dir: Path) -> pd.DataFrame:
    matches = sorted(raw_dir.glob(pattern))

    if not matches:
        raise FileNotFoundError(
            f"Aucun fichier ne correspond a '{pattern}' dans {raw_dir}."
        )

    return pd.read_csv(matches[-1], low_memory=False)


def build_exposure_candidates(pollutant_key: str, raw_dir: Path) -> pd.DataFrame:
    if pollutant_key not in POLLUTANTS:
        raise ValueError(
            f"Polluant inconnu '{pollutant_key}'. Attendu : {list(POLLUTANTS)}."
        )

    config = POLLUTANTS[pollutant_key]

    exposure_df = read_ctd_csv(config["exposure_pattern"], raw_dir)

    candidates = exposure_df[
        exposure_df["Stressor Agent"].apply(
            lambda value: matches_keywords(value, config["keywords"])
        )
    ].copy()

    candidates = candidates.rename(columns={"Reference": "pmid"})
    candidates["pmid"] = candidates["pmid"].apply(clean_text)
    candidates = candidates[candidates["pmid"].astype(str).str.len() > 0]
    candidates = candidates.drop_duplicates(subset=["pmid"]).reset_index(drop=True)

    candidates["pollutant_key"] = pollutant_key
    candidates["ctd_chemical_id"] = config["ctd_id"]

    return candidates


def build_all_exposure_candidates(
    raw_dir: Path,
    output_dir: Path,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)

    audit: dict[str, Any] = {}
    all_pmids: set[str] = set()

    for pollutant_key in POLLUTANTS:
        candidates = build_exposure_candidates(pollutant_key, raw_dir)
        candidates.to_csv(
            output_dir / f"{pollutant_key}_exposure_candidates.csv",
            index=False,
        )

        audit[f"{pollutant_key}_candidate_rows"] = int(len(candidates))
        all_pmids.update(candidates["pmid"].tolist())

    manifest_path = output_dir / "all_pollutants_pmids.txt"
    ordered_pmids = sorted(all_pmids, key=lambda pmid: (len(pmid), pmid))
    manifest_path.write_text("\n".join(ordered_pmids))

    audit["all_pollutants_unique_pmids"] = len(all_pmids)
    audit["all_pollutants_manifest"] = str(manifest_path)

    return audit
