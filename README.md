# Pipeline d’extraction CTD et de mapping ICD-10

Ce dépôt produit un dataset structuré et auditable d’associations entre
polluants atmosphériques et effets sanitaires. Il combine les exports de la
Comparative Toxicogenomics Database (CTD), les publications biomédicales et un
référentiel ICD-10 curé.

Le pipeline réalise :

1. la sélection des publications pertinentes à partir des exports CTD ;
2. la récupération des métadonnées PubMed et des textes disponibles ;
3. la préparation et la segmentation des documents ;
4. l’extraction des polluants, outcomes, mesures d’effet, populations et temporalités ;
5. la construction et le contrôle qualité des associations ;
6. l’enrichissement CTD et la production du dataset final ;
7. le mapping des outcomes vers l’ICD-10 OMS, release 2019.

## Structure

```text
config/                 référentiel ICD-10 audité
data/raw/               exports CTD d’entrée
data/processed/         résultats du pipeline
  final/                dataset d’extraction final
  icd/                  dataset final enrichi ICD-10 et rapports de mapping
docs/                   méthode, dictionnaire et résultats statistiques
scripts/                commandes complètes et tests
src/agents/             extracteurs LLM
src/builders/           construction et fusion des associations
src/ingestion/          PubMed, Europe PMC et Paperclip
src/preprocessing/      préparation CTD et segmentation
src/quality_control/    décisions accept / review / reject
src/icd/                validation et application du mapping ICD-10
src/runners/            points d’entrée de chaque étape
tests/                  tests automatisés
```

## Installation

Python 3.11 ou plus récent est requis.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Renseigner dans `.env` les paramètres nécessaires :

- `ILAAS_API_KEY`, `ILAAS_BASE_URL` et `ILAAS_MODEL` pour le service LLM ;
- `NCBI_EMAIL` et éventuellement `NCBI_API_KEY` pour PubMed ;
- `PAPERCLIP_BINARY` si l’exécutable Paperclip n’est pas accessible sous ce nom ;
- `CTD_DATA_ROOT` pour changer la racine de sortie, `data/processed` par défaut.

## Données d’entrée

Placer les exports CTD dans `data/raw/` :

```text
CTD_D052638_exposure_*.csv
CTD_D052638_genes_*.csv
CTD_D052638_ixns_*.csv
CTD_D052638_phenotype_*.csv
CTD_D052638_diseases_*.csv
CTD_D010126_exposure_*.csv
CTD_D009585_exposure_*.csv
CTD_D009569_exposure_*.csv
```

Les quatre identifiants CTD correspondent respectivement aux particules,
à l’ozone, au dioxyde d’azote et au monoxyde d’azote utilisés pour sélectionner
les publications candidates.

## Lancement complet

Depuis la racine du dépôt :

```bash
source .venv/bin/activate
./scripts/run_full.sh
```

Cette commande exécute l’extraction, construit :

```text
data/processed/final/ctd_extraction_final.csv
```

puis applique le mapping ICD-10 dans :

```text
data/processed/icd/ctd_icd_mapped_complete.csv
data/processed/icd/mapping_quality_report.csv
data/processed/icd/mapping_unresolved.csv
data/processed/icd/mapping_conflicts.csv
```

Le nombre de workers LLM peut être configuré ainsi :

```bash
WORKERS=4 ./scripts/run_full.sh
```

## Exécution du pipeline d’extraction

Afficher les étapes disponibles :

```bash
python -m src.runners.run_pipeline --list-stages
```

Exécuter toute l’extraction sans le mapping ICD-10 :

```bash
python -m src.runners.run_pipeline --workers 4
```

Exécuter un groupe d’étapes :

```bash
python -m src.runners.run_pipeline --stages ingestion
python -m src.runners.run_pipeline --stages agents --workers 4
python -m src.runners.run_pipeline --stages postprocessing
```

Limiter les extracteurs à une publication :

```bash
python -m src.runners.run_pipeline --stages agents --pmid 19620729 --workers 1
```

## Mapping ICD-10 uniquement

À partir du dataset final produit par l’extraction :

```bash
python -m src.icd.map_ctd_to_icd \
  --input data/processed/final/ctd_extraction_final.csv \
  --strict
```

Le répertoire de sortie par défaut est `data/processed/icd/`. Pour choisir un
autre emplacement :

```bash
python -m src.icd.map_ctd_to_icd \
  --input /chemin/vers/ctd_extraction.csv \
  --output-dir /chemin/vers/resultats_icd \
  --strict
```

Le mode `--strict` renvoie un code d’erreur si une ligne PM2.5 ou PM10 reste
avec le statut `UNMAPPED_REVIEW`.

## Tests

```bash
source .venv/bin/activate
./scripts/run_tests.sh
```

## Documentation

- `docs/PIPELINE.md` décrit les transformations et commandes par étape ;
- `docs/DATA_DICTIONARY.md` décrit les répertoires, fichiers et colonnes ;
- `docs/DECISIONS_LOG.md` expose les règles scientifiques et techniques ;
- `docs/STATISTICAL_DOCUMENTATION.md` présente les résultats du run documenté.

Les données brutes, les réponses LLM et les résultats sous `data/` ne sont pas
versionnés. Le code, le référentiel ICD-10, la documentation et les tests sont
versionnés.
