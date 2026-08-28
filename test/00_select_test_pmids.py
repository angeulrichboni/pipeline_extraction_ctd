import json
import re
from pathlib import Path

import pandas as pd


CTD_DIR = Path("data/raw")
OUT_DIR = Path("data/prototype")
OUT_DIR.mkdir(parents=True, exist_ok=True)

EXPOSURE_FILES = {
    "NO": "CTD_D009569_exposure_20260609045231.csv",
    "NO2": "CTD_D009585_exposure_20260609050257.csv",
    "O3": "CTD_D010126_exposure_20260609050316.csv",
    "PM": "CTD_D052638_exposure_20260609050536.csv",
}

TARGET_SAMPLE = {
    "PM": 4,
    "NO2": 2,
    "O3": 2,
    "NO": 2,
}


def read_ctd_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing CTD file: {path}")
    return pd.read_csv(path, comment="#", dtype=str).fillna("")


def extract_pmid(value: str) -> str | None:
    match = re.search(r"\d+", str(value))
    return match.group(0) if match else None


def is_non_empty(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().ne("")


def first_ctd_value(value: str) -> str:
    value = str(value).strip()
    if not value:
        return ""
    return value.split("|")[0].strip()


def load_exposure_corpus() -> pd.DataFrame:
    frames = []

    for pollutant, filename in EXPOSURE_FILES.items():
        path = CTD_DIR / filename
        df = read_ctd_csv(path)

        df["source_pollutant"] = pollutant
        df["source_file"] = filename
        df["pmid"] = df["Reference"].apply(extract_pmid)

        frames.append(df)

    exposure_df = pd.concat(frames, ignore_index=True)

    exposure_df["has_pmid"] = is_non_empty(exposure_df["pmid"])
    exposure_df["has_receptor"] = is_non_empty(exposure_df["Receptors"])
    exposure_df["has_outcome"] = is_non_empty(exposure_df["Outcome"])

    filtered = exposure_df[
        exposure_df["has_pmid"]
        & exposure_df["has_receptor"]
        & exposure_df["has_outcome"]
    ].copy()

    filtered["outcome_primary"] = filtered["Outcome"].apply(first_ctd_value)
    filtered["country_primary"] = filtered["Country"].apply(first_ctd_value)
    filtered["receptor_primary"] = filtered["Receptors"].apply(first_ctd_value)

    return exposure_df, filtered


def select_diverse_pmids(filtered: pd.DataFrame) -> pd.DataFrame:
    selected_frames = []
    already_selected_pmids: set[str] = set()

    for pollutant, n in TARGET_SAMPLE.items():
        sub = filtered[
            (filtered["source_pollutant"] == pollutant)
            & (~filtered["pmid"].isin(already_selected_pmids))
        ].copy()

        if sub.empty:
            raise ValueError(f"No candidate PMID found for pollutant={pollutant}")

        # Priorité à la diversité outcome/pays/receptor.
        diverse = (
            sub.sort_values(["outcome_primary", "country_primary", "receptor_primary", "pmid"])
            .drop_duplicates(subset=["outcome_primary", "country_primary", "receptor_primary"])
        )

        chosen = diverse.head(n)

        # Si pas assez, compléter avec d'autres PMIDs.
        if len(chosen) < n:
            remaining = sub[
                ~sub["pmid"].isin(chosen["pmid"])
            ].drop_duplicates(subset=["pmid"])

            chosen = pd.concat(
                [chosen, remaining.head(n - len(chosen))],
                ignore_index=True
            )

        if len(chosen) < n:
            raise ValueError(
                f"Could not select {n} PMIDs for pollutant={pollutant}. "
                f"Only found {len(chosen)}."
            )

        selected_frames.append(chosen)
        already_selected_pmids.update(chosen["pmid"].tolist())

    selected = pd.concat(selected_frames, ignore_index=True)

    # Garde une seule ligne CTD par PMID dans l’échantillon de test.
    selected = selected.drop_duplicates(subset=["pmid"]).copy()

    return selected


def main() -> None:
    exposure_df, filtered_df = load_exposure_corpus()
    selected_df = select_diverse_pmids(filtered_df)

    all_filtered_path = OUT_DIR / "ctd_exposure_filtered_all.csv"
    selected_context_path = OUT_DIR / "ctd_context_test.csv"
    pmids_path = OUT_DIR / "pmids_test.txt"
    audit_path = OUT_DIR / "ctd_test_selection_audit.json"

    filtered_df.to_csv(all_filtered_path, index=False)
    selected_df.to_csv(selected_context_path, index=False)

    pmids = selected_df["pmid"].astype(str).tolist()

    with open(pmids_path, "w", encoding="utf-8") as f:
        f.write("\n".join(pmids))
        f.write("\n")

    audit = {
        "total_exposure_rows": int(len(exposure_df)),
        "filtered_rows": int(len(filtered_df)),
        "filtered_unique_pmids": int(filtered_df["pmid"].nunique()),
        "selected_rows": int(len(selected_df)),
        "selected_unique_pmids": int(selected_df["pmid"].nunique()),
        "selected_by_pollutant": selected_df["source_pollutant"].value_counts().to_dict(),
        "outputs": {
            "all_filtered": str(all_filtered_path),
            "selected_context": str(selected_context_path),
            "pmids_test": str(pmids_path),
        },
    }

    with open(audit_path, "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)

    print("=" * 80)
    print("CTD TEST PMID SELECTION COMPLETE")
    print("=" * 80)
    print(json.dumps(audit, indent=2, ensure_ascii=False))
    print("=" * 80)


if __name__ == "__main__":
    main()