#!/usr/bin/env bash
# Exécute les 7 étapes du pipeline dans l'ordre, une seule fois.
# CTD_PATH doit pointer vers le fichier CTD brut (ctd_extraction.csv) pour
# l'étape 2 (mapping ICD) -- pas le fichier déjà mappé.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p outputs

PYTHONPATH=src python scripts/01_generate_trajectories.py \
  --output-dir outputs --log-every-days 90 2>&1 | tee outputs/01_trajectories.log

if [[ -f "${CTD_PATH:-ctd_extraction.csv}" ]]; then
  PYTHONPATH=src python scripts/02_map_ctd_to_icd.py \
    --input "${CTD_PATH:-ctd_extraction.csv}" \
    --output-dir outputs 2>&1 | tee outputs/02_icd_mapping.log
else
  echo "Étape 2 sautée : définir CTD_PATH vers le fichier CTD brut (ctd_extraction.csv)." \
    | tee outputs/02_icd_mapping.log
fi

PYTHONPATH=src python scripts/03_generate_p0_schedule.py \
  --output-dir outputs 2>&1 | tee outputs/03_p0_schedule.log

PYTHONPATH=src python scripts/validate_outputs.py outputs \
  2>&1 | tee outputs/validation.log

PYTHONPATH=src python scripts/04_generate_exposure_windows.py \
  --output-dir outputs 2>&1 | tee outputs/04_exposure_windows.log

PYTHONPATH=src python scripts/05_generate_exposure_thresholds.py \
  --output-dir outputs 2>&1 | tee outputs/05_exposure_thresholds.log

PYTHONPATH=src python scripts/06_generate_exposure_trajectory.py \
  --output-dir outputs 2>&1 | tee outputs/06_exposure_trajectory.log

if [[ -f "outputs/ctd_icd_mapped_complete.csv" ]]; then
  PYTHONPATH=src python scripts/07_generate_exposure_health_dataset.py \
    --output-dir outputs 2>&1 | tee outputs/07_exposure_health_dataset.log
else
  echo "Étape 7 sautée : ctd_icd_mapped_complete.csv absent (voir étape 2)." \
    | tee outputs/07_exposure_health_dataset.log
fi

echo "Pipeline terminé. Sorties dans outputs/."
