# Journal des décisions — réorganisation du pipeline

Ce document trace précisément ce qui a changé entre le code livré initialement
et cette version unifiée, et pourquoi. Chaque ligne est vérifiable dans
l'historique des fichiers.

## 1. Intégration du sous-projet ICD-11

**Avant.** `icd_mapping_final_2026_01.zip` était un sous-projet Python complet
et séparé (son propre `src/`, ses propres tests, son propre README), livré
comme une archive à part, avec un fichier `ctd_icd_mapped_complete.csv` déjà
produit copié manuellement dans `config/` du pipeline principal.

**Après.** `stage_bph.icd_mapping` est un sous-module normal du package
unique. `config/icd_mapping_reference.csv` (545 règles) est la seule donnée de
référence nécessaire. `scripts/02_map_ctd_to_icd.py` régénère
`ctd_icd_mapped_complete.csv` à la demande — plus de copie manuelle d'un
fichier déjà calculé ailleurs.

**Ce qui n'a pas été repris.** Le README et le SCIENTIFIC_METHOD.md du
sous-projet (contenu fusionné dans `docs/PIPELINE.md`), le fichier
`audit_mapping_ICD11_MMS_2026_01.xlsx` (audit binaire redondant avec
`docs/reference/icd_outcome_audit_544.csv`, qui contient la même information
en CSV directement analysable), et le dossier `outputs/` du sous-projet
(régénérable).

## 2. Correction du bug d'import

**Avant.** `scripts/exposure_windows.py` contenait `from
..src.stage_bph.config import ProjectConfig` — un import relatif cassé, qui
levait `ImportError: attempted relative import beyond top-level package` dès
qu'on lançait le script normalement. Un script de contournement
(`run_exposure_postprocess_workaround.sh`, ~90 lignes) bricolait de faux
modules Python en mémoire pour forcer l'import à fonctionner.

**Après.** La logique vit dans `src/stage_bph/exposure_windows.py` avec des
imports absolus (`from .config import ProjectConfig`). Testé par exécution
réelle — fonctionne sans contournement. `run_exposure_postprocess_workaround.sh`
supprimé.

## 3. Ajout de la couche de trajectoire (chapitre 3, étage 2)

**Avant.** Absente. Les fichiers `exposure_windows.csv` et
`exposure_thresholds.csv` ne contenaient que des statistiques par fenêtre
isolée — aucune mémoire de l'historique d'un individu.

**Après.** `src/stage_bph/exposure_trajectory.py` (nouveau module), exécuté à
l'étape 6. Calcule `window_index`, `cumulative_exposure`,
`cumulative_excess_burden`, `consecutive_exceedances`,
`max_consecutive_exceedances_to_date`, `exposure_slope_7j`,
`exposure_trend_direction`. Testé (`tests/test_exposure_trajectory.py`) :
monotonie du cumul vérifiée, remise à zéro et record du compteur vérifiés.

## 4. Correction de la fuite de cible (chapitre 4)

**Avant.** Pour toute ligne `link_label = 0`, `association_strength = 0.0`,
`evidence_weight = 0.0`, donc `health_score = 0.0` par construction. Le score
révélait directement l'étiquette.

**Après.** Le mécanisme de calcul n'a pas changé (il reste vrai que ces
métadonnées valent 0 pour les négatifs — c'est inhérent à leur définition).
Ce qui change : un avertissement explicite en tête de fichier
(`exposure_health_dataset.py`) interdit leur usage comme feature, et un test
dédié (`test_negative_rows_are_zeroed_and_labelled`) documente ce
comportement plutôt que de le laisser implicite. La correction réelle est en
amont, dans la définition du sujet `s` du modèle (point 6 ci-dessous).

## 5. Renommage des négatifs

**Avant.** `window_evidence = "negative_sample"` — implique une preuve
d'absence d'association.

**Après.** `window_evidence = "unknown_sampled_negative"` — absence
d'observation dans le corpus consulté, hypothèse de monde ouvert. Le
mécanisme de tirage (uniforme, sans remplacement, graine déterministe) n'a
pas changé, seule l'interprétation documentée.

## 6. Définition explicite du sujet `s` — Familles A et B

**Avant.** Aucune composition formelle de `s`. Le dataset mélangeait
identité (`individual_id`), profil implicite (`persona_id` brut), niveau de
fenêtre, et métadonnées de preuve dans une seule liste de colonnes sans
distinction d'usage.

**Après.**
- Famille A (trajectoire, chapitre 3) : colonnes déjà présentes + les 7
  nouvelles colonnes de trajectoire.
- Famille B (profil généralisé, chapitre 2) : `classe_age`, `grossesse`,
  `pathologie_preexistante`, dérivées de `persona_id` et de la fenêtre par
  `derive_profile()` — jamais de `individual_id` brut.
- `individual_id`/`persona_id` restent dans le fichier pour la traçabilité,
  documentés comme exclus de toute feature d'entrée.

## 7. Suppression d'entrées orphelines

**`EVENT_TO_CHAPTER["E06"]`, `EVENT_TO_CHAPTER["E07"]`** (chapitre 4) — ces
deux entrées mappaient les événements « faible poids de naissance » et
« petit poids pour l'âge gestationnel » vers un chapitre ICD, mais
`p0_schedule.generate_p0_schedule()` n'émet jamais ces `event_id` — seuls E05
(prématurité) et E08 (pré-éclampsie) sont produits pour le persona P3. Retrait
des deux entrées orphelines avec commentaire ; à réintroduire seulement après
avoir ajouté leur génération dans `p0_schedule.py`.

## 8. Suppression de fichiers legacy

**`scripts/export_dataset_final.py`** — produisait un CSV à plat avec des
noms de colonnes français hérités d'une convention de nommage antérieure
(`individu_id`, `type_presence`, `profil_emission`...), incompatible avec la
convention anglaise `snake_case` utilisée partout ailleurs
(`individual_id`, `persona_id`...). Ne s'intégrait à aucune étape du chapitre
3 ou 4 actuel. Retiré.

**`scripts/run_exposure_postprocess_workaround.sh`** — plus nécessaire, voir
point 2.

**`outputs/`** (contenu généré) — jamais versionné, exclu par `.gitignore`,
non inclus dans la livraison du code.

## 9. Ce qui n'a pas changé

La simulation résidentielle (`generator.py`, `emissions.py`, `presence.py`),
le calcul du jour semaine/week-end sur date réelle (`calendar_utils.py`), la
sélection du risque de base p0 (`p0.py`), les trois méthodes de détection
Moyenne/Maximum/MIL (`exposure_windows.py`) — tous vérifiés par exécution
réelle sans modification de leur logique interne.

## 10. Limites connues, non corrigées dans cette réorganisation

- Les poids de `exposure_signal` (0,50/0,30/0,20) et `evidence_weight`
  (0,65/0,35) restent choisis a priori, sans calibration empirique.
- `exposure_slope_7j` sur les toutes premières fenêtres d'un flux (moins de
  7 disponibles) utilise la fenêtre glissante partielle disponible plutôt que
  d'attendre 7 fenêtres pleines — comportement à valider selon l'usage réel
  du modèle.
- Le graphe à deux relations (`may_affect_aigu`/`may_affect_chronique`) n'est
  pas encore matérialisé dans un format quadruplet exportable — `window_type`
  en tient lieu pour l'instant dans `exposure_health_model_dataset.csv`.

## 11. Retrait d'ICD-11 : mapping direct CTD -> ICD-10

Décision prise après vérification empirique que l'API OMS ne propose aucun
endpoint de recherche libre par mot-clé pour ICD-10 (seul un lookup par code
déjà connu fonctionne). La curation manuelle des 545 règles de
`config/icd_mapping_reference.csv` est conservée intégralement (aucune
règle re-décidée) ; seule la CIBLE change, d'ICD-11 vers ICD-10, via une
traduction outil, tracée ligne par ligne dans
`docs/reference/outcome_to_icd10_mapping_report.csv`.

Deux sources officielles OMS utilisées pour la traduction :
- `mapping/11To10MapToOneCategory.txt` (17 944 lignes, correspondance
  code-à-code, release 2026-01) pour les 23 règles à code ICD-11 précis :
  100% résolues, correspondance unique pour chacune.
- `config/icd10_chapter_correspondence.csv` (pont chapitre, déjà vérifié
  contre le fichier officiel OMS `10To11MapToMultipleCategories`) pour les
  197+2 règles chapitre-seul : fiabilité moyenne pondérée mesurée à 94,4%,
  avec 4 chapitres sous 90% signalés (21 : 58,5% ; 08→06 partiel : 76,4% ;
  14 : 80,6% ; 01 : 84,5%).

Cas particulier corrigé manuellement : l'AVC (event E04) est classé
"maladies du système nerveux" en ICD-11 mais "maladies de l'appareil
circulatoire" (I60-I64) en ICD-10 — vérifié directement sur la table
ICD-10 officielle crawlée depuis l'API OMS. Une traduction 1:1 naïve du
chapitre aurait été fausse sur ce point précis ; corrigé dans
`EVENT_TO_CHAPTER` (src/stage_bph/exposure_health_dataset.py).

Numérotation des chapitres ICD-10 : chiffres romains (I-XXII) convertis en
position numérique à 2 chiffres (I=01 ... XXII=22, cf.
`config/icd10_chapter_numbering.csv`) pour ne pas casser le code aval qui
traite `icd_chapter` comme une chaîne numérique (`mechanistic_subgraph.py`,
`exposure_health_dataset.py`, `.zfill(2)`).

Fichier CTD renommé : `ctd_temporal.csv` -> `ctd_extraction.csv` (nouvelle
extraction, 1 875 lignes contre 98 688 pour l'ancienne). Constat après
ré-exécution du mapping sur ce nouveau fichier : 676 lignes PM sur 1 545
(43,7%) restent `UNMAPPED_REVIEW` — 259 libellés d'outcome distincts non
couverts par les 545 règles existantes (ex. "under-five deaths", "ischemic
stroke", "ST-segment height"). Ce n'est pas un effet du passage à ICD-10 :
les 545 règles ont été curées sur l'ancien fichier `ctd_temporal.csv` et
n'ont jamais été étendues pour couvrir les libellés propres à la nouvelle
extraction. Reste à traiter : extension de `icd_mapping_reference.csv`
pour ces 259 libellés, hors périmètre de cette session.

Suppression : `src/stage_bph/icd_mapping/icd10_bridge.py` (pont
chapitre-seul devenu inutile, la référence cible ICD-10 directement).
Archivage sans réécriture : `docs/reference/archive/icd_outcome_audit_544_original_icd11.csv`
(audit manuel original du 2026-07-21, jamais consommé par le code,
conservé tel quel comme trace historique plutôt que falsifié).
