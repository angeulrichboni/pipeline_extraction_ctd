#!/usr/bin/env python3
"""
Inspecte la structure Paperclip pour les PMCID du prototype.

Objectif:
    Comprendre pourquoi sections=0 et tables=0.
    Vérifier quels fichiers/dossiers sont réellement disponibles sous /papers/{PMC}/.
"""

import json
import subprocess
from datetime import datetime
from pathlib import Path

import pandas as pd


PAPERCLIP_CMD = "paperclip"

UPDATED_MANIFEST = Path(
    "data/prototype/paperclip/documents_manifest_test_with_paperclip.csv"
)

OUT_DIR = Path("data/prototype/paperclip/inspect")
OUT_DIR.mkdir(parents=True, exist_ok=True)

OUT_JSON = OUT_DIR / "paperclip_structure_inspection.json"


def run_cli(args: list[str], timeout: int = 30) -> dict:
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        return {
            "cmd": args,
            "returncode": result.returncode,
            "stdout": result.stdout or "",
            "stderr": result.stderr or "",
            "timeout": False,
        }

    except subprocess.TimeoutExpired:
        return {
            "cmd": args,
            "returncode": None,
            "stdout": "",
            "stderr": "TIMEOUT",
            "timeout": True,
        }


def normalize_pmc_id(value: str) -> str:
    value = str(value).strip()

    if not value or value.lower() == "nan":
        return ""

    if value.upper().startswith("PMC"):
        return "PMC" + value[3:].strip()

    return f"PMC{value}"


def inspect_pmc(pmid: str, pmc_id: str) -> dict:
    pmc_id = normalize_pmc_id(pmc_id)
    base = f"/papers/{pmc_id}"

    paths_to_ls = [
        base,
        f"{base}/",
        f"{base}/sections",
        f"{base}/sections/",
        f"{base}/tables",
        f"{base}/tables/",
        f"{base}/figures",
        f"{base}/figures/",
        f"{base}/supplementary",
        f"{base}/supplementary/",
    ]

    paths_to_cat = [
        f"{base}/content.lines",
        f"{base}/abstract.lines",
        f"{base}/title.lines",
        f"{base}/metadata.json",
        f"{base}/paper.json",
    ]

    return {
        "pmid": pmid,
        "pmc_id": pmc_id,
        "ls": {
            path: run_cli([PAPERCLIP_CMD, "ls", path], timeout=30)
            for path in paths_to_ls
        },
        "cat_head": {
            path: run_cli(
                [PAPERCLIP_CMD, "cat", "--full", path],
                timeout=60,
            )
            for path in paths_to_cat
        },
    }


def main() -> None:
    if not UPDATED_MANIFEST.exists():
        raise FileNotFoundError(f"Missing manifest: {UPDATED_MANIFEST}")

    manifest = pd.read_csv(UPDATED_MANIFEST, dtype=str).fillna("")
    manifest["pmc_id"] = manifest["pmc_id"].apply(normalize_pmc_id)

    candidates = manifest[
        manifest["pmc_id"].astype(str).str.strip().ne("")
    ].copy()

    results = []

    for _, row in candidates.iterrows():
        pmid = row["pmid"]
        pmc_id = row["pmc_id"]

        print(f"Inspecting PMID={pmid} PMC={pmc_id}")
        results.append(inspect_pmc(pmid, pmc_id))

    payload = {
        "run_date": datetime.now().isoformat(timespec="seconds"),
        "n_articles": len(results),
        "results": results,
    }

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print("=" * 80)
    print("PAPERCLIP STRUCTURE INSPECTION COMPLETE")
    print(f"Output: {OUT_JSON}")
    print("=" * 80)


if __name__ == "__main__":
    main()