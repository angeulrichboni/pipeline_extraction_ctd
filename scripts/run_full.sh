#!/usr/bin/env bash
# Exécute l'extraction complète puis le mapping ICD-10.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export CTD_DATA_ROOT="${CTD_DATA_ROOT:-data/processed}"
WORKERS="${WORKERS:-4}"
ICD_OUTPUT_DIR="$CTD_DATA_ROOT/icd"

python -m src.runners.run_pipeline --workers "$WORKERS"

FINAL_DATASET="$CTD_DATA_ROOT/final/ctd_extraction_final.csv"
if [[ ! -f "$FINAL_DATASET" ]]; then
  echo "Dataset final absent : $FINAL_DATASET" >&2
  exit 1
fi

PYTHONPATH=. python -m src.icd.map_ctd_to_icd \
  --input "$FINAL_DATASET" \
  --output-dir "$ICD_OUTPUT_DIR" \
  --strict

echo "Pipeline terminé : $FINAL_DATASET et $ICD_OUTPUT_DIR/."
