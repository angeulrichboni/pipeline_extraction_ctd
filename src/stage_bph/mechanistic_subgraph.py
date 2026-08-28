"""Chapitre 5 (nouveau) — sous-graphe mecanistique statique (polluant -> gene -> maladie / phenotype).

Construit, a partir du meme fichier que le chapitre 4 (ctd_icd_mapped_complete.csv),
les triplets non temporels du graphe : affecte_expression_gene, associe_a_maladie,
associe_a_phenotype. Ce module est additif : il ne modifie ni ne relit aucun des
chapitres 1 a 4 existants, il lit leur sortie deja produite.

Perimetre verifie empiriquement sur le projet (cf. document de checkpoint Phase 3) :
  - 200 genes distincts, PM2.5/PM10, 5 chapitres ICD-10 noyau -> tous conserves.
  - 9 categories phenotypiques CTD standardisees (83 formulations), la categorie
    non taggee (206 formulations heterogenes) est ecartee.
  - Aucune ligne CTD ne documente a la fois une maladie et un phenotype pour un
    meme gene : le phenotype est donc un noeud terminal, jamais chaine vers la maladie.
"""
from __future__ import annotations

import csv
import gzip
import json
from collections import defaultdict
from pathlib import Path
from typing import Iterable

CORE_ICD_CHAPTERS = {"06", "09", "10", "15", "16"}  # ICD-10 : VI nerveux, IX circulatoire, X respiratoire, XV grossesse, XVI périnatal

# Les 9 categories phenotypiques CTD retenues (verifie : 10 categories au total
# dans le fichier source, la categorie non taggee ecartee laisse 9, pas 8).
PHENOTYPE_CATEGORIES = {
    "cardiovascular_disease",
    "metabolic_disease",
    "neurodegenerative_disease",
    "other_chronic_disease",
    "perinatal_outcome",
    "renal_disease",
    "respiratory_disease",
    "systemic_inflammation",
    "unclassified",
}

POLLUTANT_ALIASES = {
    "PM2.5": "PM2.5", "PM25": "PM2.5", "PM_2.5": "PM2.5",
    "PM10": "PM10", "PM_10": "PM10",
}

TRIPLET_FIELDS = [
    "relation", "subject_type", "subject_id", "object_type", "object_id",
    "object_label", "pollutant", "pmid_count", "evidence_pmids_sample",
]


def _canon_pollutant(raw: str) -> str | None:
    key = (raw or "").strip().upper().replace(" ", "")
    return POLLUTANT_ALIASES.get(key)


def _open_maybe_gzip(path: Path):
    if str(path).endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8")
    return open(path, "rt", encoding="utf-8", newline="")


def _iter_rows(ctd_path: Path) -> Iterable[dict[str, str]]:
    with _open_maybe_gzip(ctd_path) as f:
        yield from csv.DictReader(f)


def build_mechanistic_subgraph(
    ctd_path: Path,
    output_path: Path,
    pollutants: tuple[str, ...] = ("PM2.5", "PM10"),
    core_chapters: frozenset[str] = frozenset(CORE_ICD_CHAPTERS),
    phenotype_categories: frozenset[str] = frozenset(PHENOTYPE_CATEGORIES),
    gzip_output: bool = False,
) -> dict:
    """Lit ctd_icd_mapped_complete.csv (sortie du chapitre 1) et ecrit les triplets
    mecanistiques statiques. Ne touche a aucun fichier des chapitres 1 a 4.
    """
    pollutants_set = set(pollutants)

    # bucket -> (pmid set,) pour deduplication + tracabilite
    gene_pollutant: dict[tuple[str, str], set[str]] = defaultdict(set)
    gene_disease: dict[tuple[str, str, str, str], set[str]] = defaultdict(set)
    gene_phenotype: dict[tuple[str, str, str, str], set[str]] = defaultdict(set)

    total_rows = 0
    for row in _iter_rows(ctd_path):
        total_rows += 1
        pollutant = _canon_pollutant(row.get("pollutant_specific"))
        if pollutant is None or pollutant not in pollutants_set:
            continue
        gene = (row.get("gene_symbol") or "").strip()
        if not gene:
            continue
        pmid = (row.get("pmid") or "").strip()
        status = row.get("mapping_status")

        # Arete polluant -> gene : toute ligne du perimetre portant un gene.
        gene_pollutant[(pollutant, gene)].add(pmid)

        # Arete gene -> maladie (chapitre ICD noyau uniquement).
        if status == "VALIDATED_ICD":
            chapter = (row.get("icd_chapter") or "").zfill(2)
            if chapter in core_chapters:
                chapter_name = row.get("icd_chapter_name") or ""
                gene_disease[(gene, chapter, chapter_name, pollutant)].add(pmid)

        # Arete gene -> phenotype (categories standardisees uniquement, noeud terminal).
        if status == "VALIDATED_NON_ICD":
            category = row.get("outcome_category") or ""
            if category in phenotype_categories:
                formulation = (row.get("outcome_normalized") or "").strip().lower()
                if formulation:
                    gene_phenotype[(gene, formulation, category, pollutant)].add(pmid)

    with open(output_path, "wt", encoding="utf-8", newline="") if not gzip_output else \
         gzip.open(output_path, "wt", encoding="utf-8", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=TRIPLET_FIELDS)
        writer.writeheader()

        for (pollutant, gene), pmids in sorted(gene_pollutant.items()):
            writer.writerow({
                "relation": "affecte_expression_gene",
                "subject_type": "polluant", "subject_id": pollutant,
                "object_type": "gene", "object_id": gene, "object_label": gene,
                "pollutant": pollutant,
                "pmid_count": len(pmids),
                "evidence_pmids_sample": ";".join(sorted(pmids)[:5]),
            })

        for (gene, chapter, chapter_name, pollutant), pmids in sorted(gene_disease.items()):
            writer.writerow({
                "relation": "associe_a_maladie",
                "subject_type": "gene", "subject_id": gene,
                "object_type": "chapitre_icd", "object_id": chapter, "object_label": chapter_name,
                "pollutant": pollutant,
                "pmid_count": len(pmids),
                "evidence_pmids_sample": ";".join(sorted(pmids)[:5]),
            })

        for (gene, formulation, category, pollutant), pmids in sorted(gene_phenotype.items()):
            writer.writerow({
                "relation": "associe_a_phenotype",
                "subject_type": "gene", "subject_id": gene,
                "object_type": "phenotype", "object_id": formulation, "object_label": category,
                "pollutant": pollutant,
                "pmid_count": len(pmids),
                "evidence_pmids_sample": ";".join(sorted(pmids)[:5]),
            })

    report = {
        "total_ctd_rows_scanned": total_rows,
        "triplets_affecte_expression_gene": len(gene_pollutant),
        "triplets_associe_a_maladie": len(gene_disease),
        "triplets_associe_a_phenotype": len(gene_phenotype),
        "genes_distincts": len({g for _, g in gene_pollutant}),
        "phenotypes_distincts": len({f for _, f, _, _ in gene_phenotype}),
        "output_path": str(output_path),
    }
    return report