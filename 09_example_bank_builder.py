"""
Recupere et resume, pour une liste de PMIDs, les sorties des 3 agents
(+ population/temporalite si disponibles), directement depuis les fichiers
JSON bruts par PMID -- pour comparer rapidement plusieurs PMIDs candidats
et choisir ceux qui illustrent le mieux la variete voulue (polluant
contextuel vs cible, outcome secondaire vs principal, etc.).

Usage :
    python3 09_example_bank_builder.py --pmids 20123607,17938725,19620729
"""
import argparse
import json
from pathlib import Path
from collections import Counter

DATA_ROOT = Path("data/processed")  # ajuster si CTD_DATA_ROOT differe


def load_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pmids", required=True, help="PMIDs separes par virgule.")
    parser.add_argument("--max-items", type=int, default=6, help="Nb d'items affiches par agent (defaut 6).")
    args = parser.parse_args()

    pmids = [p.strip() for p in args.pmids.split(",") if p.strip()]

    for pmid in pmids:
        print("=" * 100)
        print(f"PMID {pmid}")
        print("=" * 100)

        pollutant = load_json(DATA_ROOT / "agent_outputs" / "pollutant_extractor" / f"{pmid}_pollutants.json")
        outcome = load_json(DATA_ROOT / "agent_outputs" / "outcome_extractor" / f"{pmid}_outcomes.json")
        effect = load_json(DATA_ROOT / "agent_outputs" / "effect_measure_extractor" / f"{pmid}_effect_measures.json")
        population = load_json(DATA_ROOT / "agent_outputs" / "population_extractor" / f"{pmid}_population.json")
        temporal = load_json(DATA_ROOT / "agent_outputs" / "time_extractor" / f"{pmid}_exposure_temporal.json")

        # --- Pollutant Extractor ---
        if pollutant:
            items = pollutant.get("pollutants_found", [])
            roles = Counter(i.get("pollutant_role") for i in items)
            print(f"\n[Pollutant Extractor] {len(items)} polluants -- repartition par role : {dict(roles)}")
            for i in items[: args.max_items]:
                print(f"   - {i.get('pollutant_specific', ''):25s} role={i.get('pollutant_role', ''):12s} keep={i.get('keep_for_final_analysis')}")
        else:
            print("\n[Pollutant Extractor] absent pour ce PMID")

        # --- Outcome Extractor ---
        if outcome:
            items = outcome.get("outcomes_found", [])
            roles = Counter(i.get("outcome_role") for i in items)
            print(f"\n[Outcome Extractor] {len(items)} outcomes -- repartition par role : {dict(roles)}")
            for i in items[: args.max_items]:
                print(f"   - {i.get('outcome_core', ''):25s} role={i.get('outcome_role', ''):25s} keep={i.get('keep_for_final_analysis')}")
        else:
            print("\n[Outcome Extractor] absent pour ce PMID")

        # --- Effect Measure Extractor ---
        if effect:
            items = effect.get("effect_measures_found", [])
            print(f"\n[Effect Measure Extractor] {len(items)} mesures")
            for i in items[: args.max_items]:
                print(f"   - {i.get('pollutant_mention', ''):15s} -> {i.get('outcome_mention', ''):15s} "
                      f"{i.get('measure_type', ''):15s} = {i.get('effect_value', '')}")
        else:
            print("\n[Effect Measure Extractor] absent pour ce PMID")

        # --- Population ---
        if population:
            print(f"\n[Population] pays={population.get('study_country')} | "
                  f"age={population.get('age_group')} | sexe={population.get('sex')} | "
                  f"statut={population.get('status')}")
        else:
            print("\n[Population] absent pour ce PMID")

        # --- Temporalite ---
        if temporal:
            items = temporal.get("exposure_temporal_found", [])
            print(f"\n[Exposure Temporal] {len(items)} association(s) avec fenetre temporelle")
            for i in items[: args.max_items]:
                print(f"   - {i.get('association_id', ''):10s} categorie={i.get('exposure_window_category', '')}")
        else:
            print("\n[Exposure Temporal] absent pour ce PMID (aucune association retenue en QC, ou pas encore traite)")

        print()


if __name__ == "__main__":
    main()