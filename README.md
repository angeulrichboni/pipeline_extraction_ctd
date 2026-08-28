# Pipeline exposition-santé

Génération reproductible de trajectoires d'exposition résidentielle PM2.5/PM10
et construction d'un dataset exposition-santé prêt pour la prédiction de
liens vers des catégories ICD-10 — 30 individus, 12 logements, 5 personas,
2021-2025, au pas de 15 minutes.

Quatre chapitres, un seul package :

1. **Référentiel ICD-10** (`stage_bph.icd_mapping`) — normalisation des
   effets sanitaires CTD en chapitres ICD-10 auditables.
2. **Personas et p0** (`stage_bph.p0`, `stage_bph.p0_schedule`) —
   hétérogénéité démographique et risque de base dynamique.
3. **Exposition et trajectoire** (`stage_bph.generator`,
   `stage_bph.exposure_windows`, `stage_bph.exposure_trajectory`) —
   simulation, fenêtrage 24h/annuel, détection MIL, trajectoire
   longitudinale.
4. **Dataset exposition-santé** (`stage_bph.exposure_health_dataset`) —
   liens candidats (fenêtre × catégorie ICD) prêts pour la modélisation.

Documentation complète : `docs/PIPELINE.md` (vue d'ensemble et commandes),
`docs/DATA_DICTIONARY.md` (chaque fichier, chaque colonne),
`docs/DECISIONS_LOG.md` (historique des corrections de cette version).

## Structure

```text
config/      paramètres et données de référence (personas, p0, ICD-10)
src/         code Python du pipeline (package unique stage_bph)
scripts/     7 étapes numérotées + validation + lanceurs
tests/       tests automatisés (pytest)
docs/        documentation complète
outputs/     fichiers générés (non versionné)
```

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Test rapide

```bash
./scripts/run_tests.sh
```

## Génération complète

```bash
export CTD_PATH=/chemin/vers/ctd_extraction.csv
./scripts/run_full.sh
```

Voir `docs/PIPELINE.md` pour le détail de chaque étape et leur lancement
individuel.
