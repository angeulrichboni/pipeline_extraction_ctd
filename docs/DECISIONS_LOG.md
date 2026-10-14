# Règles scientifiques et choix techniques

Ce document décrit les règles appliquées par le pipeline. Il sert de référence
pour interpréter les résultats et évaluer leur traçabilité.

## Périmètre scientifique

Le pipeline recherche des associations entre les particules, l’ozone, le
dioxyde d’azote, le monoxyde d’azote et des effets sanitaires rapportés dans
des publications biomédicales référencées par CTD.

Le dataset final est centré sur l’épidémiologie humaine. Les données CTD
mécanistiques sur les gènes, maladies et phénotypes complètent les associations
PM sans transformer une relation mécanistique en estimation épidémiologique.

## Unité d’analyse

Une ligne représente une estimation scientifique contextualisée. La clé
conceptuelle inclut au minimum la publication, le polluant, l’outcome et la
mesure. La population, le scénario analytique et la temporalité permettent de
distinguer des estimations qui ne doivent pas être confondues.

Deux valeurs numériques rapportées pour des sous-groupes, fenêtres, lags ou
modèles différents restent deux associations. La fusion multi-PMID empile et
déduplique les résultats ; elle ne calcule pas de RR ou d’effet combiné.

## Sélection des sources

Les PMIDs proviennent des exports d’exposition CTD pour les quatre polluants
ciblés. PubMed fournit les métadonnées et l’abstract. Lorsqu’un texte complet
est accessible, Paperclip ou Europe PMC fournit le contenu documentaire.

La provenance du texte et les échecs de récupération sont conservés dans les
manifestes et audits. Un abstract exploitable peut être traité lorsque le
texte complet n’est pas disponible.

## Segmentation

Les documents sont segmentés avant l’appel aux agents. Chaque segment est
traité séparément, puis les objets extraits sont fusionnés, normalisés et
dédupliqués en Python.

Cette organisation permet de conserver des preuves situées dans des sections
différentes et limite la perte d’information liée à la taille du contexte.
Une phrase de preuve reste attachée à l’entité ou à l’association qu’elle
soutient.

## Rôle du LLM et rôle du code

Les agents LLM identifient et structurent les informations exprimées dans les
publications. Ils produisent également les preuves textuelles, la confiance et
les avertissements disponibles.

Le code Python assure :

- la normalisation des objets ;
- la déduplication ;
- la construction des associations ;
- les contrôles de cohérence ;
- les décisions finales de qualité ;
- la fusion des tables ;
- l’application du référentiel ICD-10.

Une réponse LLM n’est donc pas acceptée comme résultat final sans passer par
les validations déterministes du pipeline.

## Construction des associations

Le builder relie les polluants, outcomes et mesures issus d’une même
publication. Une association doit rester interprétable à partir de ses champs
et de sa preuve.

Les règles évitent notamment :

- d’attacher une valeur à un outcome qui ne correspond pas à sa phrase ;
- de confondre une exposition principale et une covariable ;
- de fusionner des mesures de types différents ;
- de supprimer des estimations distinctes uniquement parce qu’elles partagent
  un PMID et un polluant.

## Contrôle qualité

Le contrôle qualité classe chaque relation :

- `accept` lorsque l’exposition, l’outcome et la mesure sont suffisamment
  définis pour l’analyse ;
- `review` lorsqu’une ambiguïté demande une validation humaine ;
- `reject` lorsqu’un composant indispensable est invalide ou hors périmètre.

Les tables de revue et de rejet conservent les motifs. L’analyse principale ne
doit utiliser que les lignes indiquées comme incluses par le contrôle qualité.

## Population et temporalité

La population, la localisation et la temporalité sont extraites au niveau de
l’association lorsque les éléments documentaires le permettent.

Le lag est une caractéristique de l’estimation publiée. Le pipeline le stocke
et le qualifie ; il ne décale pas les données d’exposition et ne recalcule pas
une fenêtre temporelle.

Une mesure d’effet doit être interprétée avec son polluant, son outcome, sa
population, son scénario analytique, sa fenêtre et son instant ou lag. Elle ne
doit pas être réduite à une valeur unique par persona et polluant.

## Enrichissement mécanistique CTD

La couche mécanistique est limitée aux associations reconnues comme
PM/D052638. Elle sépare :

- le contexte général des gènes humains liés aux particules ;
- les correspondances disease/phenotype propres à l’outcome ;
- les liens gène–outcome soutenus par le réseau CTD correspondant.

Une association non-PM reste présente, avec un statut indiquant que
l’enrichissement PM ne s’applique pas.

## Mapping ICD-10

Le mapping cible l’ICD-10 OMS, release 2019, à partir de
`config/icd_mapping_reference.csv`.

Les règles sont les suivantes :

1. une règle spécifique au PMID est prioritaire ;
2. une règle générale s’applique si elle couvre la clé normalisée ;
3. une mesure physiologique ou un biomarqueur peut être validé comme non ICD ;
4. un événement trop général peut être explicitement exclu ;
5. aucune correspondance n’est créée par simple ressemblance lexicale ;
6. tout outcome PM sans règle validée reste `UNMAPPED_REVIEW`.

Chaque règle conserve son niveau de mapping, sa confiance, sa justification et
ses sources. Le mode strict transforme un cas PM non résolu en erreur
d’exécution.

## Valeurs manquantes

Une valeur absente ne signifie pas automatiquement que l’information est
fausse. Elle peut correspondre à une information non rapportée, non trouvée,
non applicable ou rejetée par les contrôles. Les champs de statut, de confiance
et de preuve doivent accompagner toute analyse de complétude.

## Organisation et versionnement

Le code, les tests, la documentation et le référentiel ICD-10 sont versionnés.
Les exports CTD, textes récupérés, réponses LLM et résultats calculés sont
stockés sous `data/` et exclus de Git.

`CTD_DATA_ROOT` permet d’isoler plusieurs exécutions dans des répertoires
distincts. Pour une analyse reproductible, conserver avec les résultats :

- la révision Git du code ;
- le référentiel ICD-10 utilisé ;
- les exports CTD sources ;
- le modèle et l’URL du fournisseur ;
- les audits et journaux d’exécution.

## Confidentialité et services externes

Les étapes PubMed, Paperclip/Europe PMC et LLM utilisent le réseau. Les agents
envoient des segments de publications au fournisseur configuré. Les clés API
restent dans `.env`, qui est exclu de Git. Les journaux partagés pour diagnostic
doivent être contrôlés afin de ne pas exposer de clé ou de contenu sensible.
