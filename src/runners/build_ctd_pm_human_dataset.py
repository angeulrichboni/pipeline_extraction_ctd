"""
CLI runner : construit les tables CTD PM (D052638) filtrees sur les etudes
humaines. Premiere etape du pipeline (voir README section 4.0).
"""

from __future__ import annotations

import argparse
import json

from src.config.paths import paths
from src.io.logging_utils import setup_logger
from src.preprocessing.ctd_pm_human_dataset import build_ctd_pm_human_dataset


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Construit les tables CTD PM (D052638) filtrees sur les etudes humaines."
    )

    parser.add_argument(
        "--raw-dir",
        default=str(paths.raw_dir),
        help="Dossier contenant les CSV CTD_D052638_*.csv bruts.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(paths.processed_dir / "ctd_pm_human"),
        help="Dossier de sortie pour les tables filtrees.",
    )

    args = parser.parse_args()

    paths.ensure_base_dirs()

    logger = setup_logger(
        name="build_ctd_pm_human_dataset",
        log_file=paths.logs_dir / "build_ctd_pm_human_dataset.log",
    )

    from pathlib import Path

    raw_dir = Path(args.raw_dir)
    output_dir = Path(args.output_dir)

    logger.info("=" * 80)
    logger.info("CTD PM HUMAN DATASET")
    logger.info("=" * 80)
    logger.info("raw_dir=%s output_dir=%s", raw_dir, output_dir)

    audit = build_ctd_pm_human_dataset(raw_dir=raw_dir, output_dir=output_dir)

    audit_path = output_dir / "audit.json"
    audit_path.write_text(json.dumps(audit, indent=2, ensure_ascii=False))

    print("=" * 80)
    print("CTD PM HUMAN DATASET")
    print("=" * 80)
    for key, value in audit.items():
        print(f"{key:32s} {value}")
    print(f"\nSorties : {output_dir}")

    logger.info("Audit : %s", audit)
    logger.info("CTD PM HUMAN DATASET COMPLETE")


if __name__ == "__main__":
    main()
