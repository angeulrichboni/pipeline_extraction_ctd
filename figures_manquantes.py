#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Génération des figures manquantes pour la soutenance
=====================================================

Ce script produit uniquement les figures qui NE SONT PAS déjà présentes
dans le dossier `figures/` du projet, et applique la palette du template
de soutenance (Université de Bordeaux / BPH).

Usage
-----
    python figures_manquantes.py
    python figures_manquantes.py --racine /chemin/vers/pipeline_exposition_sante
    python figures_manquantes.py --figure F1        # une seule figure

Entrées attendues (relatives à --racine)
----------------------------------------
    outputs/ctd_icd_mapped_complete.csv
    outputs/exposure_health_model_dataset.csv.gz

Sorties
-------
    figures/visualisations_soutenance/*.png  (300 dpi)
    figures/visualisations_soutenance/*.csv  (données sous-jacentes, pour audit)
"""

from __future__ import annotations

import argparse
import gzip
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # rendu sans interface graphique

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

# =============================================================================
# 1. IDENTITÉ VISUELLE — alignée sur le template de soutenance
# =============================================================================

PALETTE = {
    "cyan":      "#009DE0",   # Phase 1
    "navy":      "#17324D",   # Phase 1 (accent)
    "turquoise": "#00ACA9",   # Phase 2
    "green":     "#76B82A",   # Phase 2 (accent)
    "brown":     "#3B1C13",   # Phase 3
    "copper":    "#A6612F",   # Phase 3 (accent)
    "amber":     "#B26A00",   # limites / éléments non validés
    "ink":       "#263238",   # texte
    "muted":     "#6B7A82",   # texte secondaire
    "hair":      "#D9DFE2",   # filets
    "grayBg":    "#F2F5F6",
}

# Ordre et libellés courts des chapitres ICD-10 du périmètre (numérotation
# = position dans l'ordre officiel ICD-10 I-XXII, cf. config/icd10_chapter_numbering.csv)
CHAPITRES_NOYAU = {
    "06": "Système nerveux",
    "09": "Système circulatoire",
    "10": "Système respiratoire",
    "15": "Grossesse et puerpéralité",
    "16": "Période périnatale",
}


def appliquer_style() -> None:
    """Style global : sobre, sans 3D, sans ombre, quadrillage minimal."""
    sns.set_theme(style="whitegrid")
    plt.rcParams.update({
        "figure.dpi": 110,
        "savefig.dpi": 300,
        "savefig.bbox": "tight",
        "savefig.facecolor": "white",
        "font.family": "sans-serif",
        "font.sans-serif": ["Arial", "DejaVu Sans", "Liberation Sans"],
        "font.size": 11,
        "axes.titlesize": 13,
        "axes.titleweight": "bold",
        "axes.labelsize": 11,
        "axes.edgecolor": PALETTE["hair"],
        "axes.labelcolor": PALETTE["ink"],
        "axes.titlecolor": PALETTE["ink"],
        "axes.grid": True,
        "axes.axisbelow": True,
        "grid.color": PALETTE["hair"],
        "grid.linewidth": 0.6,
        "xtick.color": PALETTE["muted"],
        "ytick.color": PALETTE["muted"],
        "legend.frameon": False,
        "figure.facecolor": "white",
    })


def nettoyer_axes(ax, garder_x=False, garder_y=True) -> None:
    """Retire les bordures superflues et le quadrillage inutile."""
    for cote in ("top", "right"):
        ax.spines[cote].set_visible(False)
    ax.spines["left"].set_color(PALETTE["hair"])
    ax.spines["bottom"].set_color(PALETTE["hair"])
    ax.xaxis.grid(garder_x)
    ax.yaxis.grid(garder_y)


def annoter_barres_h(ax, valeurs, decalage=0.01, fmt="{:,.0f}") -> None:
    """Annote des barres horizontales avec leur valeur, à droite de la barre."""
    maxi = max(valeurs) if len(valeurs) else 1
    for i, v in enumerate(valeurs):
        ax.text(
            v + maxi * decalage, i, fmt.format(v).replace(",", " "),
            va="center", ha="left", fontsize=10,
            color=PALETTE["ink"], fontweight="bold",
        )


# =============================================================================
# 2. CHARGEMENT DES DONNÉES
# =============================================================================

def charger_ctd_mappe(racine: Path) -> pd.DataFrame:
    """Charge le référentiel CTD normalisé ICD-10 (sortie du chapitre 1)."""
    chemin = racine / "outputs" / "ctd_icd_mapped_complete.csv"
    if not chemin.exists():
        raise FileNotFoundError(f"Fichier introuvable : {chemin}")
    return pd.read_csv(chemin, low_memory=False)


def charger_dataset(racine: Path) -> pd.DataFrame:
    """Charge le dataset final exposition-santé (sortie du chapitre 4).

    Seules les colonnes utiles aux figures sont lues, pour limiter la mémoire :
    le fichier complet dépasse plusieurs millions de lignes.
    """
    chemin = racine / "outputs" / "exposure_health_model_dataset.csv.gz"
    if not chemin.exists():
        raise FileNotFoundError(f"Fichier introuvable : {chemin}")

    colonnes = [
        "pollutant", "window_type", "icd_chapter", "icd_chapter_name",
        "link_label", "window_evidence", "association_strength",
        "association_beta_mean", "effect_measure_count",
        "pmid_count", "outcome_count", "evidence_weight",
    ]
    with gzip.open(chemin, "rt") as flux:
        return pd.read_csv(flux, usecols=colonnes, low_memory=False)


# =============================================================================
# 3. FIGURES
# =============================================================================

def figure_F1_statuts_mapping(racine: Path, sortie: Path) -> None:
    """F1 — Répartition des statuts de normalisation ICD-10.

    Destination : diapositive « 92 309 associations PM2.5 / PM10 normalisées ».
    Remplace les barres dessinées à la main dans le template.
    """
    ctd = charger_ctd_mappe(racine)

    # Périmètre : uniquement PM2.5 et PM10, comme annoncé dans la présentation
    polluants_pm = ctd["pollutant_specific"].astype(str).str.upper().str.replace(" ", "", regex=False)
    ctd_pm = ctd[polluants_pm.isin({"PM2.5", "PM25", "PM10", "PM_10"})]

    comptes = (
        ctd_pm["mapping_status"]
        .value_counts()
        .reindex(["VALIDATED_ICD", "VALIDATED_NON_ICD", "VALIDATED_EXCLUDED", "UNMAPPED_REVIEW"])
        .fillna(0)
        .astype(int)
    )

    couleurs = [PALETTE["turquoise"], PALETTE["green"], PALETTE["muted"], PALETTE["hair"]]

    fig, ax = plt.subplots(figsize=(9, 4.2))
    positions = range(len(comptes))
    ax.barh(list(positions), comptes.values, color=couleurs, height=0.62)
    ax.set_yticks(list(positions))
    ax.set_yticklabels(comptes.index, fontsize=11, color=PALETTE["ink"])
    ax.invert_yaxis()
    ax.set_xlabel("Nombre d'associations CTD (PM2.5 et PM10)")
    ax.set_title(f"Normalisation ICD-10 — {comptes.sum():,} associations traitées".replace(",", " "))
    annoter_barres_h(ax, comptes.values)
    ax.set_xlim(0, comptes.max() * 1.16)
    nettoyer_axes(ax, garder_x=True, garder_y=False)

    fig.savefig(sortie / "F1_statuts_mapping_icd10.png")
    plt.close(fig)
    comptes.rename("nombre").to_csv(sortie / "F1_statuts_mapping_icd10.csv")
    print("  F1 — statuts de mapping ICD-10")


def figure_F2_composition_mesures(racine: Path, sortie: Path) -> None:
    """F2 — Composition des mesures d'effet par type statistique.

    Destination : annexe consacrée à la transformation des mesures d'effet.
    Justifie visuellement pourquoi une conversion en coefficient homogène
    est nécessaire avant toute agrégation.
    """
    ctd = charger_ctd_mappe(racine)
    ctd = ctd[ctd["mapping_status"] == "VALIDATED_ICD"].copy()

    ctd["type_mesure"] = ctd["measure_type"].astype(str).str.strip().str.lower()
    libelles = {
        "or": "Odds ratio (OR)",
        "rr": "Risk ratio (RR)",
        "hr": "Hazard ratio (HR)",
        "irr": "Incidence rate ratio (IRR)",
        "percent_change": "Variation en pourcentage",
        "beta": "Coefficient bêta brut",
    }
    ctd["libelle"] = ctd["type_mesure"].map(libelles).fillna("Autre / non renseigné")

    comptes = ctd["libelle"].value_counts()

    # Le coefficient bêta brut n'est pas converti par le pipeline : couleur d'alerte
    couleurs = [
        PALETTE["amber"] if "bêta" in libelle or "Autre" in libelle else PALETTE["cyan"]
        for libelle in comptes.index
    ]

    fig, ax = plt.subplots(figsize=(9, 4.4))
    positions = range(len(comptes))
    ax.barh(list(positions), comptes.values, color=couleurs, height=0.62)
    ax.set_yticks(list(positions))
    ax.set_yticklabels(comptes.index, fontsize=11, color=PALETTE["ink"])
    ax.invert_yaxis()
    ax.set_xlabel("Nombre de lignes CTD validées ICD-10")
    ax.set_title("Hétérogénéité des mesures d'effet rapportées dans la littérature")
    annoter_barres_h(ax, comptes.values)
    ax.set_xlim(0, comptes.max() * 1.16)
    nettoyer_axes(ax, garder_x=True, garder_y=False)

    fig.savefig(sortie / "F2_composition_mesures_effet.png")
    plt.close(fig)
    comptes.rename("nombre").to_csv(sortie / "F2_composition_mesures_effet.csv")
    print("  F2 — composition des mesures d'effet")


def figure_F3_positifs_negatifs(racine: Path, sortie: Path) -> None:
    """F3 — Liens positifs et candidats de comparaison par chapitre ICD-10.

    Destination : diapositive « Chapitre 4 — Construire les candidats de liens ».
    Rend visible l'équilibre de l'échantillonnage et le vocabulaire retenu
    (candidats de comparaison, non « négatifs prouvés »).
    """
    dataset = charger_dataset(racine)
    dataset["icd_chapter"] = dataset["icd_chapter"].astype(str).str.zfill(2)

    tableau = (
        dataset.groupby(["icd_chapter", "link_label"])
        .size()
        .unstack(fill_value=0)
        .reindex(list(CHAPITRES_NOYAU.keys()), fill_value=0)
    )
    tableau.columns = ["Candidats de comparaison", "Liens documentés"][: tableau.shape[1]]
    tableau.index = [CHAPITRES_NOYAU[code] for code in tableau.index]

    fig, ax = plt.subplots(figsize=(10, 4.6))
    tableau.plot(
        kind="barh", stacked=True, ax=ax, width=0.62,
        color=[PALETTE["hair"], PALETTE["turquoise"]],
    )
    ax.invert_yaxis()
    ax.set_xlabel("Nombre de lignes du dataset final")
    ax.set_ylabel("")
    ax.set_title("Composition du dataset par chapitre ICD-10")
    ax.legend(
        loc="lower center", bbox_to_anchor=(0.5, -0.30),
        ncol=2, fontsize=10,
    )
    nettoyer_axes(ax, garder_x=True, garder_y=False)

    fig.savefig(sortie / "F3_positifs_negatifs_par_chapitre.png")
    plt.close(fig)
    tableau.to_csv(sortie / "F3_positifs_negatifs_par_chapitre.csv")
    print("  F3 — liens positifs et candidats de comparaison")


def figure_F4_force_association(racine: Path, sortie: Path) -> None:
    """F4 — Force d'association par chapitre et par échelle temporelle.

    Destination : annexe sur les métadonnées de traçabilité.
    Ne concerne que les liens documentés : la force vaut zéro par construction
    pour les candidats de comparaison, les inclure fausserait la lecture.
    """
    dataset = charger_dataset(racine)
    positifs = dataset[dataset["link_label"] == 1].copy()
    positifs["icd_chapter"] = positifs["icd_chapter"].astype(str).str.zfill(2)
    positifs = positifs[positifs["icd_chapter"].isin(CHAPITRES_NOYAU)]
    positifs["Chapitre"] = positifs["icd_chapter"].map(CHAPITRES_NOYAU)
    positifs["Échelle"] = positifs["window_type"].map(
        {"daily": "Journalière (aiguë)", "annual": "Annuelle (chronique)"}
    )

    # Une valeur unique par combinaison : la force est constante au sein d'un bucket
    resume = (
        positifs.groupby(["Chapitre", "Échelle", "pollutant"])["association_strength"]
        .first()
        .reset_index()
    )

    fig, ax = plt.subplots(figsize=(10, 4.8))
    sns.barplot(
        data=resume, y="Chapitre", x="association_strength", hue="Échelle",
        palette=[PALETTE["turquoise"], PALETTE["navy"]], ax=ax, errorbar=None,
    )
    ax.set_xlabel("Force d'association (0 à 1)")
    ax.set_ylabel("")
    ax.set_xlim(0, 1.05)
    ax.set_title("Force des liens documentés, par chapitre et échelle temporelle")
    ax.legend(title="", loc="lower right", fontsize=10)
    nettoyer_axes(ax, garder_x=True, garder_y=False)

    fig.savefig(sortie / "F4_force_association_par_chapitre.png")
    plt.close(fig)
    resume.to_csv(sortie / "F4_force_association_par_chapitre.csv", index=False)
    print("  F4 — force d'association par chapitre")


def figure_F5_poids_preuve(racine: Path, sortie: Path) -> None:
    """F5 — Poids de preuve : publications et formulations distinctes.

    Destination : annexe sur les métadonnées de traçabilité.
    Montre sur quelle quantité de littérature repose chaque lien documenté.
    """
    dataset = charger_dataset(racine)
    positifs = dataset[dataset["link_label"] == 1].copy()
    positifs["icd_chapter"] = positifs["icd_chapter"].astype(str).str.zfill(2)
    positifs = positifs[positifs["icd_chapter"].isin(CHAPITRES_NOYAU)]
    positifs["Chapitre"] = positifs["icd_chapter"].map(CHAPITRES_NOYAU)

    resume = (
        positifs.groupby(["Chapitre", "pollutant", "window_type"])
        .agg(
            publications=("pmid_count", "first"),
            formulations=("outcome_count", "first"),
            poids_preuve=("evidence_weight", "first"),
        )
        .reset_index()
    )

    fig, ax = plt.subplots(figsize=(9, 5.0))
    nuage = ax.scatter(
        resume["publications"], resume["formulations"],
        s=60 + resume["poids_preuve"] * 220,
        c=resume["poids_preuve"], cmap="YlGnBu",
        edgecolor=PALETTE["navy"], linewidth=0.6, alpha=0.85,
    )
    ax.set_xlabel("Nombre de publications distinctes (PMID)")
    ax.set_ylabel("Nombre de formulations d'outcome distinctes")
    ax.set_title("Assise documentaire de chaque lien positif")
    barre = fig.colorbar(nuage, ax=ax, pad=0.02)
    barre.set_label("Poids de preuve", fontsize=10, color=PALETTE["ink"])
    barre.outline.set_edgecolor(PALETTE["hair"])
    nettoyer_axes(ax, garder_x=True, garder_y=True)

    fig.savefig(sortie / "F5_poids_preuve.png")
    plt.close(fig)
    resume.to_csv(sortie / "F5_poids_preuve.csv", index=False)
    print("  F5 — poids de preuve")


# =============================================================================
# 4. ORCHESTRATION
# =============================================================================

FIGURES = {
    "F1": figure_F1_statuts_mapping,
    "F2": figure_F2_composition_mesures,
    "F3": figure_F3_positifs_negatifs,
    "F4": figure_F4_force_association,
    "F5": figure_F5_poids_preuve,
}


def main() -> None:
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument(
        "--racine", type=Path, default=Path("."),
        help="Racine du projet pipeline_exposition_sante (défaut : répertoire courant)",
    )
    analyseur.add_argument(
        "--figure", choices=sorted(FIGURES), default=None,
        help="Générer une seule figure (défaut : toutes)",
    )
    arguments = analyseur.parse_args()

    sortie = arguments.racine / "figures" / "visualisations_soutenance"
    sortie.mkdir(parents=True, exist_ok=True)

    appliquer_style()

    a_generer = [arguments.figure] if arguments.figure else sorted(FIGURES)
    print(f"Génération dans : {sortie}")
    for cle in a_generer:
        try:
            FIGURES[cle](arguments.racine, sortie)
        except FileNotFoundError as erreur:
            print(f"  {cle} — ignorée : {erreur}")
        except Exception as erreur:  # noqa: BLE001
            print(f"  {cle} — échec : {type(erreur).__name__} : {erreur}")

    print("Terminé.")


if __name__ == "__main__":
    main()