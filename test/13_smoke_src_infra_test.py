#!/usr/bin/env python3
"""
Smoke test for src infrastructure.
"""

from src.config.settings import settings
from src.config.paths import paths
from src.io.json_io import write_json, read_json
from src.io.csv_io import write_csv_rows, read_csv_rows
from src.io.logging_utils import setup_logger


def main() -> None:
    paths.ensure_base_dirs()

    logger = setup_logger(
        name="smoke_src_infra",
        log_file=paths.logs_dir / "smoke_src_infra.log",
    )

    logger.info("=" * 80)
    logger.info("SRC INFRA SMOKE TEST")
    logger.info("=" * 80)

    logger.info(f"Project root: {settings.project_root}")
    logger.info(f"ILAAS base URL: {settings.ilaas_base_url}")
    logger.info(f"ILAAS model: {settings.ilaas_model}")
    logger.info(f"NCBI email configured: {bool(settings.ncbi_email)}")
    logger.info(f"NCBI API key configured: {bool(settings.ncbi_api_key)}")
    logger.info(f"ILAAS API key configured: {bool(settings.ilaas_api_key)}")

    test_json_path = paths.prototype_dir / "_smoke_test.json"
    test_csv_path = paths.prototype_dir / "_smoke_test.csv"

    payload = {
        "status": "ok",
        "project_root": str(settings.project_root),
        "model": settings.ilaas_model,
    }

    write_json(test_json_path, payload)
    loaded_json = read_json(test_json_path)

    rows = [
        {"pmid": "20123607", "status": "ok"},
        {"pmid": "38970158", "status": "ok"},
    ]

    write_csv_rows(test_csv_path, rows, fieldnames=["pmid", "status"])
    loaded_rows = read_csv_rows(test_csv_path)

    assert loaded_json["status"] == "ok"
    assert len(loaded_rows) == 2

    logger.info(f"JSON test file: {test_json_path}")
    logger.info(f"CSV test file: {test_csv_path}")
    logger.info("Smoke test OK")
    logger.info("=" * 80)

    print("=" * 80)
    print("SRC INFRA SMOKE TEST COMPLETE")
    print("=" * 80)
    print(f"Project root: {settings.project_root}")
    print(f"Model: {settings.ilaas_model}")
    print(f"JSON test: {test_json_path}")
    print(f"CSV test: {test_csv_path}")
    print(f"Log: {paths.logs_dir / 'smoke_src_infra.log'}")
    print("=" * 80)


if __name__ == "__main__":
    main()