from pathlib import Path
import json
import pandas as pd

BASE = Path("data/processed_full/exposure_temporal_extraction")

final_path = Path("data/processed_full/manual_fusions/ctd_extraction_final_v2_population_location.csv")
temp_path = BASE / "temp_exposure_time.csv"
errors_path = BASE / "exposure_temporal_llm_errors.jsonl"
outputs_path = BASE / "exposure_temporal_llm_outputs.jsonl"

def read_jsonl(path):
    rows = []
    if not path.exists():
        return rows
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows

final_df = pd.read_csv(final_path, low_memory=False)
temp_df = pd.read_csv(temp_path, low_memory=False)

final_df["association_id"] = final_df["association_id"].astype(str)
temp_df["association_id"] = temp_df["association_id"].astype(str)

final_ids = set(final_df["association_id"])
temp_ids = set(temp_df["association_id"])

missing_ids = sorted(final_ids - temp_ids)

errors = read_jsonl(errors_path)
outputs = read_jsonl(outputs_path)

error_ids = {
    str(x.get("association_id", "")).strip()
    for x in errors
    if str(x.get("association_id", "")).strip()
}

output_ids = {
    str(x.get("association_id", "")).strip()
    for x in outputs
    if str(x.get("association_id", "")).strip()
}

print("Associations attendues:", len(final_ids))
print("Outputs JSONL uniques:", len(output_ids))
print("Temp CSV lignes:", len(temp_df))
print("Temp CSV association_id uniques:", len(temp_ids))
print("Manquants dans temp CSV:", len(missing_ids))
print("Erreurs enregistrées:", len(error_ids))

print("\nDistribution temporal_status:")
print(temp_df["temporal_status"].value_counts(dropna=False))

print("\nDistribution exposure_window_category:")
print(temp_df["exposure_window_category"].value_counts(dropna=False))

pd.DataFrame({"association_id": missing_ids}).to_csv(
    BASE / "missing_exposure_temporal_association_ids.csv",
    index=False
)

pd.DataFrame(errors).to_csv(
    BASE / "exposure_temporal_errors.csv",
    index=False
)

print("\nSaved missing:", BASE / "missing_exposure_temporal_association_ids.csv")
print("Saved errors:", BASE / "exposure_temporal_errors.csv")