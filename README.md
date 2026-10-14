# Pipeline d’extraction CTD et de mapping ICD-10

Ce dépôt construit un jeu de données auditable de relations entre polluants
atmosphériques et effets sanitaires. Il combine les exports de la
Comparative Toxicogenomics Database (CTD), les publications indexées dans
PubMed, les textes complets disponibles et un référentiel de mapping ICD-10
OMS (release 2019).

Le résultat principal contient, pour chaque association scientifique :

- le PMID et les preuves textuelles ;
- le polluant et l’outcome normalisés ;
- la mesure d’effet, sa valeur, son intervalle de confiance et son incrément ;
- la population, la localisation et la temporalité d’exposition ;
- les décisions du contrôle qualité ;
- l’enrichissement mécanistique CTD pour les particules ;
- le statut et, lorsqu’il est pertinent, le code ICD-10 de l’outcome.

Le pipeline ne réalise pas de méta-analyse et ne calcule pas un risque relatif
global. Une ligne représente une estimation extraite dans son contexte
scientifique, pas une valeur agrégée par polluant.

## Démarrage rapide

Les commandes suivantes sont à exécuter depuis la racine du dépôt.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
```

Renseigner au minimum `ILAAS_API_KEY` dans `.env`, puis placer les exports CTD
attendus dans `data/raw/`. Lancer ensuite :

```bash
./scripts/run_full.sh
```

À la fin d’une exécution réussie, les deux fichiers principaux sont :

```text
data/processed/final/ctd_extraction_final.csv
data/processed/icd/ctd_icd_mapped_complete.csv
```

## Prérequis

- Python 3.11 ou plus récent ;
- Bash pour les scripts fournis dans `scripts/` ;
- un accès réseau à PubMed, Europe PMC/Paperclip et au service LLM configuré ;
- une clé valide pour le service LLM compatible avec l’API OpenAI ;
- les exports CTD listés dans la section suivante ;
- l’exécutable Paperclip accessible via `PAPERCLIP_BINARY` pour la récupération
  des textes complets.

Les étapes LLM envoient les segments des publications au service défini par
`ILAAS_BASE_URL`. Vérifier que cet usage respecte les règles de confidentialité
et de coût de l’environnement d’exécution.

## Données d’entrée

Créer `data/raw/` si nécessaire et y déposer un fichier correspondant à chacun
des motifs suivants :

| Identifiant CTD | Polluant | Fichiers attendus |
| --- | --- | --- |
| `D052638` | Particulate Matter | `CTD_D052638_exposure*.csv`, `CTD_D052638_genes*.csv`, `CTD_D052638_ixns*.csv`, `CTD_D052638_phenotype*.csv`, `CTD_D052638_diseases*.csv` |
| `D010126` | Ozone | `CTD_D010126_exposure*.csv` |
| `D009585` | Nitrogen dioxide | `CTD_D009585_exposure*.csv` |
| `D009569` | Nitric oxide | `CTD_D009569_exposure*.csv` |

Les suffixes horodatés des exports sont acceptés par les étapes de préparation.
Ne pas modifier les en-têtes fournis par CTD.

Contrôle rapide :

```bash
find data/raw -maxdepth 1 -type f -name 'CTD_*.csv' -printf '%f\n' | sort
```

## Configuration

Copier `.env.example` vers `.env`. Le fichier `.env` est local et ne doit pas
être commité.

| Variable | Obligatoire | Rôle |
| --- | --- | --- |
| `ILAAS_API_KEY` | oui pour les agents | clé du service LLM |
| `ILAAS_BASE_URL` | oui pour les agents | URL de base compatible OpenAI |
| `ILAAS_MODEL` | oui pour les agents | modèle utilisé par les extracteurs |
| `ILAAS_MAX_TOKENS` | non | limite de génération |
| `ILAAS_TEMPERATURE` | non | température des appels, `0` par défaut |
| `NCBI_EMAIL` | recommandé | identification auprès de l’API NCBI |
| `NCBI_API_KEY` | non | quota NCBI associé au compte |
| `PAPERCLIP_BINARY` | oui pour Paperclip | nom ou chemin de l’exécutable |
| `PAPERCLIP_FULL_TEXT_PATH_TEMPLATE` | non | chemin du contenu dans Paperclip |
| `PAPERCLIP_BASE_URL` | non | active le mode HTTP à la place du binaire local |
| `PAPERCLIP_API_KEY` | non | authentification du mode HTTP, si requise |
| `MAX_RETRIES` | non | nombre de tentatives réseau |
| `RETRY_SLEEP_SECONDS` | non | attente entre les tentatives |
| `CTD_DATA_ROOT` | non | racine des résultats, `data/processed` par défaut |

Pour stocker les résultats ailleurs :

```bash
CTD_DATA_ROOT=/chemin/absolu/ctd_processed ./scripts/run_full.sh
```

## Ce que fait le lancement complet

`scripts/run_full.sh` exécute les opérations suivantes dans l’ordre :

1. préparation des exports CTD et sélection des études humaines ;
2. constitution de la liste des PMIDs candidats ;
3. récupération des métadonnées PubMed et des textes disponibles ;
4. assemblage et segmentation des documents ;
5. extraction des polluants, outcomes et mesures d’effet ;
6. construction des associations et fusion multi-PMID ;
7. contrôle qualité et création des tables scientifiques ;
8. enrichissement CTD, population/localisation et temporalité ;
9. création du dataset final ;
10. mapping des outcomes vers l’ICD-10.

Le nombre de publications traitées simultanément par les agents se règle avec
`WORKERS` :

```bash
WORKERS=2 ./scripts/run_full.sh
```

Commencer avec `WORKERS=1` si le service LLM impose une limite stricte de débit.

## Exécutions partielles

Afficher toutes les étapes reconnues :

```bash
python -m src.runners.run_pipeline --list-stages
```

Prévisualiser les commandes sans les exécuter :

```bash
python -m src.runners.run_pipeline --dry-run
```

Exécuter un groupe :

```bash
python -m src.runners.run_pipeline --stages ingestion
python -m src.runners.run_pipeline --stages agents --workers 4
python -m src.runners.run_pipeline --stages postprocessing
```

Exécuter des étapes précises :

```bash
python -m src.runners.run_pipeline \
  --stages fetch_pubmed,fetch_paperclip,prepare_llm_inputs,segment
```

Limiter les extracteurs à une publication déjà préparée et segmentée :

```bash
python -m src.runners.run_pipeline \
  --stages agents \
  --pmid 19620729 \
  --workers 1
```

Les filtres `--pmid`, `--pmids` et `--limit` s’appliquent uniquement aux étapes
qui les acceptent. Ils ne reconstruisent pas automatiquement les entrées
PubMed ou les segments manquants.

## Mapping ICD-10 uniquement

Lorsque le dataset d’extraction existe déjà :

```bash
python -m src.icd.map_ctd_to_icd \
  --input data/processed/final/ctd_extraction_final.csv \
  --strict
```

Les résultats sont écrits dans `data/processed/icd/` :

```text
ctd_icd_mapped_complete.csv
mapping_quality_report.csv
mapping_unresolved.csv
mapping_conflicts.csv
```

`--strict` renvoie un code d’erreur lorsqu’une ligne PM2.5 ou PM10 conserve le
statut `UNMAPPED_REVIEW`. Le référentiel utilisé est
`config/icd_mapping_reference.csv`.

## Résultats à consulter

| Chemin | Utilisation |
| --- | --- |
| `data/processed/final/ctd_extraction_final.csv` | dataset d’extraction consolidé |
| `data/processed/icd/ctd_icd_mapped_complete.csv` | dataset consolidé avec champs ICD-10 |
| `data/processed/icd/mapping_quality_report.csv` | couverture et statuts du mapping |
| `data/processed/final_tables/` | tables principales, contextuelles, à revoir et rejetées |
| `data/processed/enrichment/` | enrichissement CTD et audits mécanistiques |
| `data/processed/agent_outputs/` | sorties JSON et CSV intermédiaires par PMID |
| `data/processed/logs/` | journaux d’exécution |

Une exécution est considérée comme terminée lorsque :

- `ctd_extraction_final.csv` existe ;
- le nombre de lignes du dataset mappé correspond au nombre de lignes du
  dataset d’extraction ;
- `mapping_conflicts.csv` ne contient aucun conflit ;
- en mode strict, aucun outcome PM ne reste avec `UNMAPPED_REVIEW`.

## Tests

```bash
source .venv/bin/activate
./scripts/run_tests.sh
```

Les tests couvrent les fonctions centrales d’extraction et le mapping ICD-10.
Ils ne déclenchent pas une exécution complète des services externes.

## Organisation du dépôt

```text
config/                 référentiel ICD-10 audité
data/raw/               exports CTD d’entrée
data/processed/         résultats et artefacts d’exécution
docs/                   documentation technique et scientifique
scripts/                lancement complet et tests
src/agents/             extracteurs LLM
src/builders/           construction et fusion des associations
src/config/             configuration et chemins
src/icd/                validation et application du mapping ICD-10
src/ingestion/          PubMed, Europe PMC et Paperclip
src/preprocessing/      préparation CTD et segmentation
src/quality_control/    règles accept / review / reject
src/runners/            points d’entrée exécutables
tests/                  tests automatisés
```

## Documentation détaillée

- [`docs/PIPELINE.md`](docs/PIPELINE.md) : étapes, dépendances et commandes ;
- [`docs/DATA_DICTIONARY.md`](docs/DATA_DICTIONARY.md) : fichiers, clés et colonnes ;
- [`docs/DECISIONS_LOG.md`](docs/DECISIONS_LOG.md) : règles scientifiques et choix techniques ;
- [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) : diagnostic des erreurs courantes ;
- [`docs/STATISTICAL_DOCUMENTATION.md`](docs/STATISTICAL_DOCUMENTATION.md) : statistiques de l’exécution de référence.

Les données sous `data/`, les réponses LLM et les résultats calculés sont
exclus de Git. Le dépôt versionne le code, les tests, la documentation et le
référentiel ICD-10.
