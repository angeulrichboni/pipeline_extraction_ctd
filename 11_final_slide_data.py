"""
Extrait, pour les 3 PMIDs retenus pour la banque d'exemples, 2-3 lignes
representatives par agent (pollutant, outcome, effect_measure), en
privilegiant la diversite des roles/categories plutot que les premieres
lignes brutes -- pour que chaque table montre bien le contraste voulu
(polluant cible vs contextuel, outcome principal vs secondaire).

Ajoute aussi la ligne population (1 par PMID) et 2-3 lignes de fenetre
temporelle par PMID.

Sortie : imprime les tableaux (Markdown) + sauvegarde un CSV par
agent x PMID.

Usage :
    python3 11_final_slide_data.py
"""
import json
from pathlib import Path

DATA_ROOT = Path("data/processed")  # ajuster si CTD_DATA_ROOT differe
OUT_DIR = Path("slide_data")
OUT_DIR.mkdir(exist_ok=True)

PMIDS = ["16451867", "17938744", "18197308"]
MAX_EVIDENCE_CHARS = 100
N_ROWS = 3


def load_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def shorten(text, max_chars: int = MAX_EVIDENCE_CHARS) -> str:
    text = str(text or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rsplit(" ", 1)[0] + "…"


def diverse_sample(items: list[dict], role_field: str, n: int) -> list[dict]:
    """Choisit jusqu'a n items en privilegiant un role/categorie different
    a chaque fois, plutot que de prendre les n premiers (qui peuvent tous
    avoir le meme role)."""
    seen_roles = set()
    picked = []

    for item in items:
        role = item.get(role_field)
        if role not in seen_roles:
            picked.append(item)
            seen_roles.add(role)
        if len(picked) == n:
            return picked

    for item in items:
        if item not in picked:
            picked.append(item)
        if len(picked) == n:
            break

    return picked


def print_and_save_table(rows: list[dict], columns: list[str], title: str, out_name: str) -> None:
    print(f"\n--- {title} ---")

    if not rows:
        print("(aucune donnee)")
        return

    header = " | ".join(columns)
    print(header)
    print("-" * len(header))
    for row in rows:
        print(" | ".join(str(row.get(c, "")) for c in columns))

    with open(OUT_DIR / out_name, "w", encoding="utf-8") as f:
        f.write(",".join(columns) + "\n")
        for row in rows:
            f.write(",".join(f'"{row.get(c, "")}"' for c in columns) + "\n")


def main() -> None:
    for pmid in PMIDS:
        print("=" * 100)
        print(f"PMID {pmid}")
        print("=" * 100)

        # --- Pollutant Extractor ---
        payload = load_json(DATA_ROOT / "agent_outputs" / "pollutant_extractor" / f"{pmid}_pollutants.json")
        if payload:
            items = payload.get("pollutants_found", [])
            sample = diverse_sample(items, "pollutant_role", N_ROWS)
            for i in sample:
                i["evidence_sentence"] = shorten(i.get("evidence_sentence"))
            print_and_save_table(
                sample,
                ["pollutant_specific", "pollutant_role", "evidence_sentence", "confidence"],
                "Pollutant Extractor",
                f"{pmid}_pollutant_sample.csv",
            )

        # --- Outcome Extractor ---
        payload = load_json(DATA_ROOT / "agent_outputs" / "outcome_extractor" / f"{pmid}_outcomes.json")
        if payload:
            items = payload.get("outcomes_found", [])
            sample = diverse_sample(items, "outcome_role", N_ROWS)
            for i in sample:
                i["evidence_sentence"] = shorten(i.get("evidence_sentence"))
            print_and_save_table(
                sample,
                ["outcome_core", "outcome_category", "outcome_role", "evidence_sentence"],
                "Outcome Extractor",
                f"{pmid}_outcome_sample.csv",
            )

        # --- Effect Measure Extractor ---
        payload = load_json(DATA_ROOT / "agent_outputs" / "effect_measure_extractor" / f"{pmid}_effect_measures.json")
        if payload:
            items = payload.get("effect_measures_found", [])
            sample = diverse_sample(items, "measure_type", N_ROWS)
            for i in sample:
                i["evidence_sentence"] = shorten(i.get("evidence_sentence"))
            print_and_save_table(
                sample,
                ["pollutant_mention", "outcome_mention", "measure_type", "effect_value",
                 "ci_lower", "ci_upper", "evidence_sentence"],
                "Effect Measure Extractor",
                f"{pmid}_effect_sample.csv",
            )

        # --- Population (1 ligne) ---
        payload = load_json(DATA_ROOT / "agent_outputs" / "population_extractor" / f"{pmid}_population.json")
        if payload:
            print_and_save_table(
                [payload],
                ["study_country", "study_city_or_region", "age_group", "sex", "status"],
                "Population",
                f"{pmid}_population_sample.csv",
            )

        # --- Exposure Temporal ---
        payload = load_json(DATA_ROOT / "agent_outputs" / "time_extractor" / f"{pmid}_exposure_temporal.json")
        if payload:
            items = payload.get("exposure_temporal_found", [])
            sample = diverse_sample(items, "exposure_window_category", N_ROWS)
            for i in sample:
                i["temporal_evidence_sentence"] = shorten(i.get("temporal_evidence_sentence"))
            print_and_save_table(
                sample,
                ["association_id", "exposure_window_category", "exposure_window_text",
                 "temporal_evidence_sentence"],
                "Exposure Temporal",
                f"{pmid}_temporal_sample.csv",
            )

        print()

    print(f"\nTous les CSV sont sauvegardes dans : {OUT_DIR.resolve()}")


if __name__ == "__main__":
    main()