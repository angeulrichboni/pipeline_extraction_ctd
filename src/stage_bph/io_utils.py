from __future__ import annotations

import csv
import gzip
from pathlib import Path
from typing import IO


def open_text_output(path: Path, gzip_output: bool) -> IO[str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if gzip_output:
        return gzip.open(path, "wt", encoding="utf-8", newline="")
    return path.open("w", encoding="utf-8", newline="")


def csv_writer(handle: IO[str]) -> csv.writer:
    return csv.writer(handle, lineterminator="\n")
