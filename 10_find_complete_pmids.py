"""
Cherche, parmi tous les PMIDs traites, ceux qui ont une sortie complete dans
les 5 agents (pollutant, outcome, effect_measure, population, time) --
candidats ideaux pour la banque d'exemples, puisqu'ils permettent de montrer
le pipeline de bout en bout sur un seul article.

Usage :
    python3 10_find_complete_pmids.py
    python3 10_find_complete_pmids.py --min-effects 2
"""
import argparse
import json
from pathlib import Path

DATA_ROOT = Path("data/processed")  # ajuster si CTD_DATA_ROOT differe


def pmids_from_glob(directory: Path, suffix: str) -> set[str]:
    if not directory.exists():
        return set()
    return {p.name.replace(suffix, "") for p in directory.glob(f"*{suffix}")}


def pmids_with_min_effects(directory: Path, min_effects: int) -> set[str]:
    result = set()
    if not directory.exists():
        return result
    for path in directory.glob("*_effect_measures.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if len(data.get("effect_measures_found", [])) >= min_effects:
            result.add(path.name.replace("_effect_measures.json", ""))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-effects", type=int, default=1,
                         help="Nombre minimum de mesures d'effet exigees (defaut 1).")
    parser.add_argument("--top", type=int, default=15,
                         help="Nombre de PMIDs a afficher (defaut 15).")
    args = parser.parse_args()

    agent_outputs = DATA_ROOT / "agent_outputs"

    pollutant_pmids = pmids_from_glob(agent_outputs / "pollutant_extractor", "_pollutants.json")
    outcome_pmids = pmids_from_glob(agent_outputs / "outcome_extractor", "_outcomes.json")
    effect_pmids = pmids_with_min_effects(agent_outputs / "effect_measure_extractor", args.min_effects)
    population_pmids = pmids_from_glob(agent_outputs / "population_extractor", "_population.json")
    temporal_pmids = pmids_from_glob(agent_outputs / "time_extractor", "_exposure_temporal.json")

    print(f"PMIDs avec pollutant_extractor      : {len(pollutant_pmids)}")
    print(f"PMIDs avec outcome_extractor        : {len(outcome_pmids)}")
    print(f"PMIDs avec >= {args.min_effects} mesure(s) d'effet : {len(effect_pmids)}")
    print(f"PMIDs avec population_extractor     : {len(population_pmids)}")
    print(f"PMIDs avec time_extractor            : {len(temporal_pmids)}")

    complete = pollutant_pmids & outcome_pmids & effect_pmids & population_pmids & temporal_pmids

    print()
    print(f"=> PMIDs complets sur les 5 agents : {len(complete)}")
    print()

    for pmid in sorted(complete)[: args.top]:
        effect_path = agent_outputs / "effect_measure_extractor" / f"{pmid}_effect_measures.json"
        n_effects = len(json.loads(effect_path.read_text()).get("effect_measures_found", []))
        print(f"  {pmid}  ({n_effects} mesure(s) d'effet)")

    if len(complete) > args.top:
        print(f"  ... et {len(complete) - args.top} autre(s)")


if __name__ == "__main__":
    main()