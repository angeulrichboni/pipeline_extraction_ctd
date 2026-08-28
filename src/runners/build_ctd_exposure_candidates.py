"""
CLI runner : construit, pour chacun des 4 polluants suivis par le projet
(PM, O3, NO2, NO), la liste des PMIDs candidats issus de CTD_*_exposure.
Complement de build_ctd_pm_human_dataset.py (qui reste la seule source pour
genes/ixns/phenotype/diseases, disponibles uniquement pour PM).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.config.paths import paths
from src.io.logging_utils import setup_logger
from src.preprocessing.ctd_exposure_candidates import (
    POLLUTANTS,
    build_all_exposure_candidates,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Construit les PMIDs candidats par polluant CTD (PM, O3, NO2, NO)."
    )

    parser.add_argument(
        "--raw-dir",
        default=str(paths.raw_dir),
        help="Dossier contenant les CSV CTD_*_exposure*.csv bruts.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(paths.processed_dir / "ctd_exposure_candidates"),
        help="Dossier de sortie.",
    )

    args = parser.parse_args()

    paths.ensure_base_dirs()

    logger = setup_logger(
        name="build_ctd_exposure_candidates",
        log_file=paths.logs_dir / "build_ctd_exposure_candidates.log",
    )

    raw_dir = Path(args.raw_dir)
    output_dir = Path(args.output_dir)

    logger.info("=" * 80)
    logger.info("CTD EXPOSURE CANDIDATES (%s)", ", ".join(POLLUTANTS))
    logger.info("=" * 80)
    logger.info("raw_dir=%s output_dir=%s", raw_dir, output_dir)

    audit = build_all_exposure_candidates(raw_dir=raw_dir, output_dir=output_dir)

    audit_path = output_dir / "audit.json"
    audit_path.write_text(json.dumps(audit, indent=2, ensure_ascii=False))

    print("=" * 80)
    print("CTD EXPOSURE CANDIDATES")
    print("=" * 80)
    for key, value in audit.items():
        print(f"{key:32s} {value}")
    print(f"\nSorties : {output_dir}")
    print(f"Manifeste combine (tous polluants) : {output_dir / 'all_pollutants_pmids.txt'}")

    logger.info("Audit : %s", audit)
    logger.info("CTD EXPOSURE CANDIDATES COMPLETE")


if __name__ == "__main__":
    main()
