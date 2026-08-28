# Pipeline exposition-santé — vue d'ensemble

Ce document décrit l'enchaînement des 7 étapes du pipeline, leurs entrées et
sorties, et la logique de chaque chapitre. Pour le détail colonne par colonne
de chaque fichier, voir `docs/DATA_DICTIONARY.md`. Pour l'historique des
décisions et ce qui a été retiré du code original, voir `docs/DECISIONS_LOG.md`.

## Les quatre chapitres, sept étapes techniques

```
Chapitre 1 — Référentiel ICD-10        → étape 2
Chapitre 2 — Personas et p0            → étape 3
Chapitre 3 — Exposition et trajectoire → étapes 1, 4, 5, 6
Chapitre 4 — Dataset exposition-santé  → étape 7
```

L'étape 1 (simulation) est indépendante des étapes 2 et 3 et peut tourner en
parallèle. Les étapes 4 à 7 sont strictement séquentielles.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Test rapide (2 jours, vérifie que tout s'installe correctement)

```bash
./scripts/run_tests.sh
```

## Génération complète

```bash
export CTD_PATH=/chemin/vers/ctd_extraction.csv   # fichier CTD brut, non mappé
./scripts/run_full.sh
```

Ou étape par étape :

```bash
# Étape 1 — Chapitre 3, simulation (30 individus, 12 logements, 5 ans)
PYTHONPATH=src python scripts/01_generate_trajectories.py --output-dir outputs

# Étape 2 — Chapitre 1, mapping CTD -> ICD-10
PYTHONPATH=src python scripts/02_map_ctd_to_icd.py \
  --input /chemin/vers/ctd_extraction.csv --output-dir outputs

# Étape 3 — Chapitre 2, calendrier p0 individuel
PYTHONPATH=src python scripts/03_generate_p0_schedule.py --output-dir outputs

# Étape 4 — Chapitre 3, fenêtres 24h et annuelles
PYTHONPATH=src python scripts/04_generate_exposure_windows.py --output-dir outputs

# Étape 5 — Chapitre 3, dépassements Moyenne / Maximum / MIL
PYTHONPATH=src python scripts/05_generate_exposure_thresholds.py --output-dir outputs

# Étape 6 — Chapitre 3, trajectoire longitudinale (NOUVEAU)
PYTHONPATH=src python scripts/06_generate_exposure_trajectory.py --output-dir outputs

# Étape 7 — Chapitre 4, dataset final
PYTHONPATH=src python scripts/07_generate_exposure_health_dataset.py --output-dir outputs
```

Chaque script accepte `--plain-csv` pour désactiver la compression gzip, utile
pour une inspection rapide dans un tableur ou un éditeur de texte.

## Contrôle qualité

```bash
PYTHONPATH=src python scripts/validate_outputs.py outputs
```

---

## Chapitre 1 — Référentiel ICD-10 (étape 2)

**Objectif.** Normaliser les 544 outcomes PM2.5/PM10 distincts du fichier CTD
en chapitres ICD-10 (OMS, release 2019), traçables et auditables.

**Méthode.** `stage_bph.icd_mapping` applique une règle spécifique au PMID en
priorité, sinon une règle générale pour l'outcome — jamais d'heuristique par
mots-clés. Toute décision provient de `config/icd_mapping_reference.csv`
(545 règles). Chaque outcome reçoit un statut : `VALIDATED_ICD`,
`VALIDATED_NON_ICD`, `VALIDATED_EXCLUDED`, ou `UNMAPPED_REVIEW` (attendu : 0
ligne PM dans ce dernier statut).

**Résultat de référence.** 98 688 lignes CTD → 92 309 lignes PM → 41 865
`VALIDATED_ICD`, 36 669 `VALIDATED_NON_ICD`, 13 775 `VALIDATED_EXCLUDED`,
0 non résolu, 0 conflit de règle.

## Chapitre 2 — Personas et p0 (étape 3)

**Objectif.** Représenter l'hétérogénéité démographique (5 personas, 30
individus, 12 logements) et calculer un risque de base p0 dynamique, propre
à chaque profil et recalculé à chaque changement d'année ou d'âge.

**Ce qui en sort vers le chapitre 4.** Pas `individual_id` — un triplet
catégoriel généralisé (`classe_age`, `grossesse`, `pathologie_preexistante`),
dérivé du persona et de la fenêtre temporelle par
`exposure_health_dataset.derive_profile()`.

## Chapitre 3 — Exposition et trajectoire (étapes 1, 4, 5, 6)

**Étage 1 (étapes 1, 4, 5).** Simulation résidentielle (`E_i(t) = C_h(t) ×
P_i(t)`), fenêtrage 24h et annuel aligné sur l'OMS 2021, trois méthodes de
détection (Moyenne, Maximum, MIL — seule MIL alimente la suite).

**Étage 2 (étape 6, nouveau).** Couche de trajectoire longitudinale
(`exposure_trajectory.py`) : pour chaque flux (individu × polluant × échelle),
reconstitue l'historique jusqu'à la fenêtre courante — cumul, répétition,
tendance. Indépendante de toute catégorie ICD, calculée une seule fois par
flux physique. C'est l'apport qui permet au futur modèle de distinguer une
exposition répétée d'une exposition ponctuelle au même niveau moyen.

## Chapitre 4 — Dataset exposition-santé (étape 7)

**Objectif.** Assembler profil, trajectoire, et force d'association CTD en
liens candidats (fenêtre × catégorie ICD), prêts pour la prédiction de liens.

**Règles de méthode non négociables** (voir docstring de
`exposure_health_dataset.py` et `docs/DECISIONS_LOG.md`) :
1. `health_score`, `link_label`, `association_strength`, `evidence_weight`
   ne sont jamais des features d'entrée — fuite de cible démontrée.
2. Les négatifs sont `unknown_sampled_negative`, pas des négatifs prouvés —
   hypothèse de monde ouvert.
3. `individual_id`/`persona_id` ne sont jamais des features — parité
   train/inférence.

---

## Positionnement scientifique

Le pipeline ne produit pas de diagnostic médical individuel. Il construit une
base de prédiction de liens guidée par les connaissances biomédicales,
permettant d'estimer les catégories ICD-10 les plus plausiblement associées à
un profil, une intensité d'exposition et une fenêtre temporelle.
