# Fonctionnement du pipeline

## Objectif et unité d’analyse

Le pipeline transforme des exports CTD et des publications biomédicales en
associations quantitatives entre une exposition atmosphérique et un outcome de
santé. L’unité d’analyse finale est une estimation publiée : PMID, polluant,
outcome, mesure d’effet, population, scénario analytique et temporalité.

Plusieurs lignes peuvent donc provenir du même PMID. Elles restent distinctes
si la mesure, la population, la fenêtre d’exposition ou le scénario diffère.
Le pipeline ne combine pas ces estimations par pooling statistique.

## Vue d’ensemble

```text
Exports CTD
  │
  ├─ préparation PM humaine et sélection des PMIDs
  ├─ PubMed + Paperclip/Europe PMC
  ├─ assemblage et segmentation des documents
  ├─ agents polluant / outcome / mesure d’effet
  ├─ association builder et fusion multi-PMID
  ├─ contrôle qualité et tables d’inspection
  ├─ enrichissement CTD + population + temporalité
  ├─ dataset final d’extraction
  └─ mapping ICD-10 et rapports de validation
```

`src/runners/run_pipeline.py` orchestre l’extraction. Le script
`scripts/run_full.sh` lance cette extraction puis le mapping ICD-10. Toutes les
sorties sont placées sous `CTD_DATA_ROOT`, soit `data/processed/` par défaut.

## Ordre des étapes

| Clé | Rôle | Sortie principale |
| --- | --- | --- |
| `ctd_pm_human` | filtre les tables CTD PM sur le périmètre humain | `ctd_pm_human/` |
| `ctd_exposure_candidates` | rassemble les PMIDs candidats PM, O3, NO2 et NO | manifeste documentaire |
| `fetch_pubmed` | récupère titres, métadonnées et abstracts | `pubmed/` |
| `fetch_paperclip` | récupère les textes complets disponibles | `paperclip/` |
| `prepare_llm_inputs` | assemble le meilleur texte disponible par PMID | `llm_inputs/` |
| `segment` | découpe les documents en sections exploitables | `segmented_documents/` |
| `pollutant` | extrait et normalise les expositions | `agent_outputs/pollutant_extractor/` |
| `outcome` | extrait et normalise les outcomes | `agent_outputs/outcome_extractor/` |
| `effect_measure` | extrait les estimations quantitatives | `agent_outputs/effect_measure_extractor/` |
| `association_builder` | relie polluant, outcome et estimation par PMID | `agent_outputs/association_builder/` |
| `merge` | fusionne les associations des publications | `agent_outputs/multi_pmid_runner/` |
| `quality_control` | applique les règles accept/review/reject | `agent_outputs/final_quality_control/` |
| `inspect` | sépare analyse principale, contexte et revue | `agent_outputs/final_inspection/` |
| `final_tables` | produit les tables scientifiques et d’audit | `final_tables/` |
| `ctd_enrichment` | ajoute maladies, phénotypes et gènes CTD pour PM | `enrichment/` |
| `population_location` | extrait population et localisation | `agent_outputs/population_extractor/` |
| `exposure_temporal` | extrait fenêtre, durée, période et lag | `agent_outputs/time_extractor/` |
| `agent_csv_exports` | consolide les sorties des agents en CSV | `agent_csv_outputs/` |
| `final_dataset` | fusionne les composantes finales | `final/ctd_extraction_final.csv` |

Le mapping ICD-10 intervient ensuite et écrit dans `icd/`.

## Préparation CTD

Les fichiers `CTD_*_exposure*.csv` fournissent les références d’exposition
pour les quatre polluants. Les exports `genes`, `ixns`, `phenotype` et
`diseases` de `D052638` alimentent l’enrichissement mécanistique des
associations PM.

```bash
python -m src.runners.run_pipeline \
  --stages ctd_pm_human,ctd_exposure_candidates
```

Les filtres conservent les études humaines lorsque l’information d’espèce est
disponible et produisent les fichiers nécessaires aux étapes suivantes.

## Acquisition documentaire

PubMed fournit les métadonnées et abstracts. Paperclip et Europe PMC sont
utilisés pour récupérer les textes complets accessibles. L’absence de texte
complet n’implique pas automatiquement l’exclusion : l’abstract peut servir de
source lorsque son contenu est suffisant.

```bash
python -m src.runners.run_pipeline \
  --stages fetch_pubmed,fetch_paperclip,prepare_llm_inputs,segment
```

Les manifestes et audits de cette partie permettent de distinguer les textes
complets, les abstracts seuls, les PMIDs sans PMCID et les erreurs réseau.

## Extraction structurée

Trois agents spécialisés traitent les segments :

- l’agent polluant identifie l’exposition étudiée, son libellé normalisé et sa
  preuve textuelle ;
- l’agent outcome identifie l’effet sanitaire, son concept cœur, sa catégorie
  et sa preuve ;
- l’agent mesure extrait le type d’estimation, la valeur, l’intervalle de
  confiance, la p-value, l’incrément d’exposition, la méthode et le contexte.

Les réponses des segments sont fusionnées et dédupliquées par des fonctions
Python. Le builder ne crée une association que lorsque les entités peuvent
être reliées dans le contexte de la publication.

```bash
python -m src.runners.run_pipeline --stages agents --workers 4
```

Pour une validation limitée à des documents déjà segmentés :

```bash
python -m src.runners.run_pipeline \
  --stages agents \
  --pmids 19620729,20123607 \
  --workers 1
```

## Contrôle qualité

Le contrôle qualité est déterministe. Il utilise les valeurs structurées et
les preuves extraites pour attribuer :

- `accept` à une estimation exploitable ;
- `review` à une estimation qui nécessite une vérification humaine ;
- `reject` à une estimation hors périmètre ou insuffisamment définie.

Les lignes écartées restent disponibles avec leurs motifs. La création des
tables principales n’efface donc pas la piste d’audit.

```bash
python -m src.runners.run_pipeline --stages postprocessing
```

## Enrichissement CTD

L’enrichissement mécanistique est appliqué aux associations reconnues comme
PM/D052638. Il distingue :

- le contexte gène PM global ;
- les maladies et phénotypes compatibles avec l’outcome ;
- les liens gène–outcome appuyés par les réseaux CTD correspondants.

Les associations non-PM restent dans le dataset final, sans attribution d’un
mécanisme PM.

## Population et temporalité

Les agents population/localisation et temporalité complètent l’association
scientifique. Les informations temporelles décrivent ce que rapporte l’étude :
fenêtre, durée, période, moyenne d’exposition et lag. Elles ne déplacent pas
automatiquement une série temporelle et ne recalculent pas la mesure d’effet.

Le dataset final conserve ces champs au niveau de chaque association.

## Mapping ICD-10

Le moteur de mapping :

1. normalise la clé d’outcome ;
2. cherche une règle spécifique au PMID ;
3. utilise une règle générale si aucune règle spécifique ne s’applique ;
4. ajoute les champs ICD-10 et la justification ;
5. produit les rapports de couverture, de conflits et de cas non résolus.

Les règles proviennent de `config/icd_mapping_reference.csv`. Aucune
correspondance lexicale n’est inventée en l’absence de règle validée.

```bash
python -m src.icd.map_ctd_to_icd \
  --input data/processed/final/ctd_extraction_final.csv \
  --strict
```

Statuts possibles :

- `VALIDATED_ICD` : outcome associé à une entité ou un chapitre ICD-10 ;
- `VALIDATED_NON_ICD` : concept sanitaire qui ne correspond pas à une maladie
  codable ;
- `VALIDATED_EXCLUDED` : outcome explicitement exclu du mapping ;
- `UNMAPPED_REVIEW` : aucune règle validée ne couvre l’outcome ;
- `OUT_OF_SCOPE` : relation hors du périmètre principal du mapping.

## Commandes opérationnelles

Pipeline complet :

```bash
./scripts/run_full.sh
```

Racine de données personnalisée :

```bash
CTD_DATA_ROOT=/chemin/absolu/ctd_processed ./scripts/run_full.sh
```

Liste des étapes :

```bash
python -m src.runners.run_pipeline --list-stages
```

Prévisualisation :

```bash
python -m src.runners.run_pipeline --dry-run
```

Par défaut, l’orchestrateur s’arrête au premier code de sortie non nul. L’option
`--continue-on-error` existe pour le diagnostic, mais elle ne garantit pas que
les étapes dépendantes disposeront de leurs entrées.

## Réexécution et traçabilité

Les étapes écrivent dans des chemins stables sous `CTD_DATA_ROOT`. Une
réexécution peut donc remplacer les artefacts portant le même nom. Conserver
une copie séparée lorsqu’une exécution doit servir de référence immuable.

Les éléments suivants permettent de retracer une ligne finale :

- `association_id` et `pmid` ;
- les phrases de preuve ;
- les fichiers JSON par agent ;
- les champs de provenance du modèle ;
- les décisions et motifs du contrôle qualité ;
- les audits JSON produits lors des fusions et enrichissements ;
- `mapping_rule_id` et `mapping_rationale` pour l’ICD-10.
