# Dictionnaire des données

## Conventions

Tous les chemins de sortie de ce document sont relatifs à `CTD_DATA_ROOT`.
Sa valeur par défaut est `data/processed/`.

Le dataset final est au niveau **association scientifique**. Un PMID peut
contenir plusieurs lignes lorsqu’il rapporte plusieurs polluants, outcomes,
populations, scénarios, fenêtres ou estimations.

Une cellule vide signifie que l’information n’a pas été trouvée, n’est pas
applicable ou n’a pas été retenue. Les colonnes de statut et de preuve doivent
être consultées avant d’interpréter une valeur manquante.

## Entrées CTD

Les fichiers placés dans `data/raw/` conservent leur structure CTD.

| Motif | Utilisation |
| --- | --- |
| `CTD_D052638_exposure*.csv` | publications candidates pour les particules |
| `CTD_D010126_exposure*.csv` | publications candidates pour l’ozone |
| `CTD_D009585_exposure*.csv` | publications candidates pour le dioxyde d’azote |
| `CTD_D009569_exposure*.csv` | publications candidates pour le monoxyde d’azote |
| `CTD_D052638_genes*.csv` | gènes liés aux particules |
| `CTD_D052638_ixns*.csv` | interactions chimiques–gènes |
| `CTD_D052638_phenotype*.csv` | phénotypes liés aux particules |
| `CTD_D052638_diseases*.csv` | maladies liées aux particules |

## Arborescence des résultats

| Chemin | Contenu |
| --- | --- |
| `ctd_pm_human/` | tables CTD PM filtrées et audit de préparation |
| `pubmed/` | métadonnées et abstracts par PMID |
| `paperclip/` | textes complets, réponses brutes, manifestes et audits |
| `llm_inputs/` | document assemblé pour chaque PMID |
| `segmented_documents/` | sections et segments exploitables par les agents |
| `agent_outputs/` | sorties structurées par agent et par PMID |
| `agent_csv_outputs/` | consolidation tabulaire des sorties des agents |
| `final_tables/` | tables scientifiques, contextuelles et d’audit |
| `enrichment/` | enrichissement CTD des associations PM |
| `final/` | dataset d’extraction consolidé |
| `icd/` | dataset mappé et rapports ICD-10 |
| `logs/` | journaux des runners |

## Sorties des agents

Sous `agent_outputs/`, les fichiers JSON conservent la réponse structurée, les
preuves et les informations de provenance.

| Sous-répertoire | Contenu principal |
| --- | --- |
| `pollutant_extractor/` | polluant général, spécifique, mention originale, rôle, confiance |
| `outcome_extractor/` | outcome normalisé, concept cœur, catégorie, rôle, confiance |
| `effect_measure_extractor/` | type de mesure, valeur, IC, p-value, incrément, méthode |
| `association_builder/` | relations polluant–outcome–mesure par PMID |
| `population_extractor/` | population, âge, sexe, pays, ville ou région |
| `time_extractor/` | fenêtre, durée, période, lag et méthode d’exposition |
| `multi_pmid_runner/` | fusion des associations de tous les PMIDs |
| `final_quality_control/` | décisions et motifs du contrôle qualité |
| `final_inspection/` | séparation entre analyse principale, contexte et revue |

## Dataset final d’extraction

Fichier : `final/ctd_extraction_final.csv`.

### Identité de l’association

| Colonne | Description |
| --- | --- |
| `association_id` | identifiant stable de la relation extraite |
| `pmid` | identifiant PubMed de la publication source |
| `association_label` | libellé lisible de l’association |
| `association_claim` | formulation synthétique de la relation |
| `pollutant_outcome_key` | clé normalisée polluant–outcome |

### Polluant et outcome

| Colonne | Description |
| --- | --- |
| `pollutant_general` | famille de polluant |
| `pollutant_specific` | polluant ou fraction précise |
| `pollutant_original_mention` | formulation rencontrée dans la publication |
| `outcome_normalized` | libellé normalisé de l’outcome |
| `outcome_core` | concept sanitaire central |
| `outcome_category` | catégorie sanitaire |
| `population_group` | groupe de population associé à l’estimation |
| `is_human_study` | indicateur d’étude humaine |

### Mesure d’effet

| Colonne | Description |
| --- | --- |
| `measure_type` | RR, OR, HR, différence, variation, etc. |
| `effect_value` | valeur telle qu’extraite |
| `effect_value_numeric` | représentation numérique exploitable |
| `effect_direction` | augmentation, diminution, nul ou non déterminé |
| `ci_level` | niveau de l’intervalle de confiance |
| `ci_lower`, `ci_upper` | bornes de l’intervalle |
| `p_value` | p-value rapportée |
| `statistical_significance` | statut de significativité extrait |
| `effect_summary` | résumé textuel de l’effet |
| `exposure_increment` | incrément complet associé à la mesure |
| `exposure_increment_value` | valeur numérique de l’incrément |
| `exposure_increment_unit` | unité de l’incrément |
| `adjustment_status` | statut brut ou ajusté |
| `analysis_method` | méthode statistique rapportée |
| `qc_result_context` | principal, sous-groupe, sensibilité ou autre contexte |
| `evidence_sentence` | phrase qui soutient l’estimation |

`effect_value_numeric` ne doit être comparé entre études qu’après vérification
de `measure_type`, de l’incrément, de l’unité, de la population et de la
temporalité.

### Enrichissement CTD

Les colonnes `ctd_*` décrivent le polluant CTD, les correspondances maladie et
phénotype, le type de match, la confiance, les références et les décisions de
mapping. Les colonnes suivantes synthétisent la couche mécanistique :

| Colonne | Description |
| --- | --- |
| `is_pm_d052638_candidate` | association éligible à l’enrichissement PM |
| `mechanistic_enrichment_scope` | portée de l’enrichissement appliqué |
| `outcome_specific_gene_link_available` | présence d’un lien gène–outcome |
| `outcome_specific_gene_count` | nombre de gènes liés à l’outcome |
| `outcome_specific_gene_symbols_top` | principaux symboles de gènes |
| `linked_human_gene_total_available` | volume de gènes humains PM disponibles |
| `linked_human_phenotype_total_available` | volume de phénotypes humains liés |
| `mechanism_available` | indicateur synthétique de mécanisme disponible |

Les associations non-PM sont conservées sans recevoir de mécanisme PM.

### Population et localisation

| Colonne | Description |
| --- | --- |
| `study_country` | pays de l’étude |
| `study_city_or_region` | ville, région ou zone principale |
| `study_location_detail` | précision géographique complémentaire |
| `study_population` | description de la population |
| `age_group` | groupe d’âge normalisé |
| `age_min`, `age_max`, `age_mean` | âges rapportés |
| `sex` | sexe ou composition de la population |
| `population_details` | détails complémentaires |
| `population_location_evidence` | preuve textuelle |
| `population_location_source_section` | section source |
| `population_location_confidence` | confiance de l’extraction |
| `population_location_status` | statut de la sortie |

### Temporalité de l’exposition

| Colonne | Description |
| --- | --- |
| `exposure_window_category` | catégorie de fenêtre d’exposition |
| `exposure_window_text` | formulation rapportée dans l’étude |
| `exposure_duration_value` | durée numérique |
| `exposure_duration_unit` | unité de durée |
| `exposure_lag` | lag rapporté |
| `exposure_period` | période calendaire ou période d’étude |
| `exposure_averaging_window` | fenêtre de moyenne de l’exposition |
| `exposure_assessment_method` | méthode d’évaluation de l’exposition |
| `temporal_evidence_sentence` | preuve textuelle |
| `temporal_source_section` | section source |
| `temporal_confidence` | confiance de l’extraction |
| `temporal_status` | statut de la sortie |

Ces champs qualifient l’estimation publiée. Le pipeline ne recalcule pas la
mesure d’effet en décalant une fenêtre temporelle.

### Provenance technique

Les colonnes `created_at_*`, `agent_*`, `provider_*`, `model_*`,
`source_json_path_*` et `base_url` permettent de relier les enrichissements à
leur sortie d’agent et à leur configuration d’exécution.

## Contrôle qualité

Les sorties de `agent_outputs/final_quality_control/` comprennent notamment :

| Colonne | Description |
| --- | --- |
| `qc_decision` | `accept`, `review` ou `reject` |
| `qc_measure_status` | validité et interprétabilité de la mesure |
| `qc_exposure_status` | statut de l’exposition |
| `qc_outcome_status` | statut de l’outcome |
| `qc_result_context` | contexte analytique de l’estimation |
| `qc_include_in_clean_main_analysis` | inclusion dans l’analyse principale |
| `qc_reasons` | motifs déterministes de la décision |

Les principales tables dérivées sont :

| Chemin | Description |
| --- | --- |
| `final_tables/01_main_associations_analysis.csv` | variables nécessaires à l’analyse principale |
| `final_tables/02_main_associations_scientific.csv` | vue scientifique détaillée |
| `final_tables/03_contextual_associations_analysis_ready.csv` | expositions contextuelles |
| `final_tables/04_pollutant_outcome_summary.csv` | synthèse polluant–outcome |
| `final_tables/05_per_pmid_summary.csv` | synthèse par publication |
| `final_tables/06_review_rows.csv` | relations nécessitant une revue |
| `final_tables/07_rejected_rows.csv` | relations rejetées et motifs |

## Dataset ICD-10

Fichier : `icd/ctd_icd_mapped_complete.csv`.

Il conserve toutes les colonnes du dataset d’extraction et ajoute :

| Colonne | Description |
| --- | --- |
| `outcome_mapping_key` | clé canonique utilisée pour la recherche |
| `mapping_rule_id` | identifiant de la règle appliquée |
| `mapping_scope_status` | statut dans le périmètre du mapping |
| `mapping_status` | résultat global du mapping |
| `semantic_type` | type sémantique de l’outcome |
| `normalized_health_concept` | concept sanitaire normalisé |
| `endpoint_type` | incidence, mortalité, hospitalisation, etc. |
| `eligible_for_icd` | éligibilité au codage ICD-10 |
| `icd_release` | version ICD utilisée |
| `icd_code` | code ICD-10 lorsqu’il est disponible |
| `icd_title` | intitulé de l’entité ICD-10 |
| `icd_chapter` | chapitre ICD-10 |
| `icd_chapter_name` | intitulé du chapitre |
| `mapping_level` | entité, chapitre ou multi-chapitre |
| `validation_status` | statut de validation de la règle |
| `mapping_confidence` | confiance attribuée à la règle |
| `mapping_rationale` | justification scientifique |
| `mapping_source_icd_url` | source ICD-10 |
| `mapping_source_evidence_url` | source scientifique complémentaire |
| `mapping_validation_batch` | lot de validation du référentiel |

Rapports associés :

| Fichier | Description |
| --- | --- |
| `mapping_quality_report.csv` | volumes d’entrée, de sortie et distribution des statuts |
| `mapping_unresolved.csv` | lignes PM avec `UNMAPPED_REVIEW` |
| `mapping_conflicts.csv` | conflits structurels du référentiel |

## Référentiel ICD-10

`config/icd_mapping_reference.csv` contient les règles générales et les règles
spécifiques à un PMID. Une règle spécifique est prioritaire. Les colonnes
obligatoires et l’unicité des règles sont vérifiées à l’exécution ; un conflit
interrompt le mapping.
