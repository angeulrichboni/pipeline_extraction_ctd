#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
TMP_DIR="outputs/test_run"
rm -rf "$TMP_DIR"
PYTHONPATH=src python scripts/01_generate_trajectories.py \
  --days 2 --output-dir "$TMP_DIR" --plain-csv --log-every-days 1
PYTHONPATH=src python scripts/validate_outputs.py "$TMP_DIR"
PYTHONPATH=src pytest -q
rm -rf "$TMP_DIR"
