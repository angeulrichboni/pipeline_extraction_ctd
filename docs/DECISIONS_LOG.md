# Principes scientifiques et décisions d’architecture

## Périmètre

Le pipeline produit des associations entre expositions atmosphériques et
effets sanitaires à partir de CTD et de publications biomédicales. Le dataset
final rassemble les éléments nécessaires à l’audit de chaque relation : PMID,
polluant, outcome, mesure d’effet, population, localisation, temporalité et
preuves textuelles.

## Séparation du code et des données

Le code, les tests, la documentation et le référentiel ICD-10 sont versionnés.
Les exports CTD, textes récupérés, réponses LLM et résultats calculés sont
stockés dans `data/` et exclus de Git. `CTD_DATA_ROOT` permet de placer les
résultats sur une autre racine sans modifier le code.

## Extraction par segments

Les documents sont segmentés avant l’appel aux extracteurs. Chaque segment est
traité séparément, puis les réponses sont fusionnées, normalisées et
dédupliquées par des règles Python déterministes. Cette organisation conserve
les preuves réparties dans le document et évite qu’un appel de synthèse modifie
les valeurs extraites.

## Construction des associations

Une association relie un polluant, un outcome et une mesure d’effet provenant
d’une même publication. Deux estimations numériques différentes restent deux
associations distinctes. La fusion multi-PMID ne réalise aucun pooling
statistique.

## Contrôle qualité

Le LLM produit des objets structurés et leurs preuves textuelles. La décision
`accept`, `review` ou `reject` est calculée par le code à partir de règles
explicites portant sur la mesure, l’exposition, l’outcome et le contexte du
résultat.

Les lignes `review` et `reject` sont conservées dans des tables séparées afin
de rendre les exclusions auditables.

## Mapping ICD-10

Le mapping utilise `config/icd_mapping_reference.csv`, ciblé sur l’ICD-10 OMS
release 2019. Une règle spécifique au PMID est prioritaire sur une règle
générale. Aucune correspondance lexicale n’est créée lorsqu’aucune règle
validée n’existe.

Le référentiel distingue :

- les maladies et familles pathologiques codables ;
- les mesures physiologiques ou biomarqueurs non codables comme maladie ;
- les événements trop généraux explicitement exclus ;
- les outcomes qui nécessitent une revue.

Chaque règle conserve son niveau de mapping, son statut de validation, sa
confiance, sa justification et ses sources.

## Organisation des résultats

Toutes les productions sont regroupées sous `CTD_DATA_ROOT` :

- `final/` pour le dataset consolidé de l’extraction ;
- `icd/` pour le dataset enrichi ICD-10 et les rapports de contrôle ;
- les autres sous-répertoires pour les étapes intermédiaires et leurs audits.

Cette organisation permet d’exécuter l’extraction seule, le mapping seul ou la
chaîne complète sans écrire de résultats à la racine du dépôt.
