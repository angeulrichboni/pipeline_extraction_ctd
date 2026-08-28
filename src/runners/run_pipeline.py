"""
Lanceur du pipeline complet (Phase 1).

Enchaine les runners existants dans l'ordre documente dans le README, en
appelant chacun comme un sous-processus independant (`python -m src.runners.X`).
Ce script ne reimplemente aucune logique : il se contente d'orchestrer les
runners existants avec leurs arguments habituels.

Exemples :

    # Chaine complete sur un seul PMID (pratique pour tester)
    python -m src.runners.run_pipeline --pmid 19620729

    # Chaine complete sur une liste de PMIDs
    python -m src.runners.run_pipeline --pmids 19620729,20123607

    # Uniquement les etapes d'ingestion (avant les agents LLM)
    python -m src.runners.run_pipeline --stages ingestion

    # Lister les etapes disponibles sans rien executer
    python -m src.runners.run_pipeline --list-stages
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Stage:
    key: str
    module: str
    description: str
    # Si True, --pmid/--pmids/--limit lui sont transmis quand fournis.
    accepts_pmid_filter: bool = False
    # Si True, --workers lui est transmis (agents qui appellent un LLM).
    accepts_workers: bool = False
    extra_args: list[str] = field(default_factory=list)


STAGES: list[Stage] = [
    Stage("ctd_pm_human", "src.runners.build_ctd_pm_human_dataset",
          "Preprocessing CTD PM (D052638) : fusion + filtre etudes humaines."),
    Stage("ctd_exposure_candidates", "src.runners.build_ctd_exposure_candidates",
          "PMIDs candidats pour les 4 polluants CTD (PM, O3, NO2, NO)."),
    Stage("fetch_pubmed", "src.runners.fetch_pubmed_metadata",
          "Recuperer les metadonnees PubMed (titres, abstracts)."),
    Stage("fetch_paperclip", "src.runners.fetch_paperclip_full_texts",
          "Recuperer les textes complets via Paperclip."),
    Stage("prepare_llm_inputs", "src.runners.prepare_llm_inputs",
          "Construire les inputs LLM a partir de PubMed + Paperclip."),
    Stage("segment", "src.runners.run_document_segmentation",
          "Segmenter les documents en sections exploitables."),
    Stage("pollutant", "src.runners.run_pollutant_extractor",
          "Agent d'extraction des polluants.", accepts_pmid_filter=True, accepts_workers=True),
    Stage("outcome", "src.runners.run_outcome_extractor",
          "Agent d'extraction des outcomes de sante.", accepts_pmid_filter=True, accepts_workers=True),
    Stage("effect_measure", "src.runners.run_effect_measure_extractor",
          "Agent d'extraction des mesures d'effet.", accepts_pmid_filter=True, accepts_workers=True),
    Stage("association_builder", "src.runners.run_association_builder",
          "Construction des associations polluant-outcome.", accepts_pmid_filter=True),
    Stage("merge", "src.runners.merge_associations",
          "Fusion multi-PMID des associations.",
          extra_args=["--from-association-dir"]),
    Stage("quality_control", "src.runners.run_final_quality_control",
          "Quality control final (clean / rejected)."),
    Stage("inspect", "src.runners.inspect_outputs",
          "Inspection des sorties finales (tables main/contextual/review)."),
    Stage("final_tables", "src.runners.build_final_tables",
          "Construction des tables finales."),
    Stage("ctd_enrichment", "src.runners.build_ctd_pm_enrichment",
          "Enrichissement CTD (genes, maladies, phenotypes) sur PM."),
    Stage("agent_csv_exports", "src.runners.export_agent_csv_outputs",
          "Export CSV individuel de chaque agent (pollutant/outcome/effect/"
          "association/population/temporal)."),
    Stage("population_location", "src.runners.run_population_extractor",
          "Agent d'extraction population/localisation."),
    Stage("exposure_temporal", "src.runners.run_time_extractor",
          "Agent d'extraction de la temporalite d'exposition."),
    Stage("final_dataset", "src.runners.build_final_dataset",
          "Fusion finale : enrichissement CTD + population/localisation + temporalite."),
]

# Groupes pratiques pour --stages.
STAGE_GROUPS = {
    "all": [s.key for s in STAGES],
    "ingestion": ["ctd_pm_human", "ctd_exposure_candidates", "fetch_pubmed", "fetch_paperclip", "prepare_llm_inputs", "segment"],
    "agents": ["pollutant", "outcome", "effect_measure", "association_builder"],
    "postprocessing": [
        "merge", "quality_control", "inspect", "final_tables",
        "ctd_enrichment", "agent_csv_exports", "population_location",
        "exposure_temporal", "final_dataset",
    ],
}


def resolve_stage_keys(raw: str) -> list[str]:
    keys: list[str] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        if token in STAGE_GROUPS:
            keys.extend(STAGE_GROUPS[token])
        else:
            keys.append(token)
    # dedoublonne en gardant l'ordre du pipeline
    order = {s.key: i for i, s in enumerate(STAGES)}
    return sorted(set(keys), key=lambda k: order.get(k, 999))


def build_command(stage: Stage, args: argparse.Namespace) -> list[str]:
    cmd = [sys.executable, "-m", stage.module, *stage.extra_args]

    if stage.accepts_pmid_filter:
        if args.pmid:
            cmd += ["--pmid", args.pmid]
        elif args.pmids:
            cmd += ["--pmids", args.pmids]
        if args.limit:
            cmd += ["--limit", str(args.limit)]

    if stage.accepts_workers and args.workers:
        cmd += ["--workers", str(args.workers)]

    return cmd


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Lance le pipeline d'extraction (Phase 1) de bout en bout."
    )
    parser.add_argument(
        "--stages", default="all",
        help=(
            "Etapes a executer : 'all', un groupe "
            f"({', '.join(k for k in STAGE_GROUPS if k != 'all')}), "
            "ou une liste separee par des virgules de cles d'etapes."
        ),
    )
    parser.add_argument("--pmid", help="Ne traiter qu'un seul PMID (etapes agents).")
    parser.add_argument("--pmids", help="Liste de PMIDs separes par des virgules (etapes agents).")
    parser.add_argument("--limit", type=int, help="Limiter le nombre de PMIDs traites (etapes agents).")
    parser.add_argument(
        "--workers", type=int, default=4,
        help="Nombre de PMIDs traites en parallele pour les agents LLM (defaut 4, 1 = sequentiel).",
    )
    parser.add_argument(
        "--stop-on-error", action="store_true", default=True,
        help="Arreter le pipeline des qu'une etape echoue (comportement par defaut).",
    )
    parser.add_argument(
        "--continue-on-error", dest="stop_on_error", action="store_false",
        help="Continuer meme si une etape echoue.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Afficher les commandes sans les executer.",
    )
    parser.add_argument(
        "--list-stages", action="store_true",
        help="Lister les etapes disponibles et quitter.",
    )

    args = parser.parse_args()

    if args.list_stages:
        for stage in STAGES:
            print(f"{stage.key:22s} {stage.description}")
        return

    selected_keys = resolve_stage_keys(args.stages)
    stages_by_key = {s.key: s for s in STAGES}

    unknown = [k for k in selected_keys if k not in stages_by_key]
    if unknown:
        raise SystemExit(f"Etape(s) inconnue(s) : {', '.join(unknown)}")

    selected_stages = [stages_by_key[k] for k in selected_keys]

    print("=" * 80)
    print("PIPELINE CTD EXTRACT")
    print("Etapes : " + ", ".join(s.key for s in selected_stages))
    print("=" * 80)

    for stage in selected_stages:
        cmd = build_command(stage, args)
        print(f"\n--- [{stage.key}] {stage.description}")
        print("    " + " ".join(cmd))

        if args.dry_run:
            continue

        result = subprocess.run(cmd)

        if result.returncode != 0:
            print(f"\n>>> Etape '{stage.key}' en echec (code {result.returncode}).")
            if args.stop_on_error:
                raise SystemExit(result.returncode)

    print("\n" + "=" * 80)
    print("PIPELINE TERMINE" if not args.dry_run else "DRY-RUN TERMINE")
    print("=" * 80)


if __name__ == "__main__":
    main()
