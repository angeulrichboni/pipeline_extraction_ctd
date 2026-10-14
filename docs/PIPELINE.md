# Pipeline d’extraction CTD et de mapping ICD-10

## Objectif

Le pipeline transforme des exports CTD et des publications biomédicales en un
dataset d’associations quantitatives polluant–outcome, contrôlé et enrichi par
un mapping ICD-10 auditable.

## Chaîne de traitement

```text
Exports CTD dans data/raw/
  → sélection des études humaines et des PMIDs candidats
  → récupération PubMed et Paperclip/Europe PMC
  → construction des entrées LLM
  → segmentation des documents
  → extraction polluant / outcome / mesure d’effet
  → construction des associations par PMID
  → fusion multi-PMID
  → contrôle qualité accept / review / reject
  → tables scientifiques et tables d’audit
  → extraction population/localisation et temporalité
  → enrichissement CTD
  → dataset final
  → mapping ICD-10
```

L’orchestrateur est `src/runners/run_pipeline.py`. Les sorties sont écrites
sous `CTD_DATA_ROOT`, soit `data/processed/` par défaut.

## 1. Préparation CTD

Les runners `build_ctd_pm_human_dataset` et
`build_ctd_exposure_candidates` filtrent les exports CTD, conservent les
études humaines et construisent la liste des PMIDs à traiter.

```bash
python -m src.runners.run_pipeline --stages ctd_pm_human,ctd_exposure_candidates
```

## 2. Acquisition documentaire

PubMed fournit les métadonnées et abstracts. Paperclip fournit les textes
complets lorsqu’ils sont disponibles ; Europe PMC complète la récupération.

```bash
python -m src.runners.run_pipeline --stages fetch_pubmed,fetch_paperclip
```

Les documents sont ensuite assemblés et segmentés :

```bash
python -m src.runners.run_pipeline --stages prepare_llm_inputs,segment
```

## 3. Extraction structurée

Les extracteurs traitent chaque segment puis fusionnent leurs réponses en
Python. La normalisation et la déduplication reposent sur des clés
déterministes.

- polluants : concept normalisé, rôle et preuve textuelle ;
- outcomes : libellé cœur, catégorie, rôle et preuve ;
- mesures d’effet : type, valeur, intervalle de confiance, p-value, incrément,
  méthode et contexte statistique ;
- population/localisation : caractéristiques de la population étudiée ;
- temporalité : durée, fenêtre, période et lag d’exposition.

```bash
python -m src.runners.run_pipeline --stages agents --workers 4
```

## 4. Construction et contrôle qualité

Le builder relie polluant, outcome et mesure d’effet au sein d’une même
publication. Le contrôle qualité attribue ensuite :

- `accept` lorsque la relation est exploitable ;
- `review` lorsqu’une ambiguïté nécessite une vérification ;
- `reject` lorsqu’un composant requis est invalide.

Les décisions sont produites par le code Python, indépendamment du LLM.

```bash
python -m src.runners.run_pipeline --stages postprocessing
```

Le dataset consolidé est écrit dans :

```text
data/processed/final/ctd_extraction_final.csv
```

## 5. Mapping ICD-10

Le moteur `src/icd` normalise l’outcome, recherche d’abord une règle propre au
PMID puis une règle générale. Les règles sont lues dans
`config/icd_mapping_reference.csv`. Aucune correspondance par mots-clés n’est
inventée en l’absence de règle.

```bash
python -m src.icd.map_ctd_to_icd \
  --input data/processed/final/ctd_extraction_final.csv \
  --strict
```

Les sorties sont écrites dans `data/processed/icd/` :

```text
ctd_icd_mapped_complete.csv
mapping_quality_report.csv
mapping_unresolved.csv
mapping_conflicts.csv
```

Statuts possibles :

- `VALIDATED_ICD` : outcome associé à une entité ou un chapitre ICD-10 ;
- `VALIDATED_NON_ICD` : mesure ou concept sanitaire sans code ICD pertinent ;
- `VALIDATED_EXCLUDED` : outcome explicitement exclu du mapping ;
- `UNMAPPED_REVIEW` : aucune règle validée ;
- `OUT_OF_SCOPE` : polluant hors périmètre du mapping principal.

## 6. Commandes opérationnelles

Pipeline complet avec mapping ICD-10 :

```bash
./scripts/run_full.sh
```

Racine de données personnalisée :

```bash
CTD_DATA_ROOT=/chemin/vers/data_processed ./scripts/run_full.sh
```

Prévisualisation des commandes sans exécution :

```bash
python -m src.runners.run_pipeline --dry-run
```

Tests :

```bash
./scripts/run_tests.sh
```
