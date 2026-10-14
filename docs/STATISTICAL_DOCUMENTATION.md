# Rapport statistique du pipeline

Ce rapport décrit les artefacts de l’exécution de référence présents dans `data/processed`. Les chiffres proviennent des CSV et JSON produits par le pipeline ; aucune valeur n’est estimée lorsqu’un artefact ne la contient pas.

## 1. Executive Summary

La pipeline actuelle part de **434 PMIDs PM candidats uniques** issus de CTD. Le run disponible a réellement traité **432 / 434 PMIDs (99,5 %)** ; les deux PMIDs candidats absents des artefacts traités sont `27384219`, `27633937`. Les agents LLM ont analysé **432 documents**, dont **292 / 432 (67,6 %) avec full text** et **140 / 432 (32,4 %) sans full text**.

Les extractions canoniques sont : **2 306 polluants**, **2 125 outcomes**, **3 409 mesures d’effet**, **432 lignes population/location**, **1 875 lignes de temporalité**. Le builder déterministe a construit **3 003 associations candidates** ; le contrôle qualité a retenu **1 875 associations finales** pour l’analyse principale. Le dataset final consolidé contient **1 875 lignes** et **113 colonnes**.

| Indicateur | Nombre | % du total pertinent |
| --- | --- | --- |
| PMIDs PM candidats CTD | 434 | 100,0 % du corpus PM candidat |
| PMIDs réellement traités | 432 | 99.5 % |
| Abstracts disponibles PubMed/Paperclip | 431 | 99.8 % |
| PMC ID disponibles | 356 | 82.4 % |
| Full texts disponibles | 292 | 67.6 % |
| Documents analysés par agents | 432 | 100.0 % |
| Polluants extraits | 2 306 | mentions normalisées après déduplication par PMID |
| Outcomes extraits | 2 125 | entités normalisées après déduplication par PMID |
| Mesures d’effet extraites | 3 409 | mesures quantitatives/directions |
| Associations candidates | 3 003 | relations polluant-outcome-mesure avant QC |
| Associations finales main analysis | 1 875 | 62.4 % |
| Dataset final consolidé | 1 875 | 1 ligne = 1 association finale |

### Chiffres clés
- Publications PM candidates CTD : **434**.
- Publications traitées : **432 / 434 (99.5 %)**.
- Abstracts disponibles PubMed/Paperclip : **431 / 432 (99.8 %)**.
- Full texts disponibles : **292 / 432 (67.6 %)**.
- Associations candidates : **3 003** ; associations finales : **1 875 / 3 003 (62.4 %)**.
- Enrichissement outcome-specific : **13 502 liens association-gène**, couvrant **339 associations PM**.

## 2. Architecture générale

La séquence réellement utilisée par les artefacts actuels est :

```text
Exports CTD PM et autres polluants
↓
Sélection des PMIDs candidats CTD exposure
↓
Récupération PubMed metadata et abstracts
↓
Récupération full text via Paperclip / Europe PMC quand disponible
↓
Construction des inputs LLM et segmentation
↓
Agents LLM : pollutant, outcome, effect measure
↓
Association builder déterministe
↓
Merge multi-PMID
↓
Quality control final
↓
Tables finales d’analyse
↓
Population/location et temporalité
↓
Enrichissement CTD PM : disease, phenotype, gènes PM-level, gènes outcome-specific
↓
Fusion finale : ctd_extraction_final.csv
```

| Étape | Objectif | Entrée | Sortie | Volume entrant | Volume sortant | Taux |
| --- | --- | --- | --- | --- | --- | --- |
| CTD exposure PM | Identifier les articles candidats | data/raw/CTD_D052638_exposure*.csv | ctd_pm_human/exposure_pm_candidates.csv | 821 | 434 | 52.9 % |
| PubMed/Paperclip | Récupérer metadata, abstract, PMC/full text | PMIDs candidats | documents_manifest_test_with_paperclip.csv | 434 | 432 | 99.5 % |
| Segmentation | Transformer les textes en chunks | LLM inputs | segmented_documents_manifest_test.csv | 432 | 432 | 100.0 % |
| Pollutant extractor | Extraire les polluants | 432 documents segmentés | 2 306 polluants | 432 | 2 306 | — |
| Outcome extractor | Extraire les endpoints santé | 432 documents segmentés + polluants | 2 125 outcomes | 432 | 2 125 | — |
| Effect extractor | Extraire mesures quantitatives | 432 documents + entités précédentes | 3 409 mesures | 432 | 3 409 | — |
| Association builder | Construire relation polluant-outcome-mesure | Mesures gardées | 3 003 associations | 3 183 | 3 003 | 94.3 % |
| Quality control | Accepter/review/rejeter | 3 003 associations | 1 875 main analysis | 3 003 | 1 875 | 62.4 % |
| Enrichissement CTD | Ajouter contexte mécanistique PM | 1 875 associations finales | 1 875 lignes enrichies | 1 875 | 1 875 | 100.0 % |

## 3. Sources de données et outils utilisés

### CTD
CTD fournit les exports bruts utilisés pour sélectionner les PMIDs et enrichir les associations PM. Le filtre principal est `D052638`, identifiant CTD de `Particulate Matter`.

| Table CTD | Lignes brutes | Après filtre PM | Après filtre humain | Règle |
| --- | --- | --- | --- | --- |
| Exposition PM CTD | 821 | 434 | non disponible | Stressor Agent contient PM |
| Interactions gène-chimique | 66 552 | 29 697 | 16 700 | Chemical ID=D052638 puis Organisms contient Homo sapiens |
| Phénotypes | 4 830 | 3 215 | 1 485 | Chemical ID=D052638 puis Organisms contient Homo sapiens |
| Maladies | 17 516 | 4 615 | non applicable | Chemical ID=D052638 ; pas de colonne espèce |
| Gènes globaux CTD | 20 155 | — | 8 807 | gènes dérivés des interactions PM-humain |

### PubMed
PubMed fournit les métadonnées, titres, DOI, journal, année et abstracts. Les artefacts actuels contiennent **432 PMIDs traités**, dont **431 avec abstract** et **1 sans abstract PubMed/Paperclip**.

### Paperclip / Europe PMC
Paperclip/Europe PMC sert à récupérer les textes intégraux. Le manifest indique **292 full texts disponibles**. Les modes de récupération observés sont : `reuse_existing`=5, `vide`=76, `cli`=64, `europepmc`=287.

### LLM et runners
Les agents LLM utilisent le client configuré dans `src/llm/client.py` via les variables `ILAAS_*`. Les sorties tracent le provider, le modèle, les réponses brutes, les réparations JSON et les fichiers de raisonnement. Les statistiques agents ci-dessous utilisent les JSON canoniques dans `data/processed/agent_outputs/*`, pas les CSV globaux d’export qui peuvent contenir des artefacts de tests.

### Chiffres clés
- CTD exposure PM : **434 / 821 lignes (52.9 %)**.
- Interactions PM-humain CTD : **16 700**.
- Gènes humains PM dérivés : **8 807**.
- Full texts récupérés : **292 / 432 (67.6 %)**.

## 4. Couverture documentaire : abstracts et full texts

| Indicateur | Nombre | Pourcentage |
| --- | --- | --- |
| Total PMIDs traités | 432 | 100,0 % |
| Avec abstract PubMed/Paperclip | 431 | 99.8 % |
| Sans abstract PubMed/Paperclip | 1 | 0.2 % |
| Avec full text | 292 | 67.6 % |
| Sans full text | 140 | 32.4 % |
| Avec PMC ID | 356 | 82.4 % |
| PMC ID sans full text récupéré | 64 | 14.8 % |

Croisement abstract/full text :

| Catégorie documentaire | Documents | % des documents traités |
| --- | --- | --- |
| abstract + full text | 292 | 67.6 % |
| abstract seul | 139 | 32.2 % |
| ni abstract ni full text | 1 | 0.2 % |

Le manifest de segmentation marque **432 / 432 documents avec `has_abstract=True`**, mais cette valeur inclut un cas title-only transformé en pseudo-abstract par la segmentation. La couverture PubMed/Paperclip stricte est donc **431 / 432**.

### Chiffres clés
- Documents traités : **432**.
- Abstracts stricts PubMed/Paperclip : **431 / 432 (99.8 %)**.
- Full texts : **292 / 432 (67.6 %)**.
- Abstract/title-only sans full text : **140 / 432 (32.4 %)**.

## 5. Extraction des polluants

Le `pollutant_extractor` a produit **2 306 polluants** dans **426 / 432 documents (98.6 %)**. La moyenne est **5.41 polluants par document avec polluant**, la médiane **5.0**, le minimum **1**, le maximum **34**. Les documents sans polluant extrait sont **6 / 432 (1.4 %)**.

| Famille de polluant | Mentions | Documents | % des polluants |
| --- | --- | --- | --- |
| PM / particules | 726 | 412 | 31.5 % |
| pollution de l’air générale | 393 | 284 | 17.0 % |
| other | 334 | 144 | 14.5 % |
| NO2 | 161 | 157 | 7.0 % |
| trafic / route | 158 | 115 | 6.9 % |
| O3 / ozone | 112 | 111 | 4.9 % |
| NOx | 97 | 82 | 4.2 % |
| SO2 | 73 | 73 | 3.2 % |
| black carbon | 69 | 69 | 3.0 % |
| fumées / combustion | 50 | 33 | 2.2 % |
| métaux / éléments | 37 | 15 | 1.6 % |
| CO | 32 | 32 | 1.4 % |
| soot / black smoke | 25 | 23 | 1.1 % |
| VOC / PAH | 19 | 12 | 0.8 % |
| NO | 17 | 17 | 0.7 % |
| H2S | 3 | 3 | 0.1 % |

Décomposition PM / particules :

| Type PM | Mentions | Documents | % des PM | % total polluants |
| --- | --- | --- | --- | --- |
| PM2.5 | 323 | 323 | 44.5 % | 14.0 % |
| PM10 | 187 | 187 | 25.8 % | 8.1 % |
| PM non spécifié | 135 | 135 | 18.6 % | 5.9 % |
| ultrafine particles / UFP | 40 | 40 | 5.5 % | 1.7 % |
| fine PM | 25 | 25 | 3.4 % | 1.1 % |
| PM1 | 13 | 13 | 1.8 % | 0.6 % |
| coarse PM | 3 | 3 | 0.4 % | 0.1 % |

Top polluants normalisés extraits :

| Rang | Polluant spécifique | Mentions | Documents | % |
| --- | --- | --- | --- | --- |
| 1 | PM2.5 | 323 | 323 | 14.0 % |
| 2 | air pollution | 251 | 251 | 10.9 % |
| 3 | PM10 | 187 | 187 | 8.1 % |
| 4 | particulate matter | 163 | 163 | 7.1 % |
| 5 | NO2 | 157 | 157 | 6.8 % |
| 6 | O3 | 111 | 111 | 4.8 % |
| 7 | traffic-related pollution | 107 | 107 | 4.6 % |
| 8 | CO | 79 | 79 | 3.4 % |
| 9 | SO2 | 73 | 73 | 3.2 % |
| 10 | ambient air pollution | 72 | 72 | 3.1 % |
| 11 | black carbon | 68 | 68 | 2.9 % |
| 12 | air pollutants | 55 | 55 | 2.4 % |
| 13 | NOx | 45 | 45 | 2.0 % |
| 14 | ultrafine particles | 40 | 40 | 1.7 % |
| 15 | road proximity | 27 | 27 | 1.2 % |
| 16 | elemental carbon | 20 | 20 | 0.9 % |
| 17 | NO | 17 | 17 | 0.7 % |
| 18 | woodsmoke | 16 | 16 | 0.7 % |
| 19 | black smoke | 13 | 13 | 0.6 % |
| 20 | PM1 | 13 | 13 | 0.6 % |

### Chiffres clés
- Polluants extraits : **2 306**.
- Documents avec ≥1 polluant : **426 / 432 (98.6 %)**.
- Mentions PM / particules : **726 / 2 306 (31.5 %)**.
- Polluants cibles projet selon agent : **1 011 / 2 306 (43.8 %)**.

## 6. Extraction des outcomes

Le `outcome_extractor` a produit **2 125 outcomes** dans **330 / 432 documents (76.4 %)**. La moyenne est **6.44 outcomes par document avec outcome**, médiane **5.0**, min **1**, max **31**. Les documents sans outcome extrait sont **102 / 432 (23.6 %)**.

Distribution par rôle outcome :
| Rang | Rôle | Occurrences | Documents | % |
| --- | --- | --- | --- | --- |
| 1 | primary_outcome | 1 073 | 293 | 50.5 % |
| 2 | secondary_outcome | 461 | 145 | 21.7 % |
| 3 | endpoint_variant | 411 | 148 | 19.3 % |
| 4 | case_definition_component | 179 | 95 | 8.4 % |
| 5 | ambiguous | 1 | 1 | 0.0 % |

Distribution par catégorie outcome :
| Rang | Catégorie | Occurrences | Documents | % |
| --- | --- | --- | --- | --- |
| 1 | health_outcome | 1 581 | 304 | 74.4 % |
| 2 | respiratory_disease | 248 | 110 | 11.7 % |
| 3 | cardiovascular_disease | 203 | 83 | 9.6 % |
| 4 | cancer | 66 | 30 | 3.1 % |
| 5 | renal_disease | 13 | 4 | 0.6 % |
| 6 | neurodegenerative_disease | 12 | 6 | 0.6 % |
| 7 | reproductive_outcome | 2 | 2 | 0.1 % |

Top outcomes normalisés :
| Rang | Outcome core | Occurrences | Documents | % |
| --- | --- | --- | --- | --- |
| 1 | asthma | 69 | 47 | 3.2 % |
| 2 | mortality | 40 | 39 | 1.9 % |
| 3 | cardiovascular mortality | 38 | 32 | 1.8 % |
| 4 | cardiovascular disease | 29 | 25 | 1.4 % |
| 5 | lung cancer | 27 | 22 | 1.3 % |
| 6 | respiratory mortality | 24 | 17 | 1.1 % |
| 7 | low birth weight | 22 | 15 | 1.0 % |
| 8 | systolic blood pressure | 22 | 17 | 1.0 % |
| 9 | preterm birth | 19 | 17 | 0.9 % |
| 10 | chronic obstructive pulmonary disease | 18 | 17 | 0.8 % |
| 11 | diastolic blood pressure | 18 | 14 | 0.8 % |
| 12 | blood pressure | 17 | 17 | 0.8 % |
| 13 | all cause mortality | 16 | 14 | 0.8 % |
| 14 | ischemic heart disease | 16 | 14 | 0.8 % |
| 15 | stroke | 16 | 14 | 0.8 % |
| 16 | systolic bp | 15 | 9 | 0.7 % |
| 17 | respiratory diseases | 15 | 13 | 0.7 % |
| 18 | lung function | 14 | 13 | 0.7 % |
| 19 | respiratory symptoms | 13 | 13 | 0.6 % |
| 20 | pneumonia | 13 | 10 | 0.6 % |

### Chiffres clés
- Outcomes extraits : **2 125**.
- Outcomes gardés pour analyse finale selon agent : **1 946 / 2 125 (91.6 %)**.
- Documents avec ≥1 outcome : **330 / 432 (76.4 %)**.

## 7. Mesures / Measures

Une `measure` correspond ici à une mesure d’effet quantitative ou statistique extraite pour une relation polluant-outcome : OR, RR, HR, beta, percent change, p-value-only, diagnostic, etc. Seules les mesures complètes de type effet direct peuvent alimenter le builder d’associations.

Mesures extraites : **3 409** dans **294 / 432 documents (68.1 %)**. Mesures gardées pour le builder : **3 183 / 3 409 (93.4 %)**.

Distribution par type de mesure :
| Rang | Type mesure | Occurrences | Documents | % |
| --- | --- | --- | --- | --- |
| 1 | percent_change | 1 121 | 123 | 32.9 % |
| 2 | beta | 935 | 92 | 27.4 % |
| 3 | OR | 633 | 77 | 18.6 % |
| 4 | RR | 318 | 31 | 9.3 % |
| 5 | HR | 287 | 25 | 8.4 % |
| 6 | other | 49 | 10 | 1.4 % |
| 7 | IRR | 24 | 2 | 0.7 % |
| 8 | por | 18 | 1 | 0.5 % |
| 9 | p_value | 11 | 7 | 0.3 % |
| 10 | count | 8 | 1 | 0.2 % |
| 11 | difference | 2 | 1 | 0.1 % |
| 12 | slope | 2 | 1 | 0.1 % |
| 13 | risk quotient | 1 | 1 | 0.0 % |

Distribution par rôle de mesure :
| Rang | Rôle mesure | Occurrences | Documents | % |
| --- | --- | --- | --- | --- |
| 1 | direct_effect_estimate | 3 336 | 294 | 97.9 % |
| 2 | incomplete_effect_description | 49 | 16 | 1.4 % |
| 3 | p_value_only | 10 | 6 | 0.3 % |
| 4 | gene_association | 7 | 1 | 0.2 % |
| 5 | heterogeneity_test | 5 | 3 | 0.1 % |
| 6 | model_diagnostic | 2 | 2 | 0.1 % |

Unités extraites dans `exposure_increment_unit` :
| Rang | Unité | Occurrences | % |
| --- | --- | --- | --- |
| 1 | μg/m3 | 719 | 48.2 % |
| 2 | µg/m3 | 455 | 30.5 % |
| 3 | microg/m3 | 82 | 5.5 % |
| 4 | ppb | 75 | 5.0 % |
| 5 | ng/m3 | 32 | 2.1 % |
| 6 | 0 | 26 | 1.7 % |
| 7 | SD | 24 | 1.6 % |
| 8 | μg/kg | 14 | 0.9 % |
| 9 | ppm | 11 | 0.7 % |
| 10 | unit | 9 | 0.6 % |
| 11 | pphm | 6 | 0.4 % |
| 12 | microm2 | 5 | 0.3 % |
| 13 | dB | 5 | 0.3 % |
| 14 | µg/m | 5 | 0.3 % |
| 15 | year | 4 | 0.3 % |
| 16 | mg/m3 | 3 | 0.2 % |
| 17 | μg.m | 3 | 0.2 % |
| 18 | hr | 2 | 0.1 % |
| 19 | microg | 2 | 0.1 % |
| 20 | μg | 2 | 0.1 % |

### Chiffres clés
- Mesures extraites : **3 409**.
- Mesures directes gardées pour builder : **3 183 / 3 409 (93.4 %)**.
- Documents avec ≥1 mesure : **294 / 432 (68.1 %)**.

## 8. Population

Le `population_extractor` produit une ligne par document : **432 / 432 documents (100.0 %)**. Les données sont ensuite jointes au dataset final par `pmid`, donc chaque association finale hérite de la population/localisation du document.

Statut et confiance population :
| Rang | Status | Occurrences | Documents | % |
| --- | --- | --- | --- | --- |
| 1 | explicit | 344 | 344 | 79.6 % |
| 2 | multiple | 63 | 63 | 14.6 % |
| 3 | not_reported | 23 | 23 | 5.3 % |
| 4 | review | 2 | 2 | 0.5 % |

| Rang | Confiance | Occurrences | Documents | % |
| --- | --- | --- | --- | --- |
| 1 | high | 430 | 430 | 99.5 % |
| 2 | low | 2 | 2 | 0.5 % |

Pays les plus fréquents :
| Rang | Pays | Documents | Documents | % |
| --- | --- | --- | --- | --- |
| 1 | not_reported | 106 | 106 | 24.5 % |
| 2 | United States | 92 | 92 | 21.3 % |
| 3 | China | 32 | 32 | 7.4 % |
| 4 | Canada | 15 | 15 | 3.5 % |
| 5 | Belgium | 14 | 14 | 3.2 % |
| 6 | Taiwan | 11 | 11 | 2.5 % |
| 7 | United Kingdom | 11 | 11 | 2.5 % |
| 8 | Italy | 11 | 11 | 2.5 % |
| 9 | Netherlands | 10 | 10 | 2.3 % |
| 10 | Brazil | 9 | 9 | 2.1 % |
| 11 | India | 7 | 7 | 1.6 % |
| 12 | Spain | 6 | 6 | 1.4 % |
| 13 | Germany | 6 | 6 | 1.4 % |
| 14 | Mexico | 6 | 6 | 1.4 % |
| 15 | Japan | 6 | 6 | 1.4 % |
| 16 | South Korea | 6 | 6 | 1.4 % |
| 17 | Czech Republic | 5 | 5 | 1.2 % |
| 18 | Sweden | 5 | 5 | 1.2 % |
| 19 | Australia | 3 | 3 | 0.7 % |
| 20 | Nepal | 3 | 3 | 0.7 % |

Sexe :
| Rang | Sexe | Documents | Documents | % |
| --- | --- | --- | --- | --- |
| 1 | not_reported | 184 | 184 | 42.6 % |
| 2 | both | 179 | 179 | 41.4 % |
| 3 | female | 39 | 39 | 9.0 % |
| 4 | male | 23 | 23 | 5.3 % |
| 5 | ambiguous | 6 | 6 | 1.4 % |
| 6 | review | 1 | 1 | 0.2 % |

Groupes d’âge :
| Rang | Groupe âge | Documents | Documents | % |
| --- | --- | --- | --- | --- |
| 1 | not_reported | 173 | 173 | 40.0 % |
| 2 | adults | 30 | 30 | 6.9 % |
| 3 | elderly | 21 | 21 | 4.9 % |
| 4 | children | 10 | 10 | 2.3 % |
| 5 | newborns | 9 | 9 | 2.1 % |
| 6 | young adults | 7 | 7 | 1.6 % |
| 7 | adult | 5 | 5 | 1.2 % |
| 8 | 45-84 years | 3 | 3 | 0.7 % |
| 9 | older adults | 3 | 3 | 0.7 % |
| 10 | middle-aged | 3 | 3 | 0.7 % |
| 11 | 57-85 years | 2 | 2 | 0.5 % |
| 12 | adults; children | 2 | 2 | 0.5 % |
| 13 | school-aged | 2 | 2 | 0.5 % |
| 14 | 50-65 years | 2 | 2 | 0.5 % |
| 15 | ambiguous | 2 | 2 | 0.5 % |
| 16 | 0-14 years | 2 | 2 | 0.5 % |
| 17 | children and adolescents | 2 | 2 | 0.5 % |
| 18 | 30-70 years | 2 | 2 | 0.5 % |
| 19 | children and young adults | 2 | 2 | 0.5 % |
| 20 | 6-14 years | 2 | 2 | 0.5 % |

La taille d’échantillon des études n’est pas extraite dans un champ structuré actuel. **Statistique non disponible dans les artefacts actuels.** Il faudrait ajouter un champ `sample_size` à `population_extractor` pour calculer cumul, moyenne, médiane et min/max de taille d’étude.

### Chiffres clés
- Lignes population/location : **432 / 432 (100.0 %)**.
- Associations finales avec pays non manquant : **1 555 / 1 875 (82.9 %)**.
- Associations finales avec population non manquante : **1 866 / 1 875 (99.5 %)**.

## 9. Informations temporelles

Le `time_extractor` travaille au niveau association finale. Il a produit **1 875 lignes temporelles**, soit **1 875 / 1 875 associations finales (100.0 %)**. Il extrait la fenêtre d’exposition, le lag, la période, l’averaging window et la méthode d’évaluation quand disponibles.

Catégories temporelles :
| Rang | Catégorie fenêtre | Occurrences | Documents | % |
| --- | --- | --- | --- | --- |
| 1 | long_term | 793 | 110 | 42.3 % |
| 2 | short_term | 501 | 99 | 26.7 % |
| 3 | prenatal | 130 | 26 | 6.9 % |
| 4 | lagged | 119 | 31 | 6.3 % |
| 5 | multiple | 118 | 32 | 6.3 % |
| 6 | trimester_specific | 116 | 20 | 6.2 % |
| 7 | not_reported | 50 | 20 | 2.7 % |
| 8 | early_life | 27 | 4 | 1.4 % |
| 9 | ambiguous | 12 | 8 | 0.6 % |
| 10 | cumulative | 4 | 2 | 0.2 % |
| 11 | repeated_measure | 3 | 2 | 0.2 % |
| 12 | lifetime | 2 | 1 | 0.1 % |

Statuts temporels :
| Rang | Status | Occurrences | Documents | % |
| --- | --- | --- | --- | --- |
| 1 | explicit | 1 688 | 226 | 90.0 % |
| 2 | multiple | 123 | 34 | 6.6 % |
| 3 | not_reported | 52 | 22 | 2.8 % |
| 4 | ambiguous | 12 | 8 | 0.6 % |

Confiance temporelle :
| Rang | Confiance | Occurrences | Documents | % |
| --- | --- | --- | --- | --- |
| 1 | high | 1 836 | 234 | 97.9 % |
| 2 | low | 25 | 14 | 1.3 % |
| 3 | medium | 13 | 8 | 0.7 % |
| 4 | not_reported | 1 | 1 | 0.1 % |

Lags les plus fréquents :
| Rang | Lag | Occurrences | % |
| --- | --- | --- | --- |
| 1 | 0 | 46 | 13.5 % |
| 2 | 1 day | 23 | 6.7 % |
| 3 | 0-1 days | 17 | 5.0 % |
| 4 | 0-4 | 17 | 5.0 % |
| 5 | up to 24 hours | 16 | 4.7 % |
| 6 | 24 to 72 hours | 11 | 3.2 % |
| 7 | up to 4 days | 8 | 2.3 % |
| 8 | 0-2 days | 7 | 2.0 % |
| 9 | 2 | 7 | 2.0 % |
| 10 | 0-2 | 7 | 2.0 % |
| 11 | 0-4 days | 6 | 1.8 % |
| 12 | 2 years | 6 | 1.8 % |
| 13 | 0-14 | 6 | 1.8 % |
| 14 | 0-5 days | 6 | 1.8 % |
| 15 | 1 | 5 | 1.5 % |
| 16 | 0-7 days | 5 | 1.5 % |
| 17 | 0-4 lags (0-2 hours) | 5 | 1.5 % |
| 18 | 0-5 | 4 | 1.2 % |
| 19 | lags up to 4 days | 4 | 1.2 % |
| 20 | 3 days | 4 | 1.2 % |

### Chiffres clés
- Lignes temporelles : **1 875 / 1 875 associations finales (100.0 %)**.
- Associations finales avec catégorie temporelle non manquante : **1 813 / 1 875 (96.7 %)**.
- Associations finales avec lag non manquant : **342 / 1 875 (18.2 %)**.

## 10. Associations polluant → outcome

Une association est une ligne structurée reliant un polluant, un outcome de santé et une mesure d’effet quantitative extraite d’un article. Une formulation slide-ready est : **relation exposition-santé quantifiée**.

Associations candidates : **3 003** dans **288 / 432 documents (66.7 %)**. Associations finales main analysis : **1 875** dans **237 documents**. Moyenne finale par document avec association finale : **7.91**, médiane **6**, min **1**, max **41**.

Polluants dans les associations finales :
| Polluant | Associations | Documents | % des finales |
| --- | --- | --- | --- |
| PM2.5 | 1 119 | 153 | 59.7 % |
| PM10 | 426 | 71 | 22.7 % |
| NO2 | 199 | 48 | 10.6 % |
| O3 | 95 | 27 | 5.1 % |
| particulate matter | 20 | 8 | 1.1 % |
| ultrafine particles | 8 | 2 | 0.4 % |
| PM1 | 6 | 1 | 0.3 % |
| NO | 2 | 2 | 0.1 % |

Direction des associations finales :
| Rang | Direction | Associations | Documents | % |
| --- | --- | --- | --- | --- |
| 1 | increase | 1 641 | 232 | 87.5 % |
| 2 | decrease | 231 | 60 | 12.3 % |
| 3 | (vide) | 3 | 3 | 0.2 % |

Significativité statistique :
| Rang | Significativité | Associations | Documents | % |
| --- | --- | --- | --- | --- |
| 1 | significant | 1 399 | 204 | 74.6 % |
| 2 | non_significant | 375 | 105 | 20.0 % |
| 3 | unknown | 101 | 33 | 5.4 % |

Types d’effet dans les associations finales :
| Rang | Type effet | Associations | Documents | % |
| --- | --- | --- | --- | --- |
| 1 | percent_change | 543 | 93 | 29.0 % |
| 2 | beta | 543 | 73 | 29.0 % |
| 3 | OR | 435 | 67 | 23.2 % |
| 4 | HR | 202 | 23 | 10.8 % |
| 5 | RR | 130 | 25 | 6.9 % |
| 6 | IRR | 22 | 2 | 1.2 % |

Top polluant × outcome :
| Rang | Polluant | Outcome | Associations | % |
| --- | --- | --- | --- | --- |
| 1 | PM2.5 | lung cancer | 37 | 2.0 % |
| 2 | PM2.5 | asthma | 29 | 1.5 % |
| 3 | PM2.5 | cardiovascular mortality | 27 | 1.4 % |
| 4 | PM2.5 | peak expiratory flow | 27 | 1.4 % |
| 5 | PM2.5 | mortality | 26 | 1.4 % |
| 6 | PM10 | asthma | 23 | 1.2 % |
| 7 | PM10 | childhood leukemia | 23 | 1.2 % |
| 8 | PM2.5 | under five deaths | 22 | 1.2 % |
| 9 | PM2.5 | anosmia | 22 | 1.2 % |
| 10 | PM2.5 | maternal deaths | 19 | 1.0 % |
| 11 | PM2.5 | intrauterine inflammation | 17 | 0.9 % |
| 12 | PM2.5 | st segment height | 15 | 0.8 % |
| 13 | PM10 | systolic blood pressure | 15 | 0.8 % |
| 14 | PM10 | diastolic blood pressure | 15 | 0.8 % |
| 15 | PM10 | preterm birth | 15 | 0.8 % |
| 16 | PM2.5 | impaired fasting glucose | 15 | 0.8 % |
| 17 | PM2.5 | all cause mortality | 14 | 0.7 % |
| 18 | PM2.5 | ischemic heart disease mortality | 14 | 0.7 % |
| 19 | PM2.5 | right ventricular mass | 13 | 0.7 % |
| 20 | PM2.5 | incident stroke | 13 | 0.7 % |

### Chiffres clés
- Associations candidates : **3 003**.
- Associations finales : **1 875 / 3 003 (62.4 %)**.
- PM dans final : **1 579 / 1 875 (84.2 %)**.
- Documents avec association finale : **237 / 432 (54.9 %)**.

## 11. Contrôle qualité

Le QC applique trois familles de règles : validité de la mesure, validité de l’exposition, validité de l’outcome, puis classification du contexte de résultat. Il produit `accept`, `review` ou `reject`.
| Décision QC | Associations | % des candidates |
| --- | --- | --- |
| accept | 2 660 | 88.6 % |
| review | 93 | 3.1 % |
| reject | 250 | 8.3 % |

Rôles QC :
| Rôle QC | Associations | % des candidates |
| --- | --- | --- |
| main_project_clean_association | 1 875 | 62.4 % |
| contextual_air_pollution_association | 737 | 24.5 % |
| target_pollutant_secondary_or_review_association | 48 | 1.6 % |
| review_association | 93 | 3.1 % |
| rejected_association | 250 | 8.3 % |

Statuts exposition QC :
| Statut exposition | Associations | % des candidates |
| --- | --- | --- |
| project_target_air_pollutant | 1 923 | 64.0 % |
| contextual_air_pollutant | 713 | 23.7 % |
| review_exposure | 93 | 3.1 % |
| source_marker_air_pollution | 24 | 0.8 % |
| reject_exposure | 250 | 8.3 % |

Statuts mesure QC :
| Statut mesure | Associations | % des candidates |
| --- | --- | --- |
| valid_measure | 3 003 | 100.0 % |

Raisons de rejet/review les plus fréquentes :
| Rang | Raison | Occurrences | % |
| --- | --- | --- | --- |
| 1 | covariate_or_non_pollutant_effect | 135 | 26.3 % |
| 2 | valid_percent_change_effect_estimate_without_ci_or_p | 130 | 25.3 % |
| 3 | non_air_pollution_exposure | 115 | 22.4 % |
| 4 | ambiguous_or_non_target_exposure | 93 | 18.1 % |
| 5 | subgroup_analysis_detected | 13 | 2.5 % |
| 6 | result_context=subgroup_analysis | 13 | 2.5 % |
| 7 | valid_direct_effect_estimate_without_ci_or_p | 9 | 1.8 % |
| 8 | sensitivity_analysis_detected | 2 | 0.4 % |
| 9 | result_context=sensitivity_analysis | 2 | 0.4 % |
| 10 | concentration_response_detected | 1 | 0.2 % |
| 11 | result_context=concentration_response | 1 | 0.2 % |

### Chiffres clés
- Acceptées QC : **2 660 / 3 003 (88.6 %)**.
- Review QC : **93 / 3 003 (3.1 %)**.
- Rejetées QC : **250 / 3 003 (8.3 %)**.
- Main analysis clean : **1 875 / 3 003 (62.4 %)**.

## 12. Analyse de complétude

Complétude des champs importants dans `ctd_extraction_final.csv` :
| Champ | Présent | Manquant | Complétude |
| --- | --- | --- | --- |
| association_id | 1 875 | 0 | 100.0 % |
| pmid | 1 875 | 0 | 100.0 % |
| pollutant_specific | 1 875 | 0 | 100.0 % |
| pollutant_general | 1 875 | 0 | 100.0 % |
| outcome_normalized | 1 875 | 0 | 100.0 % |
| measure_type | 1 875 | 0 | 100.0 % |
| effect_value | 1 875 | 0 | 100.0 % |
| ci_lower | 1 635 | 240 | 87.2 % |
| ci_upper | 1 635 | 240 | 87.2 % |
| p_value | 392 | 1 483 | 20.9 % |
| exposure_increment | 1 853 | 22 | 98.8 % |
| study_country | 1 555 | 320 | 82.9 % |
| study_population | 1 866 | 9 | 99.5 % |
| sex | 1 428 | 447 | 76.2 % |
| exposure_window_category | 1 813 | 62 | 96.7 % |
| exposure_window_text | 1 814 | 61 | 96.7 % |
| ctd_disease_name | 1 211 | 664 | 64.6 % |
| ctd_phenotype_name | 627 | 1 248 | 33.4 % |
| outcome_specific_gene_symbols_top | 339 | 1 536 | 18.1 % |

## 13. Enrichissement

L’enrichissement CTD est limité aux PM pour la couche mécanistique. Les **296 associations non-PM** restent dans le fichier enrichi, mais ne reçoivent pas de mécanisme CTD inventé. La méthode distingue deux niveaux : `PM-level context` et `outcome-specific`.

### Disease et phenotype
Sur **421 outcome keys PM**, **76 / 421 (18.1 %)** ont un mapping disease accepté et **36 / 421 (8.6 %)** ont un mapping phenotype accepté.

### Gènes PM-level
L’enrichissement contextuel PM-level est disponible dans `association_pm_gene_links_top.csv` : **315 800 liens**, soit **1 579 associations PM × 200 top gènes PM humains**. Ce fichier est explicitement noté comme contexte PM général, non outcome-specific.

### Gènes outcome-specific
Le fichier `association_pm_gene_links_outcome_specific.csv` contient **13 502 liens association-gène**, couvrant **339 / 1 579 associations PM (21.5 %)** et **1 070 gènes uniques**. La règle est : gène présent dans le `Inference Network` CTD du disease/phenotype mappé à l’outcome, et aussi présent dans les gènes PM-humains CTD.

Distribution des liens outcome-specific :
| Rang | Type mapping CTD | Liens | Documents | % |
| --- | --- | --- | --- | --- |
| 1 | disease | 10 687 | 49 | 79.2 % |
| 2 | phenotype | 2 815 | 16 | 20.8 % |

### Chiffres clés
- Associations PM enrichissables : **1 579 / 1 875 (84.2 %)**.
- Disease acceptés : **76 / 421 (18.1 %)**.
- Phenotype acceptés : **36 / 421 (8.6 %)**.
- Liens gènes outcome-specific : **13 502**.

## 14. Normalisation des données

La normalisation est appliquée par les agents et les builders : synonymes polluants (`PM2.5`, `pm 2.5`, `particulate matter 2.5`), outcomes core (`asthma diagnosis` vers `asthma` lorsque reconnu), types de mesures (`odds ratio` vers `OR`), valeurs numériques, p-values et unités. Les règles sont implémentées dans `src/agents/pollutant_extractor.py`, `src/agents/outcome_extractor.py`, `src/agents/effect_measure_extractor.py` et `src/builders/association_builder.py`.

| Élément | Valeurs brutes/occurrences | Valeurs normalisées uniques | Réduction/observation |
| --- | --- | --- | --- |
| Polluants extraits | 2 306 | 348 | normalisation vers `pollutant_specific` |
| Outcomes extraits | 2 125 | 1 064 | normalisation vers `outcome_core` |
| Types de mesures | 3 409 | 13 | normalisation vers OR/RR/HR/beta/percent_change/etc. |
| Polluant-outcome final | 1 875 | 620 | clé final_tables |

## 15. Déduplication

Les agents dédupliquent par concept normalisé au niveau PMID ; le builder déduplique les associations par clé scientifique (`pmid`, polluant, outcome, type de mesure, valeur, CI, p-value, méthode). Le merge multi-PMID empile ensuite les sorties. Les artefacts globaux `agent_csv_outputs` ne sont pas utilisés pour les comptes canoniques des agents car ils contiennent aussi des tests de cohérence modèle.

| Niveau | Avant / source | Après déduplication | Règle |
| --- | --- | --- | --- |
| PMIDs PM exposure CTD | 434 | 434 | unicité PMID |
| Pollutant extractor | chunks LLM | 2 306 | un polluant par concept normalisé et PMID |
| Outcome extractor | chunks LLM | 2 125 | outcome_key / outcome_core + rôle |
| Effect extractor | chunks LLM | 3 409 | clé polluant/outcome/mesure/statistique |
| Association builder | 3 183 | 3 003 | clé scientifique association |

## 16. Funnel du pipeline

| Étape | Volume | Perte vs étape précédente | % conservé vs dénominateur |
| --- | --- | --- | --- |
| PMIDs PM candidats CTD uniques | 434 | — | 100.0 % |
| PMIDs traités | 432 | 2 | 99.5 % |
| Avec abstract PubMed/Paperclip | 431 | 1 | 99.8 % |
| Avec full text | 292 | 139 | 67.6 % |
| Documents analysés par agents | 432 | -140 | 100.0 % |
| Documents avec ≥1 polluant | 426 | 6 | 98.6 % |
| Documents avec ≥1 outcome | 330 | 96 | 76.4 % |
| Documents avec ≥1 mesure | 294 | 36 | 68.1 % |
| Documents avec ≥1 association candidate | 288 | 6 | 66.7 % |
| Documents avec ≥1 association finale | 237 | 51 | 54.9 % |
| Associations candidates | 3 003 | -2 766 | 100.0 % |
| Associations clean database | 2 753 | 250 | 91.7 % |
| Associations finales main analysis | 1 875 | 878 | 62.4 % |
| Lignes dataset final | 1 875 | 0 | 100.0 % |

## 17. Statistiques au niveau article/document

| Extraction | Documents avec ≥1 élément | Moyenne | Médiane | Min | Max | PMID max |
| --- | --- | --- | --- | --- | --- | --- |
| Polluants | 426 | 5.41 | 5.0 | 1 | 34 | 29467104 (34) |
| Outcomes | 330 | 6.44 | 5.0 | 1 | 31 | 25252923 (31) |
| Measures | 294 | 11.60 | 8.0 | 1 | 61 | 22892901 (61) |
| Associations candidates | 288 | 10.43 | 8.0 | 1 | 61 | 22892901 (61) |
| Associations finales | 237 | 7.91 | 6 | 1 | 41 | 31614721 (41) |

## 18. Analyses croisées

Polluant × direction dans les associations finales :
| Polluant |  | decrease | increase | Total |
| --- | --- | --- | --- | --- |
| PM2.5 | 1 | 164 | 954 | 1 119 |
| PM10 | 2 | 31 | 393 | 426 |
| NO2 | 0 | 20 | 179 | 199 |
| O3 | 0 | 13 | 82 | 95 |
| particulate matter | 0 | 1 | 19 | 20 |
| ultrafine particles | 0 | 0 | 8 | 8 |
| PM1 | 0 | 2 | 4 | 6 |
| NO | 0 | 0 | 2 | 2 |

Polluant × significativité :
| Polluant | non_significant | significant | unknown | Total |
| --- | --- | --- | --- | --- |
| PM2.5 | 227 | 837 | 55 | 1 119 |
| PM10 | 96 | 300 | 30 | 426 |
| NO2 | 31 | 168 | 0 | 199 |
| O3 | 12 | 67 | 16 | 95 |
| particulate matter | 4 | 16 | 0 | 20 |
| ultrafine particles | 4 | 4 | 0 | 8 |
| PM1 | 0 | 6 | 0 | 6 |
| NO | 1 | 1 | 0 | 2 |

## 19. Top éléments

### Top 20 polluants extraits
| Rang | Polluant | Occurrences | Documents | % |
| --- | --- | --- | --- | --- |
| 1 | PM2.5 | 323 | 323 | 14.0 % |
| 2 | air pollution | 251 | 251 | 10.9 % |
| 3 | PM10 | 187 | 187 | 8.1 % |
| 4 | particulate matter | 163 | 163 | 7.1 % |
| 5 | NO2 | 157 | 157 | 6.8 % |
| 6 | O3 | 111 | 111 | 4.8 % |
| 7 | traffic-related pollution | 107 | 107 | 4.6 % |
| 8 | CO | 79 | 79 | 3.4 % |
| 9 | SO2 | 73 | 73 | 3.2 % |
| 10 | ambient air pollution | 72 | 72 | 3.1 % |
| 11 | black carbon | 68 | 68 | 2.9 % |
| 12 | air pollutants | 55 | 55 | 2.4 % |
| 13 | NOx | 45 | 45 | 2.0 % |
| 14 | ultrafine particles | 40 | 40 | 1.7 % |
| 15 | road proximity | 27 | 27 | 1.2 % |
| 16 | elemental carbon | 20 | 20 | 0.9 % |
| 17 | NO | 17 | 17 | 0.7 % |
| 18 | woodsmoke | 16 | 16 | 0.7 % |
| 19 | black smoke | 13 | 13 | 0.6 % |
| 20 | PM1 | 13 | 13 | 0.6 % |

### Top 20 outcomes extraits
| Rang | Outcome | Occurrences | Documents | % |
| --- | --- | --- | --- | --- |
| 1 | asthma | 69 | 47 | 3.2 % |
| 2 | mortality | 40 | 39 | 1.9 % |
| 3 | cardiovascular mortality | 38 | 32 | 1.8 % |
| 4 | cardiovascular disease | 29 | 25 | 1.4 % |
| 5 | lung cancer | 27 | 22 | 1.3 % |
| 6 | respiratory mortality | 24 | 17 | 1.1 % |
| 7 | low birth weight | 22 | 15 | 1.0 % |
| 8 | systolic blood pressure | 22 | 17 | 1.0 % |
| 9 | preterm birth | 19 | 17 | 0.9 % |
| 10 | chronic obstructive pulmonary disease | 18 | 17 | 0.8 % |
| 11 | diastolic blood pressure | 18 | 14 | 0.8 % |
| 12 | blood pressure | 17 | 17 | 0.8 % |
| 13 | all cause mortality | 16 | 14 | 0.8 % |
| 14 | ischemic heart disease | 16 | 14 | 0.8 % |
| 15 | stroke | 16 | 14 | 0.8 % |
| 16 | systolic bp | 15 | 9 | 0.7 % |
| 17 | respiratory diseases | 15 | 13 | 0.7 % |
| 18 | lung function | 14 | 13 | 0.7 % |
| 19 | respiratory symptoms | 13 | 13 | 0.6 % |
| 20 | pneumonia | 13 | 10 | 0.6 % |

### Top populations/pays
| Rang | Pays | Documents | Documents | % |
| --- | --- | --- | --- | --- |
| 1 | not_reported | 106 | 106 | 24.5 % |
| 2 | United States | 92 | 92 | 21.3 % |
| 3 | China | 32 | 32 | 7.4 % |
| 4 | Canada | 15 | 15 | 3.5 % |
| 5 | Belgium | 14 | 14 | 3.2 % |
| 6 | Taiwan | 11 | 11 | 2.5 % |
| 7 | United Kingdom | 11 | 11 | 2.5 % |
| 8 | Italy | 11 | 11 | 2.5 % |
| 9 | Netherlands | 10 | 10 | 2.3 % |
| 10 | Brazil | 9 | 9 | 2.1 % |
| 11 | India | 7 | 7 | 1.6 % |
| 12 | Spain | 6 | 6 | 1.4 % |
| 13 | Germany | 6 | 6 | 1.4 % |
| 14 | Mexico | 6 | 6 | 1.4 % |
| 15 | Japan | 6 | 6 | 1.4 % |
| 16 | South Korea | 6 | 6 | 1.4 % |
| 17 | Czech Republic | 5 | 5 | 1.2 % |
| 18 | Sweden | 5 | 5 | 1.2 % |
| 19 | Australia | 3 | 3 | 0.7 % |
| 20 | Nepal | 3 | 3 | 0.7 % |

### Top types d’effet finaux
| Rang | Type effet | Associations | Documents | % |
| --- | --- | --- | --- | --- |
| 1 | percent_change | 543 | 93 | 29.0 % |
| 2 | beta | 543 | 73 | 29.0 % |
| 3 | OR | 435 | 67 | 23.2 % |
| 4 | HR | 202 | 23 | 10.8 % |
| 5 | RR | 130 | 25 | 6.9 % |
| 6 | IRR | 22 | 2 | 1.2 % |

### Top fenêtres temporelles
| Rang | Fenêtre | Associations | Documents | % |
| --- | --- | --- | --- | --- |
| 1 | long_term | 793 | 110 | 42.3 % |
| 2 | short_term | 501 | 99 | 26.7 % |
| 3 | prenatal | 130 | 26 | 6.9 % |
| 4 | lagged | 119 | 31 | 6.3 % |
| 5 | multiple | 118 | 32 | 6.3 % |
| 6 | trimester_specific | 116 | 20 | 6.2 % |
| 7 | not_reported | 50 | 20 | 2.7 % |
| 8 | early_life | 27 | 4 | 1.4 % |
| 9 | ambiguous | 12 | 8 | 0.6 % |
| 10 | cumulative | 4 | 2 | 0.2 % |
| 11 | repeated_measure | 3 | 2 | 0.2 % |
| 12 | lifetime | 2 | 1 | 0.1 % |

## 20. Implémentation technique

| Étape | Script/module | Entrée | Sortie | Traitement |
| --- | --- | --- | --- | --- |
| Préprocessing CTD PM | `src/preprocessing/ctd_pm_human_dataset.py` | CSV CTD bruts | `ctd_pm_human/*.csv`, audit | filtre PM/humain |
| Candidats multi-polluants | `src/preprocessing/ctd_exposure_candidates.py` | CTD exposure | `ctd_exposure_candidates/*.csv` | PM, O3, NO2, NO |
| PubMed | `src/ingestion/pubmed_fetcher.py` | PMIDs | `pubmed/*_pubmed.json` | metadata/abstract |
| Full text | `src/ingestion/paperclip_fetcher.py`, `europepmc_fetcher.py` | PMIDs/PMCIDs | `paperclip/full_texts/*.txt` | Paperclip + fallback Europe PMC |
| Segmentation | `src/preprocessing/document_segmenter.py` | LLM inputs | `segmented_documents/*_segmented.json` | sections/chunks |
| Agents | `src/agents/*_extractor.py` | documents segmentés | JSON agents | LLM température 0, repair JSON |
| Association builder | `src/builders/association_builder.py` | sorties agents | associations JSON/CSV | déterministe |
| Quality control | `src/quality_control/final_cleaner.py` | associations_all | clean/rejected/audit | règles déterministes |
| Enrichissement CTD | `src/runners/build_ctd_pm_enrichment.py` | tables finales + CTD | enrichment CSV | liens outcome-specific |
| Fusion finale | `src/preprocessing/final_dataset_merge.py` | main enriched + population + time | `final/ctd_extraction_final.csv` | jointures m:1 |

## 21. Échecs et cas limites

| Cas limite / échec | Nombre | % | Traitement |
| --- | --- | --- | --- |
| PMIDs candidats PM non traités | 2 | 0.5 % | 27384219, 27633937 |
| Sans abstract PubMed/Paperclip | 1 | 0.2 % | document analysable via titre/pseudo-abstract si segmenté |
| Sans full text | 140 | 32.4 % | analyse abstract/title-only |
| Pollutant extractor vide | 6 | 1.4 % | pas de polluant extrait |
| Outcome extractor vide | 102 | 23.6 % | pas d’outcome extrait |
| Effect extractor vide | 138 | 31.9 % | pas de mesure extraite |
| Associations rejetées QC | 250 | 8.3 % | exposition non air pollution, ambiguïtés, etc. |
| Review QC | 93 | 3.1 % | gardé hors main analysis |

## 22. Traçabilité des données

Chaque ligne finale peut être tracée par `pmid` et `association_id`. Le chemin est : PMID CTD exposure → fichier PubMed/Paperclip → document segmenté → sorties agents JSON avec `evidence_sentence` → association builder → QC (`qc_reasons`) → enrichissement CTD (`outcome_key`, disease/phenotype mapping, gene links) → fusion finale. Les fichiers détaillés conservés incluent les réponses brutes LLM, les fichiers de reasoning, les JSON d’état et les CSV/audits de chaque étape.

## 23. Performance technique

**Statistique non disponible dans les artefacts actuels** pour le temps total complet, le temps moyen par article, le nombre exact d’appels API/LLM, la consommation de tokens et les coûts. Les logs existent par runner, mais ils ne contiennent pas un schéma consolidé de durées/tokens/coûts. Pour calculer ces métriques à l’avenir, il faudrait enregistrer systématiquement `started_at`, `finished_at`, `duration_seconds`, `model`, `prompt_tokens`, `completion_tokens`, `cost` par appel et par PMID.

Métriques disponibles : réparations JSON agents : pollutant **5**, outcome **4**, effect **6**. Chunks traités par agent principal : **3744**.

## 24. Chiffres clés à retenir pour la présentation
- 434 PMIDs PM candidats CTD ; 432 traités (99.5 %).
- 431 / 432 documents ont un abstract PubMed/Paperclip (99.8 %).
- 292 / 432 documents ont un full text exploitable (67.6 %).
- 2 306 polluants, 2 125 outcomes et 3 409 mesures d’effet ont été extraits par les agents.
- 3 003 associations candidates ont été construites ; 1 875 passent en main analysis (62.4 %).
- Le dataset final contient 1 875 lignes : une ligne = une relation exposition-santé finale.
- 1 579 associations finales sont PM/D052638 et éligibles à l’enrichissement mécanistique CTD.
- 76 / 421 outcomes PM uniques matchent une disease CTD acceptée.
- 36 / 421 outcomes PM uniques matchent un phenotype CTD accepté.
- L’enrichissement outcome-specific produit 13 502 liens association-gène couvrant 339 associations PM.

## 25. Statistiques directement réutilisables dans les slides
### Slide — Acquisition des données
- 434 PMIDs PM candidats CTD
- 432 PMIDs traités
- 2 PMIDs candidats non traités

### Slide — Couverture abstract/full text
- 431 abstracts stricts (99.8 %)
- 292 full texts (67.6 %)
- 140 documents abstract/title-only

### Slide — Extraction
- 2 306 polluants
- 2 125 outcomes
- 3 409 mesures
- 3 183 mesures gardées pour builder

### Slide — Polluants
- 726 mentions PM/particules
- 1 011 polluants cibles projet
- 1 875 associations finales dont 1 579 PM

### Slide — Associations
- 3 003 candidates
- 2 753 clean database
- 1 875 finales main analysis
- 737 contextuelles

### Slide — Qualité
- 2 660 accept
- 93 review
- 250 reject

### Slide — Enrichissement
- 1 579 associations PM enrichissables
- 315 800 liens PM-level
- 13 502 liens gene outcome-specific

### Slide — Dataset final
- 1 875 lignes
- 113 colonnes
- 1 ligne = 1 association finale

## 26. Tableau exhaustif des KPI

| Catégorie | KPI | Valeur | Dénominateur | Pourcentage | Source/calcul |
| --- | --- | --- | --- | --- | --- |
| Acquisition | PMIDs PM candidats CTD uniques | 434 | 434 | 100.0 % | ctd_pm_human/exposure_pm_candidates.csv |
| Acquisition | PMIDs traités | 432 | 434 | 99.5 % | paperclip manifest |
| Acquisition | PMIDs candidats PM non traités | 2 | 434 | 0.5 % | différence candidats PM - manifest |
| Documentation | Abstracts PubMed/Paperclip disponibles | 431 | 432 | 99.8 % | paperclip manifest |
| Documentation | Full texts disponibles | 292 | 432 | 67.6 % | paperclip manifest |
| Documentation | PMC IDs disponibles | 356 | 432 | 82.4 % | paperclip manifest |
| Agents | Polluants extraits canoniques | 2 306 | — | — | agent_outputs/pollutant_extractor |
| Agents | Outcomes extraits canoniques | 2 125 | — | — | agent_outputs/outcome_extractor |
| Agents | Mesures extraites canoniques | 3 409 | — | — | agent_outputs/effect_measure_extractor |
| Agents | Mesures gardées pour association builder | 3 183 | 3 409 | 93.4 % | keep_for_association_builder |
| Associations | Associations candidates construites | 3 003 | — | — | associations_all_test.csv |
| Qualité | Associations acceptées QC | 2 660 | 3 003 | 88.6 % | qc audit |
| Qualité | Associations review QC | 93 | 3 003 | 3.1 % | qc audit |
| Qualité | Associations rejetées QC | 250 | 3 003 | 8.3 % | qc audit |
| Final | Associations finales main analysis | 1 875 | 3 003 | 62.4 % | final_tables/01 |
| Final | Dataset final lignes | 1 875 | 1 875 | 100.0 % | final/ctd_extraction_final.csv |
| Enrichissement | Associations PM enrichissables | 1 579 | 1 875 | 84.2 % | enrichment audit |
| Enrichissement | Liens gène PM-level top | 315 800 | — | — | association_pm_gene_links_top.csv |
| Enrichissement | Liens gène outcome-specific | 13 502 | — | — | association_pm_gene_links_outcome_specific.csv |
| Enrichissement | Associations avec gènes outcome-specific | 339 | 1 579 | 21.5 % | enrichment audit |

## 27. Conclusion générale

Le pipeline transforme un corpus CTD PM de **434 PMIDs candidats** en un dataset final consolidé de **1 875 relations exposition-santé quantifiées**. Il combine récupération documentaire, agents LLM spécialisés, association builder déterministe, contrôle qualité strict et enrichissement CTD. La couverture documentaire est forte pour les abstracts (**431 / 432**) et partielle mais substantielle pour les full texts (**292 / 432**). Le QC réduit **3 003 associations candidates** à **1 875 associations finales** utilisables en analyse principale. L’enrichissement sépare les gènes PM-level des liens gène outcome-specific : le premier niveau fournit un contexte général, le second produit **13 502 liens plus défendables** via les réseaux CTD disease/phenotype correspondant aux outcomes extraits.

Limites principales : deux PMIDs PM candidats ne sont pas dans les artefacts traités ; les métriques de temps, tokens et coûts ne sont pas consolidées ; la taille d’échantillon des études n’est pas structurée ; les mappings CTD restent dépendants de la qualité de normalisation des outcomes.

## 28. Résumé ultra-court pour l’oral
1. 434 PMIDs PM candidats CTD ; 432 traités (99.5 %).
2. 431 / 432 documents ont un abstract PubMed/Paperclip (99.8 %).
3. 292 / 432 documents ont un full text exploitable (67.6 %).
4. 2 306 polluants, 2 125 outcomes et 3 409 mesures d’effet ont été extraits par les agents.
5. 3 003 associations candidates ont été construites ; 1 875 passent en main analysis (62.4 %).
6. Le dataset final contient 1 875 lignes : une ligne = une relation exposition-santé finale.
7. 1 579 associations finales sont PM/D052638 et éligibles à l’enrichissement mécanistique CTD.
8. 76 / 421 outcomes PM uniques matchent une disease CTD acceptée.
9. 36 / 421 outcomes PM uniques matchent un phenotype CTD accepté.
10. L’enrichissement outcome-specific produit 13 502 liens association-gène couvrant 339 associations PM.
11. Le terme “association” signifie ici une relation exposition-santé quantifiée, pas une preuve causale directe.
12. Les gènes outcome-specific ne sont ajoutés que lorsque l’outcome extrait matche une disease ou un phenotype CTD accepté.

## Annexe — Inventaire des statistiques calculées

### Inventaire des fichiers principaux
| Fichier | Lignes | Format |
| --- | --- | --- |
| data/processed/paperclip/documents_manifest_test_with_paperclip.csv | 432 | CSV |
| data/processed/segmented_documents/segmented_documents_manifest_test.csv | 432 | CSV |
| data/processed/agent_outputs/multi_pmid_runner/associations_all_test.csv | 3 003 | CSV |
| data/processed/agent_outputs/final_quality_control/associations_clean_test.csv | 2 753 | CSV |
| data/processed/agent_outputs/final_quality_control/associations_rejected_test.csv | 250 | CSV |
| data/processed/final_tables/01_main_associations_analysis.csv | 1 875 | CSV |
| data/processed/enrichment/main_associations_enriched.csv | 1 875 | CSV |
| data/processed/enrichment/association_pm_gene_links_outcome_specific.csv | 13 502 | CSV |
| data/processed/final/ctd_extraction_final.csv | 1 875 | CSV |

### Top raisons QC complètes
| Rang | Raison | Occurrences | % |
| --- | --- | --- | --- |
| 1 | covariate_or_non_pollutant_effect | 135 | 26.3 % |
| 2 | valid_percent_change_effect_estimate_without_ci_or_p | 130 | 25.3 % |
| 3 | non_air_pollution_exposure | 115 | 22.4 % |
| 4 | ambiguous_or_non_target_exposure | 93 | 18.1 % |
| 5 | subgroup_analysis_detected | 13 | 2.5 % |
| 6 | result_context=subgroup_analysis | 13 | 2.5 % |
| 7 | valid_direct_effect_estimate_without_ci_or_p | 9 | 1.8 % |
| 8 | sensitivity_analysis_detected | 2 | 0.4 % |
| 9 | result_context=sensitivity_analysis | 2 | 0.4 % |
| 10 | concentration_response_detected | 1 | 0.2 % |
| 11 | result_context=concentration_response | 1 | 0.2 % |

### Top unités effect extractor
| Rang | Unité | Occurrences | % |
| --- | --- | --- | --- |
| 1 | μg/m3 | 719 | 48.2 % |
| 2 | µg/m3 | 455 | 30.5 % |
| 3 | microg/m3 | 82 | 5.5 % |
| 4 | ppb | 75 | 5.0 % |
| 5 | ng/m3 | 32 | 2.1 % |
| 6 | 0 | 26 | 1.7 % |
| 7 | SD | 24 | 1.6 % |
| 8 | μg/kg | 14 | 0.9 % |
| 9 | ppm | 11 | 0.7 % |
| 10 | unit | 9 | 0.6 % |
| 11 | pphm | 6 | 0.4 % |
| 12 | microm2 | 5 | 0.3 % |
| 13 | dB | 5 | 0.3 % |
| 14 | µg/m | 5 | 0.3 % |
| 15 | year | 4 | 0.3 % |
| 16 | mg/m3 | 3 | 0.2 % |
| 17 | μg.m | 3 | 0.2 % |
| 18 | hr | 2 | 0.1 % |
| 19 | microg | 2 | 0.1 % |
| 20 | μg | 2 | 0.1 % |
| 21 | th | 2 | 0.1 % |
| 22 | micro | 1 | 0.1 % |
| 23 | μm2 | 1 | 0.1 % |
| 24 | minute | 1 | 0.1 % |
| 25 | d | 1 | 0.1 % |
| 26 | A | 1 | 0.1 % |

### Top polluant-outcome final
| Rang | Polluant | Outcome | Associations | % |
| --- | --- | --- | --- | --- |
| 1 | PM2.5 | lung cancer | 37 | 2.0 % |
| 2 | PM2.5 | asthma | 29 | 1.5 % |
| 3 | PM2.5 | cardiovascular mortality | 27 | 1.4 % |
| 4 | PM2.5 | peak expiratory flow | 27 | 1.4 % |
| 5 | PM2.5 | mortality | 26 | 1.4 % |
| 6 | PM10 | asthma | 23 | 1.2 % |
| 7 | PM10 | childhood leukemia | 23 | 1.2 % |
| 8 | PM2.5 | under five deaths | 22 | 1.2 % |
| 9 | PM2.5 | anosmia | 22 | 1.2 % |
| 10 | PM2.5 | maternal deaths | 19 | 1.0 % |
| 11 | PM2.5 | intrauterine inflammation | 17 | 0.9 % |
| 12 | PM2.5 | st segment height | 15 | 0.8 % |
| 13 | PM10 | systolic blood pressure | 15 | 0.8 % |
| 14 | PM10 | diastolic blood pressure | 15 | 0.8 % |
| 15 | PM10 | preterm birth | 15 | 0.8 % |
| 16 | PM2.5 | impaired fasting glucose | 15 | 0.8 % |
| 17 | PM2.5 | all cause mortality | 14 | 0.7 % |
| 18 | PM2.5 | ischemic heart disease mortality | 14 | 0.7 % |
| 19 | PM2.5 | right ventricular mass | 13 | 0.7 % |
| 20 | PM2.5 | incident stroke | 13 | 0.7 % |
