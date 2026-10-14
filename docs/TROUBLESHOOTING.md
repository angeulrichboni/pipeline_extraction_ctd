# Dépannage

Les commandes de cette page supposent que le terminal se trouve à la racine du
dépôt et que l’environnement virtuel est activé.

## Vérifications de base

```bash
pwd
python --version
python -c "import pandas, dotenv, requests; print('dépendances Python : OK')"
python -m src.runners.run_pipeline --list-stages
python -m src.runners.run_pipeline --dry-run
```

La version Python doit être au moins 3.11. Si un import échoue :

```bash
pip install -r requirements.txt
```

## Fichier CTD introuvable

Symptôme : `FileNotFoundError` ou message indiquant qu’aucun fichier ne
correspond à `CTD_...`.

Vérifier les fichiers :

```bash
find data/raw -maxdepth 1 -type f -name 'CTD_*.csv' -printf '%f\n' | sort
```

Le dossier doit contenir les quatre exports `exposure` et les exports
`genes`, `ixns`, `phenotype` et `diseases` pour `D052638`. Conserver les
en-têtes CTD et l’extension `.csv`.

## Clé LLM absente

Symptôme : `Missing ILAAS API key`.

Créer la configuration locale si nécessaire :

```bash
cp .env.example .env
```

Renseigner `ILAAS_API_KEY`, `ILAAS_BASE_URL` et `ILAAS_MODEL`, puis vérifier
sans afficher la clé :

```bash
python -c "from src.config.settings import settings; print(bool(settings.ilaas_api_key), settings.ilaas_base_url, settings.ilaas_model)"
```

Le premier élément affiché doit être `True`.

## Erreur réseau ou limitation de débit

Les codes HTTP 429 et les erreurs temporaires 5xx peuvent provenir du service
LLM ou des services documentaires. Réduire d’abord le parallélisme :

```bash
WORKERS=1 ./scripts/run_full.sh
```

Consulter ensuite les fichiers sous `data/processed/logs/`. Ne jamais copier
une clé API dans un ticket ou un message de diagnostic.

## Paperclip indisponible

Vérifier l’exécutable configuré :

```bash
command -v paperclip
```

Si le binaire porte un autre nom ou se trouve ailleurs, renseigner son chemin
dans `.env` :

```text
PAPERCLIP_BINARY=/chemin/vers/paperclip
```

Les audits sous `data/processed/paperclip/` distinguent les textes complets,
les abstracts seuls, les PMIDs sans PMCID et les erreurs de récupération.

## Une étape partielle ne trouve pas ses entrées

Les groupes ne reconstruisent pas toutes leurs dépendances. Respecter l’ordre :

```bash
python -m src.runners.run_pipeline --stages ingestion
python -m src.runners.run_pipeline --stages agents --workers 1
python -m src.runners.run_pipeline --stages postprocessing
```

Un test avec `--pmid` suppose que le fichier
`data/processed/segmented_documents/<PMID>_segmented.json` existe déjà.

## Résultats écrits dans un répertoire inattendu

Afficher la racine active :

```bash
python -c "from src.config.paths import paths; print(paths.processed_dir)"
```

Si `CTD_DATA_ROOT` est défini dans le terminal ou dans `.env`, les résultats
sont écrits à cet emplacement. Utiliser de préférence un chemin absolu pour
une racine externe.

## Dataset final absent

Vérifier les entrées de la fusion finale :

```bash
test -f data/processed/enrichment/main_associations_enriched.csv && echo enrichment_OK
test -f data/processed/agent_csv_outputs/05_population_location_extractor_output.csv && echo population_OK
test -f data/processed/agent_csv_outputs/06_exposure_temporal_extractor_output.csv && echo temporal_OK
```

Relancer ensuite les étapes de post-traitement :

```bash
python -m src.runners.run_pipeline --stages postprocessing
```

## Outcomes ICD-10 non résolus

Consulter :

```text
data/processed/icd/mapping_unresolved.csv
data/processed/icd/mapping_quality_report.csv
```

Une résolution scientifique nécessite l’ajout ou la correction d’une règle
dans `config/icd_mapping_reference.csv`, avec justification, statut de
validation et sources. Ne pas contourner un `UNMAPPED_REVIEW` par une
correspondance textuelle improvisée.

## Conflit dans le référentiel ICD-10

`mapping_conflicts.csv` décrit les clés dupliquées ou incompatibles. Le mapping
s’arrête pour éviter de choisir arbitrairement une règle. Corriger le
référentiel, puis relancer le mapping seul :

```bash
python -m src.icd.map_ctd_to_icd \
  --input data/processed/final/ctd_extraction_final.csv \
  --strict
```

## Lancer les tests

```bash
./scripts/run_tests.sh
```

Si les tests passent mais qu’un service externe échoue, le problème se situe
probablement dans la configuration, le réseau, le quota ou la disponibilité du
service concerné. Les tests unitaires n’effectuent pas une exécution réseau
complète.

## Informations utiles pour un diagnostic

Fournir uniquement :

- la commande exécutée ;
- le nom de l’étape en échec ;
- le code de sortie ;
- les dernières lignes du journal correspondant ;
- la version de Python ;
- les noms de variables configurées, sans leurs valeurs secrètes.

Ne pas transmettre `.env` ni les en-têtes HTTP d’authentification.
