#!/usr/bin/env python3
"""
Traduction de config/icd_mapping_reference.csv (545 règles curées, cible
ICD-11) vers une cible ICD-10 directe, SANS refaire le travail de
curation manuelle (les décisions "quel outcome correspond à quelle
maladie" restent celles déjà auditées).

Deux sources officielles OMS utilisées, toutes deux déjà présentes dans
le projet ou construites lors d'une session précédente :

1. mapping/11To10MapToOneCategory.txt (17 944 lignes, table officielle
   OMS code-à-code ICD-11 -> ICD-10, release 2026-01) : utilisée pour
   les 25 règles ayant déjà un icd_code ICD-11 précis. Lookup direct,
   aucune approximation.

2. config/icd10_chapter_correspondence.csv (déjà vérifié contre le
   fichier officiel OMS 10To11MapToMultipleCategories, cf. son propre
   docstring) : utilisée pour les 197 règles chapitre-seul, faute de
   code ICD-11 précis à traduire. Chaque ligne obtient le chapitre
   ICD-10 correspondant, PLUS le taux de fiabilité officiel mesuré pour
   cette transition de chapitre (colonne mapping_chapter_reliability_pct
   ajoutée, absente de la version ICD-11, pour audit).

icd10_table_reference.csv (notre propre crawl indépendant de l'API OMS,
session précédente, 12597 nœuds) sert à récupérer le TITRE anglais
officiel de chaque chapitre ICD-10 (validation croisée de deuxième
source indépendante).

Numérotation des chapitres : ICD-10 utilise des chiffres romains
(I à XXII). Pour ne PAS casser le code aval qui traite icd_chapter comme
une chaîne numérique à 2 chiffres (zfill(2), ensembles CORE_ICD_CHAPTERS
etc.), on stocke la POSITION du chapitre ICD-10 dans son propre ordre
officiel (I=01, II=02, ..., XXII=22) plutôt que le chiffre romain lui-même.
Le chiffre romain et le titre restent disponibles dans icd_chapter_name
et sont documentés dans un fichier de correspondance à part
(icd10_chapter_numbering.csv) pour audit.

Sortie : config/icd_mapping_reference.csv (écrasé), et un rapport
docs/reference/outcome_to_icd10_mapping_report.csv documentant, pour
CHAQUE règle modifiée, l'ancienne valeur ICD-11, la nouvelle valeur
ICD-10, et la méthode exacte utilisée (code_lookup_officiel ou
chapter_bridge_officiel).
"""

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REFERENCE_PATH = ROOT / "config" / "icd_mapping_reference.csv"
BRIDGE_PATH = ROOT / "config" / "icd10_chapter_correspondence.csv"
CODE_CROSSWALK_PATH = ROOT / "mapping" / "11To10MapToOneCategory.txt"
ICD10_TABLE_PATH = ROOT / "icd10_table_reference.csv"
MIGRATION_REPORT_PATH = ROOT / "docs" / "reference" / "outcome_to_icd10_mapping_report.csv"
CHAPTER_NUMBERING_PATH = ROOT / "config" / "icd10_chapter_numbering.csv"

# Ordre officiel des 22 chapitres ICD-10 (chiffre romain -> position 2 chiffres)
ICD10_CHAPTER_ORDER = [
    "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X",
    "XI", "XII", "XIII", "XIV", "XV", "XVI", "XVII", "XVIII", "XIX", "XX",
    "XXI", "XXII",
]
ROMAN_TO_POSITION = {roman: str(i + 1).zfill(2) for i, roman in enumerate(ICD10_CHAPTER_ORDER)}


def load_code_crosswalk():
    """icd11Code -> (icd10Code, icd10Title, icd10Chapter[romain]) via la table officielle OMS."""
    crosswalk = {}
    with open(CODE_CROSSWALK_PATH, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            code11 = row["icd11Code"].strip()
            if code11 and code11 not in crosswalk:
                crosswalk[code11] = (
                    row["icd10Code"].strip(),
                    row["icd10Title"].strip(),
                    row["icd10Chapter"].strip(),
                )
    return crosswalk


def load_chapter_bridge():
    """icd11_chapter -> dict(icd10_chapter_number [romain], reliability_pct, correspondence_type)."""
    bridge = {}
    with open(BRIDGE_PATH, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            bridge[row["icd11_chapter"]] = row
    return bridge


def load_icd10_chapter_titles():
    """chiffre romain -> titre anglais officiel (issu de notre crawl API OMS)."""
    titles = {}
    with open(ICD10_TABLE_PATH, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["classKind"] == "chapter":
                titles[row["code"]] = row["title"]
    return titles


def main():
    code_crosswalk = load_code_crosswalk()
    chapter_bridge = load_chapter_bridge()
    chapter_titles = load_icd10_chapter_titles()

    with open(REFERENCE_PATH, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    migration_log = []
    n_code_lookup = 0
    n_chapter_bridge = 0
    n_multi_chapter = 0
    n_unchanged = 0
    n_no_mapping = 0

    for row in rows:
        rule_id = row["rule_id"]
        old_code = row["icd_code"]
        old_title = row["icd_title"]
        old_chapter = row["icd_chapter"]
        old_chapter_name = row["icd_chapter_name"]
        old_release = row["icd_release"]

        # La release cible s'applique à toutes les lignes, y compris les
        # VALIDATED_NON_ICD / VALIDATED_EXCLUDED (c'est un tampon de version
        # du référentiel, pas une propriété du seul sous-ensemble mappé).
        row["icd_release"] = "ICD-10 (OMS, release 2019)"

        if row["mapping_status"] != "VALIDATED_ICD":
            # Rien d'autre à traduire : pas une règle éligible ICD.
            n_unchanged += 1
            continue

        method = None

        # Cas 1 : code ICD-11 précis -> lookup officiel code-à-code
        if old_code and old_code in code_crosswalk:
            icd10_code, icd10_title, icd10_chapter_roman = code_crosswalk[old_code]
            row["icd_code"] = icd10_code
            row["icd_title"] = icd10_title
            method = "code_lookup_officiel"
            n_code_lookup += 1
            # Chapitre ICD-10 pris DIRECTEMENT depuis la table officielle
            # code-à-code (colonne icd10Chapter), pas re-dérivé via le pont
            # chapitre : c'est la source la plus précise disponible pour
            # une ligne qui a déjà un code exact.
            if icd10_chapter_roman:
                row["icd_chapter"] = ROMAN_TO_POSITION.get(icd10_chapter_roman, "")
                row["icd_chapter_name"] = chapter_titles.get(icd10_chapter_roman, "")

        # Cas 2 : chapitre multiple (ex. "11|12") -> traduire chaque membre
        elif "|" in old_chapter:
            parts = old_chapter.split("|")
            new_positions = []
            new_names = []
            for p in parts:
                bridge_row = chapter_bridge.get(p)
                if bridge_row:
                    roman = bridge_row["icd10_chapter_number"]
                    new_positions.append(ROMAN_TO_POSITION.get(roman, ""))
                    new_names.append(chapter_titles.get(roman, ""))
            row["icd_chapter"] = "|".join(new_positions)
            row["icd_chapter_name"] = "|".join(new_names)
            method = "chapter_bridge_officiel_multi"
            n_multi_chapter += 1

        # Cas 3 : chapitre seul -> pont chapitre officiel
        elif old_chapter in chapter_bridge:
            bridge_row = chapter_bridge[old_chapter]
            roman = bridge_row["icd10_chapter_number"]
            row["icd_chapter"] = ROMAN_TO_POSITION.get(roman, "")
            row["icd_chapter_name"] = chapter_titles.get(roman, bridge_row["icd10_chapter_name_fr"])
            method = "chapter_bridge_officiel"
            n_chapter_bridge += 1

        else:
            method = "AUCUNE_CORRESPONDANCE_TROUVEE"
            n_no_mapping += 1

        row["icd_release"] = "ICD-10 (OMS, release 2019)"
        row["source_icd_url"] = (
            f"https://icd.who.int/browse10/2019/en#/{row['icd_code']}"
            if row["icd_code"] else "https://icd.who.int/browse10/2019/en"
        )
        row["mapping_rationale"] = (
            row["mapping_rationale"]
            + f" [Traduit depuis la révision OMS précédente via {method}, code/chapitre d'origine (révision précédente) : "
            f"{old_code or old_chapter}, source OMS officielle.]"
        )

        migration_log.append({
            "rule_id": rule_id,
            "outcome_normalized": row["outcome_normalized"],
            "method": method,
            "code_avant_migration": old_code,
            "chapitre_avant_migration": old_chapter,
            "chapitre_avant_migration_nom": old_chapter_name,
            "code_icd10": row["icd_code"],
            "chapitre_icd10": row["icd_chapter"],
            "chapitre_icd10_nom": row["icd_chapter_name"],
        })

    with open(REFERENCE_PATH, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    MIGRATION_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MIGRATION_REPORT_PATH, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(migration_log[0].keys()))
        writer.writeheader()
        writer.writerows(migration_log)

    with open(CHAPTER_NUMBERING_PATH, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["icd10_chapter_position", "icd10_chapter_roman", "icd10_chapter_title_en"])
        for roman, pos in ROMAN_TO_POSITION.items():
            writer.writerow([pos, roman, chapter_titles.get(roman, "")])

    print("=== MIGRATION ICD-11 -> ICD-10 TERMINÉE ===")
    print(f"Règles VALIDATED_ICD traduites via lookup code officiel : {n_code_lookup}")
    print(f"Règles VALIDATED_ICD traduites via pont chapitre officiel : {n_chapter_bridge}")
    print(f"Règles multi-chapitres traduites : {n_multi_chapter}")
    print(f"Règles non éligibles ICD (inchangées) : {n_unchanged}")
    print(f"Règles sans correspondance trouvée (À VÉRIFIER) : {n_no_mapping}")
    print(f"Rapport de migration : {MIGRATION_REPORT_PATH}")
    print(f"Table de numérotation des chapitres : {CHAPTER_NUMBERING_PATH}")


if __name__ == "__main__":
    main()
