# Dictionnaire des données et sorties

Tous les chemins de résultats sont relatifs à `CTD_DATA_ROOT`, dont la valeur
par défaut est `data/processed`.

## Entrées CTD

Les fichiers `data/raw/CTD_*.csv` contiennent les exports CTD utilisés pour
sélectionner les publications et enrichir les associations.

## Documents et entrées LLM

| Chemin | Contenu |
| --- | --- |
| `pubmed/` | métadonnées et abstracts PubMed par PMID |
| `paperclip/` | textes complets, manifestes et audits de récupération |
| `llm_inputs/` | documents assemblés avant segmentation |
| `segmented_documents/` | segments transmis aux extracteurs |

## Sorties des extracteurs

Sous `agent_outputs/`, chaque sous-répertoire contient les objets JSON produits
pour un PMID :

| Chemin | Contenu principal |
| --- | --- |
| `pollutant_extractor/` | polluant normalisé, rôle, confiance, preuve |
| `outcome_extractor/` | outcome cœur, catégorie, rôle, confiance, preuve |
| `effect_measure_extractor/` | mesure, valeur, IC, p-value, incrément, méthode |
| `association_builder/` | associations polluant–outcome–effet par PMID |
| `population_extractor/` | population, âge, sexe et localisation |
| `time_extractor/` | fenêtre, période, durée et lag d’exposition |
| `multi_pmid_runner/` | fusion des associations de toutes les publications |

## Contrôle qualité

`agent_outputs/final_quality_control/` contient les associations classées et
les motifs de décision.

| Colonne | Description |
| --- | --- |
| `qc_decision` | décision `accept`, `review` ou `reject` |
| `qc_measure_status` | qualité et interprétabilité de la mesure |
| `qc_exposure_status` | statut de l’exposition étudiée |
| `qc_outcome_status` | statut sanitaire de l’outcome |
| `qc_result_context` | résultat principal, sous-groupe ou sensibilité |
| `qc_include_in_clean_main_analysis` | inclusion dans l’analyse principale |
| `qc_reasons` | règles déterministes ayant produit la décision |

`agent_outputs/final_inspection/` sépare les tables principales, contextuelles
et à revoir.

## Tables finales

| Chemin | Description |
| --- | --- |
| `final_tables/01_main_associations_analysis.csv` | associations principales acceptées |
| `final_tables/02_main_associations_scientific.csv` | version scientifique détaillée |
| `final_tables/03_contextual_associations_analysis_ready.csv` | expositions contextuelles |
| `final_tables/04_pollutant_outcome_summary.csv` | synthèse polluant–outcome |
| `final_tables/05_per_pmid_summary.csv` | synthèse par publication |
| `final_tables/06_review_rows.csv` | relations nécessitant une revue |
| `final_tables/07_rejected_rows.csv` | relations rejetées et motifs |
| `enrichment/main_associations_enriched.csv` | associations enrichies avec CTD |
| `final/ctd_extraction_final.csv` | dataset consolidé avec population et temporalité |
| `final/ctd_extraction_final.audit.json` | audit de la fusion finale |

## Mapping ICD-10

Le sous-répertoire `icd/` contient :

| Fichier | Description |
| --- | --- |
| `ctd_icd_mapped_complete.csv` | dataset final complété par les champs ICD-10 |
| `mapping_quality_report.csv` | volumes d’entrée, statuts et couverture |
| `mapping_unresolved.csv` | lignes PM2.5/PM10 avec `UNMAPPED_REVIEW` |
| `mapping_conflicts.csv` | erreurs structurelles du référentiel ICD-10 |

Le dataset mappé conserve toutes les colonnes d’entrée et ajoute notamment :

| Colonne | Description |
| --- | --- |
| `outcome_mapping_key` | clé canonique utilisée pour la recherche |
| `mapping_rule_id` | identifiant de la règle appliquée |
| `mapping_scope_status` | statut dans le périmètre PM |
| `mapping_status` | résultat global du mapping |
| `semantic_type` | type sémantique de l’outcome |
| `normalized_health_concept` | concept sanitaire normalisé |
| `endpoint_type` | incidence, mortalité, hospitalisation, etc. |
| `eligible_for_icd` | éligibilité au codage ICD-10 |
| `icd_release` | version ICD utilisée |
| `icd_code` | code ICD-10 lorsqu’un code précis est disponible |
| `icd_title` | intitulé de l’entité ICD-10 |
| `icd_chapter` | chapitre ICD-10 |
| `icd_chapter_name` | intitulé du chapitre |
| `mapping_level` | niveau entité, chapitre ou multi-chapitre |
| `validation_status` | niveau de validation de la règle |
| `mapping_confidence` | confiance attribuée à la règle |
| `mapping_rationale` | justification scientifique |
| `mapping_source_icd_url` | source ICD-10 |
| `mapping_source_evidence_url` | source scientifique complémentaire |
| `mapping_validation_batch` | lot de validation du référentiel |

## Référentiel ICD-10

`config/icd_mapping_reference.csv` contient une règle générale ou spécifique à
un PMID. Les colonnes obligatoires sont contrôlées avant chaque exécution. Tout
conflit est écrit dans `icd/mapping_conflicts.csv` et interrompt le mapping.
