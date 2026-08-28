# Dictionnaire de données

Ce document décrit chaque fichier de sortie produit par le pipeline, colonne
par colonne. Tous les fichiers sont des CSV (compressés `.csv.gz` par défaut,
`--plain-csv` pour du CSV brut) afin de pouvoir être ouverts directement dans
un tableur ou chargés dans pandas pour l'analyse du mémoire.

Convention générale : `individual_id` et `persona_id` figurent dans tous les
fichiers pour la traçabilité et la reconstruction de séquences, mais ne
doivent jamais être utilisés comme variable d'entrée d'un modèle prédictif
(voir `docs/PIPELINE.md`, section parité train/inférence).

---

## Étape 1 — `household_concentrations.csv(.gz)`

Une ligne par logement × créneau de 15 minutes. Grain le plus fin du pipeline.

| Colonne | Type | Description |
|---|---|---|
| `household_id` | str | Identifiant du logement (H01 à H12) |
| `timestamp` | str ISO | Date-heure du créneau |
| `date` | str | Date (AAAA-MM-JJ) |
| `year` | int | Année |
| `day_type` | str | `semaine` / `weekend` (bascule vendredi 18h → dimanche 18h, date réelle) |
| `slot_15min` | int | Créneau dans la journée, 0 à 95 |
| `emission_scenario` | str | `clean` / `cooking` / `tobacco` / `biomass_extreme` |
| `pm25_indoor`, `pm10_indoor` | float | Concentration intérieure du logement (µg/m³) |
| `background_pm25` | float | Composante de fond (avant émissions ponctuelles) |
| `cooking_increment_pm25`, `tobacco_increment_pm25`, `biomass_increment_pm25` | float | Contribution de chaque source, décroissance exponentielle incluse |
| `pm10_mode` | str | Mode de dérivation du PM10 (`legacy_fixed` actuellement) |
| `pm10_ratio` | float | Ratio PM10/PM2.5 appliqué (1.53) |
| `parameter_status` | str | Statut de provenance du paramètre logement |

## Étape 1 — `individual_exposures.csv(.gz)`

Une ligne par individu × créneau de 15 minutes.

| Colonne | Type | Description |
|---|---|---|
| `individual_id`, `persona_id`, `household_id` | str | Identifiants — traçabilité uniquement, jamais feature |
| `timestamp`, `date`, `year` | — | Comme ci-dessus |
| `age` | int | Âge de l'individu à cette date |
| `sex` | str | `Homme` / `Femme` |
| `room` | str | Pièce occupée (`sejour`, `chambre`, `cuisine`, `sdb`, `absent`) |
| `is_home` | 0/1 | Présence effective au domicile |
| `presence_template`, `work_status`, `smoking_status` | str | Profil comportemental |
| `pregnancy_phase`, `gestational_week` | str, int\| | Phase de grossesse si applicable (persona P3) |
| `baseline_asthma`, `baseline_hypertension` | 0/1 | État de santé initial |
| `asthma_rule_id`, `hypertension_rule_id` | str | Traçabilité de la règle p0 ayant fixé l'état initial |
| `pm25_indoor`, `pm10_indoor` | float | Concentration du logement à ce créneau |
| `pm25_residential_exposure`, `pm10_residential_exposure` | float | Exposition réelle — **0 si absent**, sinon = concentration du logement |

## Étape 1 — `household_events.csv(.gz)`

Un événement domestique par ligne (cuisson, cigarette, combustion).

| Colonne | Description |
|---|---|
| `event_id` | Identifiant unique |
| `household_id`, `event_date` | Logement et date |
| `source_type` | `cooking_*`, `tobacco_cigarette`, `biomass_heating_extreme` |
| `start_slot`, `peak_slot` | Créneaux de montée et de pic |
| `peak_increment_pm25` | Amplitude tirée pour cet événement |
| `evidence_status`, `scientific_note` | Traçabilité de la source du paramètre |

## Étape 1 — `daily_household_summary.csv`, `annual_household_summary.csv`

Agrégats journaliers et annuels par logement — moyenne, maximum, dépassement
des seuils OMS 2021, nombre d'événements. Utile pour un contrôle visuel
rapide, remplacé pour l'analyse fine par les fichiers de l'étape 4-6.

## Étape 1 — `initial_health_states.csv`

Un état de santé initial par individu (asthme, hypertension), avec la règle
p0 ayant servi à le tirer. Produit une seule fois, ne dépend pas du temps.

---

## Étape 2 — `ctd_icd_mapped_complete.csv`

Le fichier CTD brut, enrichi des colonnes de mapping ICD-10. Une ligne par
association source ; le nombre de lignes est identique au fichier d'entrée.

Colonnes ajoutées par le mapping (voir aussi `docs/reference/icd_outcome_audit_544.csv`
pour l'audit complet des 544 outcomes PM2.5/PM10 distincts) :

| Colonne | Description |
|---|---|
| `mapping_status` | `VALIDATED_ICD` / `VALIDATED_NON_ICD` / `VALIDATED_EXCLUDED` / `UNMAPPED_REVIEW` |
| `icd_chapter`, `icd_chapter_name` | Chapitre ICD-10 (OMS, release 2019) |
| `icd_code`, `icd_title` | Code précis si la règle en fournit un (sinon vide, mapping au niveau chapitre) |
| `mapping_level` | `chapter` / `code` / `multi_chapter` |
| `mapping_rule_id` | Règle exacte appliquée (traçable dans `config/icd_mapping_reference.csv`) |
| `mapping_confidence`, `mapping_rationale` | Confiance et justification de la règle |
| `eligible_for_icd` | `true`/`false` |
| `outcome_mapping_key` | Clé canonique (normalisation lexicale, casse et accents neutralisés) |

## Étape 2 — `mapping_quality_report.csv`, `mapping_unresolved.csv`, `mapping_conflicts.csv`

Contrôle qualité du mapping : comptages par statut et par chapitre,
lignes non résolues (attendu : 0), conflits de règles (attendu : 0).

---

## Étape 3 — `individual_p0_schedule.csv`

Une ligne par individu × année × événement de santé applicable.

| Colonne | Description |
|---|---|
| `individual_id`, `persona_id`, `calendar_year`, `age`, `sex` | Contexte |
| `event_id`, `event_name` | Événement sanitaire (E01 asthme baseline, E02 asthme, E03 cardiopathie, E04 AVC, E05 prématurité, E08 pré-éclampsie) |
| `p0_value` | Probabilité de base appliquée |
| `rule_id`, `condition`, `scenario` | Traçabilité de la règle p0 |
| `evidence_status`, `source`, `scientific_note` | Provenance scientifique |

> `E06` (faible poids) et `E07` (petit poids gestationnel) sont définis dans
> `config/p0_reference.csv` mais ne sont pas encore émis par ce script — voir
> `docs/DECISIONS_LOG.md`.

---

## Étape 4 — `exposure_windows.csv(.gz)`

Une ligne par individu × polluant × fenêtre (24h **ou** annuelle).

| Colonne | Description |
|---|---|
| `bag_id` | Clé unique de la fenêtre — sert de jointure avec les étapes 5, 6, 7 |
| `window_type` | `daily` (24h) ou `annual` |
| `window_start`, `window_end`, `year`, `date` | Bornes temporelles |
| `valid_slots`, `home_slots`, `home_minutes` | Créneaux disponibles / créneaux de présence effective |
| `mean_exposure`, `home_mean_exposure`, `max_exposure`, `sum_exposure` | Statistiques de la fenêtre, calculées sur les créneaux de présence uniquement |

## Étape 5 — `exposure_thresholds.csv(.gz)`

Une ligne par fenêtre (même grain que l'étape 4), enrichie des trois méthodes
de détection.

| Colonne | Description |
|---|---|
| `mean_threshold_value`, `max_threshold_value`, `mil_threshold_value` | Seuil OMS 2021 applicable (identique pour les trois méthodes sur une même fenêtre) |
| `mean_exceedance`, `max_exceedance`, `mil_exceedance` | 0/1 par méthode |
| `proportion_above_threshold` | Proportion de créneaux de présence au-dessus du seuil — base du calcul MIL |
| `mil_min_proportion` | Paramètre de calibration MIL utilisé (0.05 par défaut) |
| `excess_mean`, `excess_max` | Écart positif moyenne/maximum au-dessus du seuil |
| `excess_burden` | Somme des excès horaires pondérés — base de `cumulative_excess_burden` à l'étape 6 |

## Étape 6 — `exposure_trajectory.csv(.gz)` *(nouveau)*

Une ligne par fenêtre, dans le même ordre que l'étape 5, enrichie de
l'historique du flux (individu × polluant × échelle) jusqu'à cette fenêtre.
**Ces colonnes ne dépendent d'aucune catégorie ICD** — calculées une seule
fois par flux physique.

| Colonne | Description |
|---|---|
| `window_index` | Position de la fenêtre dans la séquence chronologique du flux (0, 1, 2…) |
| `cumulative_exposure` | Somme de `sum_exposure` depuis la première fenêtre — jamais décroissante |
| `cumulative_excess_burden` | Somme de `excess_burden` depuis le début — jamais décroissante |
| `consecutive_exceedances` | Fenêtres MIL-positives consécutives menant à la fenêtre courante — remis à 0 dès qu'une fenêtre repasse sous le seuil |
| `max_consecutive_exceedances_to_date` | Le plus long épisode consécutif observé jusqu'ici — ne redescend jamais |
| `exposure_slope_7j` | Pente sur 7 fenêtres glissantes — **fenêtres `daily` uniquement** |
| `exposure_trend_direction` | `hausse` / `stable` / `baisse` / `insuffisant` sur les 3 dernières fenêtres — **fenêtres `annual` uniquement** |

## Étape 7 — `exposure_health_model_dataset.csv(.gz)`

Le fichier final. Une ligne par fenêtre × catégorie ICD candidate (positive
documentée par CTD, ou `unknown_sampled_negative` échantillonnée).

### Composition du quadruplet (s, r, o, t)

| Composant | Colonnes | Utilisable comme feature ? |
|---|---|---|
| **s** — sujet | `classe_age`, `grossesse`, `pathologie_preexistante` (Famille B) + toutes les colonnes `mean_/max_/sum_/cumulative_/consecutive_/exposure_slope_/exposure_trend_` (Famille A) | **Oui** |
| **r** — relation | `window_type` (`daily` → aigu, `annual` → chronique) | Structurel |
| **o** — objet, cible à prédire | `icd_chapter`, `icd_chapter_name` | Cible, pas feature |
| **t** — temps | `window_start`, `window_end`, `year`, `date` | Oui (hors identifiant) |

### Colonnes Famille B — profil généralisé

| Colonne | Valeurs | Dérivation |
|---|---|---|
| `classe_age` | `enfant` / `adulte` / `senior` | Depuis `persona_id` (P1→enfant, P4→senior, sinon adulte) |
| `grossesse` | `oui` / `non` | `oui` seulement si la date de la fenêtre tombe dans `[pregnancy_start, expected_delivery_date]` de l'individu (persona P3) |
| `pathologie_preexistante` | `aucune` / `respiratoire` / `cardiovasculaire` | Depuis `persona_id` (P5→respiratoire, P4→cardiovasculaire, sinon aucune) |

### Colonnes de traçabilité — jamais en feature d'entrée

| Colonne | Pourquoi l'exclure |
|---|---|
| `individual_id`, `persona_id` | Identité non réutilisable pour un cas réel (parité train/inférence) |
| `link_label` | La cible que le modèle apprend à prédire indirectement via `icd_chapter` — pas une feature |
| `health_score`, `association_strength`, `evidence_weight` | **Fuite de cible** : valent exactement 0 pour toute ligne `unknown_sampled_negative`, par construction. Un modèle qui les recevrait en entrée apprendrait à reconnaître ce zéro plutôt qu'un signal d'exposition réel. |
| `window_evidence` | `direct_window` / `unspecified_window` / `unknown_sampled_negative` — révèle indirectement `link_label` |
| `p0_event_ids`, `p0_value_max`, `p0_relevance`, `persona_relevance` | Dérivées de `individual_id`/`persona_id`, mêmes réserves |

### Autres colonnes

| Colonne | Description |
|---|---|
| `association_beta_mean` | Coefficient β **signé** (ln de l'OR/RR/HR, ou de 1+%/100, par incrément de concentration) — signe conservé, jamais valeur absolue |
| `effect_measure_count`, `association_count`, `pmid_count`, `outcome_count` | Robustesse de la preuve CTD pour ce couple (polluant, chapitre) |
| `exposure_signal` | Combinaison pondérée moyenne/max/MIL de la fenêtre — poids non calibrés empiriquement, voir `docs/DECISIONS_LOG.md` |

---

## Fichiers de contrôle qualité

- `quality_report.json` (étape 1) — comptages attendus vs observés, avertissements de provenance.
- `post_validation_report.json` (`validate_outputs.py`) — vérifie l'absence d'exposition résiduelle quand `is_home=0`, la cohérence du ratio PM10/PM2.5, l'unicité de la concentration partagée par logement.
