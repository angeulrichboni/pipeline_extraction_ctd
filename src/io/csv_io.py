"""
CSV helpers.
"""

import csv
from pathlib import Path
from typing import Any


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def read_csv_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing CSV file: {path}")

    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write_csv_rows(
    path: Path,
    rows: list[dict[str, Any]],
    fieldnames: list[str] | None = None,
) -> None:
    ensure_parent_dir(path)

    if fieldnames is None:
        fieldnames = sorted({key for row in rows for key in row.keys()})

    if not fieldnames:
        fieldnames = ["empty"]

    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def write_csv_from_dataclass_dicts(
    path: Path,
    rows: list[dict[str, Any]],
    fieldnames: list[str],
) -> None:
    write_csv_rows(path=path, rows=rows, fieldnames=fieldnames)