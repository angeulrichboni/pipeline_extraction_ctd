"""
CLI runner : teste la coherence d'un modele LLM en relancant le meme agent
sur le meme PMID plusieurs fois, et en comparant les items extraits d'un
run a l'autre. A utiliser avant de choisir un modele pour le run complet --
un modele instable (meme a temperature=0.0) produira des items presents
seulement dans une partie des repetitions.

Usage :
    python -m src.runners.check_model_consistency --pmid 17938725 --agent pollutant --repeats 3
    python -m src.runners.check_model_consistency --pmid 17938725 --agent effect_measure --repeats 5 --model mistral-small-3.2-24b
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.config.paths import paths
from src.config.settings import settings
from src.llm.client import ILAASClient

# Champs utilises pour identifier un item d'un run a l'autre. On exclut
# volontairement les champs de texte libre (evidence_sentence, reasoning) qui
# peuvent varier en formulation meme quand le modele identifie la meme chose
# -- ce n'est pas de l'instabilite au sens ou on l'entend ici.
AGENT_CONFIG = {
    "pollutant": {
        "found_key": "pollutants_found",
        "key_fields": ["pollutant_general", "pollutant_specific"],
    },
    "outcome": {
        "found_key": "outcomes_found",
        "key_fields": ["outcome_core", "outcome_category"],
    },
    "effect_measure": {
        "found_key": "effect_measures_found",
        "key_fields": ["pollutant_mention", "outcome_mention", "measure_type", "effect_value"],
    },
}


def item_key(item: dict[str, Any], key_fields: list[str]) -> str:
    return " | ".join(str(item.get(field, "")).strip().lower() for field in key_fields)


def run_repeats(
    pmid: str,
    agent: str,
    repeats: int,
    client: ILAASClient,
    model: str,
) -> tuple[list[list[dict[str, Any]]], list[dict[str, Any]]]:
    config = AGENT_CONFIG[agent]

    safe_model = model.replace("/", "_")
    tmp_dir = paths.processed_dir / "consistency_tests" / f"{agent}_{safe_model}_{pmid}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    print(f"Sorties detaillees de ce test (raw_response, reasoning) : {tmp_dir}")
    print()

    runs: list[list[dict[str, Any]]] = []
    failed_runs: list[dict[str, Any]] = []

    for run_index in range(1, repeats + 1):
        print(f"--- Run {run_index}/{repeats} ---")

        run_dir = tmp_dir / f"run_{run_index}"
        run_dir.mkdir(parents=True, exist_ok=True)

        try:
            if agent == "pollutant":
                from src.agents.pollutant_extractor import run_pollutant_extractor_for_pmid

                payload = run_pollutant_extractor_for_pmid(
                    pmid=pmid,
                    segmented_document_path=paths.segmented_document_path(pmid),
                    output_json=run_dir / "out.json",
                    output_state_json=run_dir / "state.json",
                    raw_response_path=run_dir / "raw.txt",
                    repair_response_path=run_dir / "repair.txt",
                    reasoning_dir=run_dir / "reasoning",
                    client=client,
                    model=model,
                )

            elif agent == "outcome":
                from src.agents.outcome_extractor import run_outcome_extractor_for_pmid

                payload = run_outcome_extractor_for_pmid(
                    pmid=pmid,
                    segmented_document_path=paths.segmented_document_path(pmid),
                    pollutant_json_path=paths.pollutant_output_path(pmid)
                    if paths.pollutant_output_path(pmid).exists()
                    else None,
                    output_json=run_dir / "out.json",
                    output_state_json=run_dir / "state.json",
                    raw_response_path=run_dir / "raw.txt",
                    repair_response_path=run_dir / "repair.txt",
                    reasoning_dir=run_dir / "reasoning",
                    client=client,
                    model=model,
                )

            elif agent == "effect_measure":
                from src.agents.effect_measure_extractor import run_effect_measure_extractor_for_pmid

                payload = run_effect_measure_extractor_for_pmid(
                    pmid=pmid,
                    segmented_document_path=paths.segmented_document_path(pmid),
                    pollutant_json_path=paths.pollutant_output_path(pmid)
                    if paths.pollutant_output_path(pmid).exists()
                    else None,
                    outcome_json_path=paths.outcome_output_path(pmid)
                    if paths.outcome_output_path(pmid).exists()
                    else None,
                    output_json=run_dir / "out.json",
                    output_state_json=run_dir / "state.json",
                    raw_response_path=run_dir / "raw.txt",
                    repair_response_path=run_dir / "repair.txt",
                    reasoning_dir=run_dir / "reasoning",
                    client=client,
                    model=model,
                )

            else:
                raise ValueError(f"Agent inconnu : {agent}")

            items = payload[config["found_key"]]
            runs.append(items)

            print(f"  {len(items)} item(s) trouve(s)")

        except Exception as exc:
            failed_runs.append({"run_index": run_index, "error": str(exc)})
            print(f"  ECHEC de ce run : {exc}")

    return runs, failed_runs


def analyze_consistency(
    runs: list[list[dict[str, Any]]],
    key_fields: list[str],
) -> dict[str, Any]:
    repeats = len(runs)

    # Compte, pour chaque cle d'item unique, dans combien de runs elle apparait.
    counts: dict[str, int] = {}

    for run_items in runs:
        keys_in_run = {item_key(item, key_fields) for item in run_items}
        for key in keys_in_run:
            counts[key] = counts.get(key, 0) + 1

    stable = {key: count for key, count in counts.items() if count == repeats}
    unstable = {key: count for key, count in counts.items() if count < repeats}

    total_unique = len(counts)
    if total_unique == 0:
        # Aucun item trouve dans AUCUN run : rien a comparer, ce n'est pas
        # une preuve de stabilite -- on le signale explicitement plutot que
        # d'afficher un faux score parfait.
        consistency_score = None
    else:
        consistency_score = len(stable) / total_unique

    return {
        "repeats": repeats,
        "total_unique_items": total_unique,
        "stable_items": len(stable),
        "unstable_items": len(unstable),
        "consistency_score": round(consistency_score, 3) if consistency_score is not None else None,
        "stable_item_keys": sorted(stable.keys()),
        "unstable_item_keys": {key: f"{count}/{repeats}" for key, count in unstable.items()},
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Teste la coherence d'un modele en relancant le meme agent plusieurs fois sur le meme PMID."
    )

    parser.add_argument("--pmid", required=True, help="PMID a tester (doit deja etre segmente).")
    parser.add_argument(
        "--agent",
        required=True,
        choices=list(AGENT_CONFIG.keys()),
        help="Agent a tester.",
    )
    parser.add_argument("--repeats", type=int, default=3, help="Nombre de repetitions (defaut 3).")
    parser.add_argument("--model", default=None, help="Modele a tester (defaut : ILAAS_MODEL du .env).")

    args = parser.parse_args()

    model = args.model or settings.ilaas_model

    client = ILAASClient(
        api_key=settings.ilaas_api_key,
        base_url=settings.ilaas_base_url,
        model=model,
    )

    print("=" * 80)
    print("TEST DE COHERENCE")
    print("=" * 80)
    print(f"PMID: {args.pmid}")
    print(f"Agent: {args.agent}")
    print(f"Modele: {model}")
    print(f"Repetitions: {args.repeats}")
    print()

    runs, failed_runs = run_repeats(
        pmid=args.pmid,
        agent=args.agent,
        repeats=args.repeats,
        client=client,
        model=model,
    )

    if failed_runs:
        print()
        print(f"ATTENTION : {len(failed_runs)}/{args.repeats} run(s) ont echoue (erreur reseau/serveur, pas un probleme de coherence) :")
        for failure in failed_runs:
            print(f"  - run {failure['run_index']} : {failure['error']}")

    if not runs:
        print()
        print("Aucun run n'a reussi -- impossible de mesurer la coherence. Reessaie, ou change de modele.")
        return

    key_fields = AGENT_CONFIG[args.agent]["key_fields"]
    analysis = analyze_consistency(runs, key_fields)
    analysis["successful_runs"] = len(runs)
    analysis["failed_runs"] = len(failed_runs)

    print()
    print("=" * 80)
    print("RESULTAT")
    print("=" * 80)
    print(f"Items uniques toutes repetitions confondues : {analysis['total_unique_items']}")
    print(f"Items stables (presents dans les {args.repeats} runs) : {analysis['stable_items']}")
    print(f"Items instables (absents d'au moins 1 run) : {analysis['unstable_items']}")

    if analysis["consistency_score"] is None:
        print("Score de coherence : NON CALCULABLE (aucun item trouve dans aucun run)")
    else:
        print(f"Score de coherence : {analysis['consistency_score']} (1.0 = parfaitement stable)")

    if analysis["unstable_item_keys"]:
        print()
        print("Items instables (cle -> nb de runs ou il apparait) :")
        for key, ratio in analysis["unstable_item_keys"].items():
            print(f"  - {key!r} : {ratio}")

    print()
    if analysis["consistency_score"] is None:
        print(
            "-> Rien trouve dans aucun des runs : ceci NE PROUVE PAS que le modele est "
            "stable. Verifie manuellement (raw_response, reasoning) si l'absence est "
            "normale pour ce PMID/agent, ou reteste sur un PMID dont tu sais qu'il "
            "contient ce type d'information."
        )
    elif analysis["consistency_score"] >= 0.9:
        print("-> Modele stable, utilisable pour un run complet.")
    elif analysis["consistency_score"] >= 0.7:
        print("-> Modele moyennement stable, a surveiller sur un plus grand echantillon.")
    else:
        print("-> Modele instable, deconseille pour ce pipeline (reproductibilite compromise).")


if __name__ == "__main__":
    main()
