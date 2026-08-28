"""
Preprocessing : prepare les fichiers CTD lies a Particulate Matter (D052638).

Ce module ne fait AUCUN appel LLM : c'est du code deterministe qui, a partir
des CSV bruts telecharges depuis CTD (data/raw/CTD_D052638_*.csv), produit un
petit jeu de tables de reference propres, filtrees sur :

- le chemical D052638 (Particulate Matter) pour genes / ixns / phenotype / diseases ;
- les etudes humaines (colonne "Organisms" contenant "Homo sapiens") pour les
  fichiers qui portent cette information (ixns, phenotype).

Ces tables sont ensuite reutilisees a deux endroits du pipeline :
- en amont, pour identifier les references (PMIDs) d'etudes d'exposition PM ;
- en aval, par `build_ctd_pm_enrichment.py`, qui n'a plus besoin de refaire ce
  filtrage lui-meme.

Le fichier "genes" CTD n'a pas de colonne Chemical ID ni Organisms : c'est une
table globale (tous chemicals confondus) utilisee uniquement pour enrichir la
liste de genes humains derivee des interactions PM (ixns_human), avec leurs
compteurs globaux d'interactions/organismes.

Le fichier "diseases" CTD n'a pas de colonne Organisms : le filtre humain n'y
est pas applicable, seul le filtre Chemical ID = D052638 est effectue.

Le fichier "exposure" CTD n'a ni Chemical ID ni Organisms : le PM y est
identifie par une recherche de mots-cles dans la colonne "Stressor Agent"
(texte libre, pipe-separe). Cette partie est deleguee a
`ctd_exposure_candidates.py`, qui fait la meme chose pour O3/NO2/NO.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from src.preprocessing.ctd_exposure_candidates import build_exposure_candidates

PM_CHEMICAL_ID = "D052638"
PM_CHEMICAL_NAME = "Particulate Matter"


def clean_text(value: Any) -> str:
    if pd.isna(value):
        return ""

    text = str(value).strip()

    if text.lower() in {"nan", "none", "null"}:
        return ""

    return text


def is_homo_sapiens(value: Any) -> bool:
    text = clean_text(value).lower()
    return "homo sapiens" in text or text == "human" or "human" in text


def read_ctd_csv(pattern: str, raw_dir: Path) -> pd.DataFrame:
    matches = sorted(raw_dir.glob(pattern))

    if not matches:
        raise FileNotFoundError(
            f"Aucun fichier ne correspond a '{pattern}' dans {raw_dir}."
        )

    # Le nom de fichier contient un horodatage ; on prend le plus recent.
    return pd.read_csv(matches[-1], low_memory=False)


def filter_pm_chemical(df: pd.DataFrame) -> pd.DataFrame:
    return df[
        df["Chemical ID"].fillna("").astype(str).str.strip().eq(PM_CHEMICAL_ID)
    ].copy()


def filter_human(df: pd.DataFrame, organism_col: str = "Organisms") -> pd.DataFrame:
    return df[df[organism_col].apply(is_homo_sapiens)].copy()


def build_genes_human(ixns_human: pd.DataFrame, genes_df: pd.DataFrame) -> pd.DataFrame:
    """Liste des genes humains lies a PM, enrichie avec les compteurs globaux CTD."""

    if ixns_human.empty:
        return pd.DataFrame(
            columns=["gene_symbol", "gene_id", "human_ixn_row_count",
                     "ctd_gene_interaction_count_global", "ctd_gene_organism_count_global"]
        )

    counts = (
        ixns_human.groupby(["Gene Symbol", "Gene ID"], dropna=False)
        .size()
        .reset_index(name="human_ixn_row_count")
        .rename(columns={"Gene Symbol": "gene_symbol", "Gene ID": "gene_id"})
    )

    genes_norm = genes_df.rename(
        columns={
            "Gene Symbol": "gene_symbol",
            "Gene ID": "gene_id",
            "Interaction Count": "ctd_gene_interaction_count_global",
            "Organism Count": "ctd_gene_organism_count_global",
        }
    )

    merged = counts.merge(genes_norm, on=["gene_symbol", "gene_id"], how="left")
    merged = merged.sort_values(
        ["human_ixn_row_count", "gene_symbol"], ascending=[False, True]
    ).reset_index(drop=True)

    return merged


def build_ctd_pm_human_dataset(raw_dir: Path, output_dir: Path) -> dict[str, Any]:
    """Construit les tables PM/humain et les ecrit dans output_dir.

    Retourne un dictionnaire d'audit (comptes avant/apres filtre) qui est
    aussi ecrit tel quel dans output_dir/audit.json par le runner.
    """

    output_dir.mkdir(parents=True, exist_ok=True)

    exposure_df = read_ctd_csv("CTD_D052638_exposure*.csv", raw_dir)
    genes_df = read_ctd_csv("CTD_D052638_genes*.csv", raw_dir)
    ixns_df = read_ctd_csv("CTD_D052638_ixns*.csv", raw_dir)
    phenotype_df = read_ctd_csv("CTD_D052638_phenotype*.csv", raw_dir)
    diseases_df = read_ctd_csv("CTD_D052638_diseases*.csv", raw_dir)

    ixns_pm = filter_pm_chemical(ixns_df)
    ixns_human = filter_human(ixns_pm)

    phenotype_pm = filter_pm_chemical(phenotype_df)
    phenotype_human = filter_human(phenotype_pm)

    diseases_pm = filter_pm_chemical(diseases_df)

    genes_human = build_genes_human(ixns_human, genes_df)

    exposure_pm = build_exposure_candidates("pm", raw_dir)

    outputs = {
        "genes_human.csv": genes_human,
        "ixns_human.csv": ixns_human,
        "phenotype_human.csv": phenotype_human,
        "diseases_pm.csv": diseases_pm,
        "exposure_pm_candidates.csv": exposure_pm,
    }

    for filename, df in outputs.items():
        df.to_csv(output_dir / filename, index=False)

    audit = {
        "pm_chemical_id": PM_CHEMICAL_ID,
        "pm_chemical_name": PM_CHEMICAL_NAME,
        "exposure_rows_total": int(len(exposure_df)),
        "exposure_pm_candidate_rows": int(len(exposure_pm)),
        "genes_rows_total_ctd_global": int(len(genes_df)),
        "genes_human_rows": int(len(genes_human)),
        "ixns_rows_total": int(len(ixns_df)),
        "ixns_pm_rows": int(len(ixns_pm)),
        "ixns_human_rows": int(len(ixns_human)),
        "phenotype_rows_total": int(len(phenotype_df)),
        "phenotype_pm_rows": int(len(phenotype_pm)),
        "phenotype_human_rows": int(len(phenotype_human)),
        "diseases_rows_total": int(len(diseases_df)),
        "diseases_pm_rows": int(len(diseases_pm)),
        "diseases_species_filter": "not_available_in_source",
    }

    return audit
