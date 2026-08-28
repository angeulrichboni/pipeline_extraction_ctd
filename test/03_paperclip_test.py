#!/usr/bin/env python3
"""
Test Paperclip sur les PMIDs du prototype.

Entrée:
    data/prototype/documents_manifest_test.csv

Sorties:
    data/prototype/paperclip/paperclip_test_results.jsonl
    data/prototype/paperclip/paperclip_test_audit.json
    data/prototype/paperclip/paperclip_failed.json
    data/prototype/paperclip/documents_manifest_test_with_paperclip.csv
    data/prototype/paperclip/full_texts/{pmid}.txt
    data/prototype/paperclip/raw/{pmid}_content_raw.txt

Objectif:
    Valider la brique:
        documents_manifest_test.csv
            -> Paperclip
            -> full text via /papers/{PMC}/content.lines

Décision v1:
    - Paperclip est utilisé uniquement pour récupérer le full text.
    - Les sections, tables et metadata natives Paperclip ne sont pas utilisées.
    - Si Paperclip échoue, l'article reste utilisable avec l'abstract PubMed.
"""

import argparse
import json
import logging
import re
import subprocess
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------

PAPERCLIP_CMD = "paperclip"

PROTOTYPE_DIR = Path("data/prototype")
MANIFEST_PATH = PROTOTYPE_DIR / "documents_manifest_test.csv"

OUT_DIR = PROTOTYPE_DIR / "paperclip"
FULL_TEXT_DIR = OUT_DIR / "full_texts"
RAW_DIR = OUT_DIR / "raw"

RESULTS_JSONL = OUT_DIR / "paperclip_test_results.jsonl"
AUDIT_JSON = OUT_DIR / "paperclip_test_audit.json"
FAILED_JSON = OUT_DIR / "paperclip_failed.json"
UPDATED_MANIFEST = OUT_DIR / "documents_manifest_test_with_paperclip.csv"
LOG_FILE = OUT_DIR / "paperclip_test.log"

CAT_TIMEOUT = 120
SLEEP_BETWEEN = 0.2
MIN_CONTENT_CHARS = 100


# ---------------------------------------------------------------------
# Initialisation dossiers
# ---------------------------------------------------------------------

for path in [OUT_DIR, FULL_TEXT_DIR, RAW_DIR]:
    path.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------
# Utilitaires CLI
# ---------------------------------------------------------------------

def run_cli(args: list[str], timeout: int) -> tuple[int | None, str, str]:
    """
    Exécute une commande shell sans shell=True.

    Retour:
        returncode, stdout, stderr
    """
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        return result.returncode, result.stdout or "", result.stderr or ""

    except subprocess.TimeoutExpired:
        return None, "", "TIMEOUT"

    except Exception as exc:
        return None, "", str(exc)


def has_paperclip_error(stdout: str, stderr: str) -> bool:
    """
    Détecte les vraies erreurs Paperclip/VSH.

    Important:
        Ne pas chercher des motifs comme "not found" dans tout le full text,
        car un article scientifique peut contenir cette expression normalement.

    On vérifie seulement:
        - les premières lignes;
        - les erreurs explicites Paperclip/VSH.
    """
    text = f"{stdout or ''}\n{stderr or ''}".strip()
    first_lines = "\n".join(text.splitlines()[:10])

    hard_error_patterns = [
        "ERR:",
        "[exit 1]",
        "[exit 2]",
        "TIMEOUT",
        "Slab service unavailable",
        "Cannot list path",
        "Cannot read path",
        "No such file or directory",
    ]

    return any(
        pattern.lower() in first_lines.lower()
        for pattern in hard_error_patterns
    )


def check_paperclip_available() -> None:
    """
    Vérifie que la commande Paperclip est disponible.
    """
    code, stdout, stderr = run_cli([PAPERCLIP_CMD, "--version"], timeout=10)

    raw = f"{stdout or ''}\n{stderr or ''}".strip()

    if code is None:
        raise RuntimeError("Paperclip command timed out.")

    if code != 0:
        raise RuntimeError(
            f"Paperclip not available. code={code}, stdout={stdout}, stderr={stderr}"
        )

    if not raw:
        raise RuntimeError("Paperclip command returned no version output.")

    log.info(f"Paperclip version: {raw}")


# ---------------------------------------------------------------------
# Nettoyage et parsing
# ---------------------------------------------------------------------

def normalize_pmc_id(value: str) -> str:
    """
    Normalise un PMCID.

    Exemples:
        2831931    -> PMC2831931
        PMC2831931 -> PMC2831931
    """
    value = str(value).strip()

    if not value or value.lower() == "nan":
        return ""

    if value.upper().startswith("PMC"):
        return "PMC" + value[3:].strip()

    return f"PMC{value}"


def is_non_empty(value: Any) -> bool:
    value = str(value).strip()
    return bool(value) and value.lower() != "nan"


def clean_paperclip_output(raw: str) -> str:
    """
    Nettoie la sortie de:
        paperclip cat --full /papers/{PMC}/content.lines

    Paperclip renvoie souvent des lignes préfixées:
        L1: ...
        L2: ...

    On garde le contenu mais on retire:
        - les préfixes L123:
        - les lignes de logs;
        - les lignes d'erreur.
    """
    lines = []

    for line in raw.splitlines():
        stripped = line.strip()

        if not stripped:
            continue

        if stripped.startswith("[paperclip]"):
            continue

        if stripped.startswith("→"):
            continue

        if stripped.startswith("cat --full"):
            continue

        if stripped.startswith("cat /papers/"):
            continue

        if stripped.startswith("grep "):
            continue

        if stripped.startswith("ERR:"):
            continue

        if "[exit 1]" in stripped or "[exit 2]" in stripped:
            continue

        # Supprime les préfixes L1:, L25:, etc.
        cleaned = re.sub(r"^L\d+:\s*", "", stripped).strip()

        if cleaned:
            lines.append(cleaned)

    return "\n".join(lines).strip()


# ---------------------------------------------------------------------
# Paperclip
# ---------------------------------------------------------------------

def paperclip_cat_content(pmc_id: str) -> tuple[str, str | None, str]:
    """
    Récupère le full text via:
        /papers/{PMC}/content.lines

    Retour:
        content, error, raw_output
    """
    pmc_id = normalize_pmc_id(pmc_id)
    path = f"/papers/{pmc_id}/content.lines"

    code, stdout, stderr = run_cli(
        [PAPERCLIP_CMD, "cat", "--full", path],
        timeout=CAT_TIMEOUT,
    )

    raw = (stdout or "") + ("\n" + stderr if stderr else "")

    if code is None:
        return "", "timeout", raw

    if code != 0 or has_paperclip_error(stdout, stderr):
        detail = raw.strip()[:500] or f"exit_code_{code}"
        return "", f"cat_failed:{detail}", raw

    content = clean_paperclip_output(stdout)

    if not content:
        return "", "empty_after_parse", raw

    if len(content) < MIN_CONTENT_CHARS:
        return "", f"too_short:{len(content)}", raw

    return content, None, raw


def fetch_article_from_paperclip(pmid: str, pmc_id: str) -> dict[str, Any]:
    """
    Récupère un article Paperclip.

    Pour la v1:
        - seulement content.lines
        - pas de sections natives
        - pas de tables natives
    """
    pmc_id = normalize_pmc_id(pmc_id)

    result: dict[str, Any] = {
        "pmid": str(pmid),
        "pmc_id": pmc_id,
        "paperclip_id": pmc_id,
        "retrieved_at": datetime.now().isoformat(timespec="seconds"),

        "status": None,
        "error": None,
        "warnings": [],

        "full_text": None,
        "paperclip_content_chars": 0,
        "full_text_path": "",
        "raw_content_path": "",
    }

    content, error, raw = paperclip_cat_content(pmc_id)

    raw_path = RAW_DIR / f"{pmid}_content_raw.txt"
    with open(raw_path, "w", encoding="utf-8") as f:
        f.write(raw)

    result["raw_content_path"] = str(raw_path)

    if error:
        result["status"] = f"failed:{error}"
        result["error"] = error
        return result

    full_text_path = FULL_TEXT_DIR / f"{pmid}.txt"
    with open(full_text_path, "w", encoding="utf-8") as f:
        f.write(content)

    result["status"] = "success"
    result["full_text"] = content
    result["paperclip_content_chars"] = len(content)
    result["full_text_path"] = str(full_text_path)

    return result


# ---------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------

def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    """
    Écrit une liste de dictionnaires en JSONL.
    """
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False))
            f.write("\n")


def load_manifest(path: Path) -> pd.DataFrame:
    """
    Charge le manifest documentaire.
    """
    if not path.exists():
        raise FileNotFoundError(f"Missing manifest: {path}")

    manifest = pd.read_csv(path, dtype=str).fillna("")

    required_cols = ["pmid", "pmc_id"]

    for col in required_cols:
        if col not in manifest.columns:
            raise ValueError(f"Manifest must contain column: {col}")

    manifest["pmid"] = manifest["pmid"].astype(str).str.strip()
    manifest["pmc_id"] = manifest["pmc_id"].apply(normalize_pmc_id)

    return manifest


def clean_previous_outputs(fresh: bool) -> None:
    """
    Supprime les sorties précédentes si --fresh.
    """
    if not fresh:
        return

    for path in [
        RESULTS_JSONL,
        AUDIT_JSON,
        FAILED_JSON,
        UPDATED_MANIFEST,
    ]:
        if path.exists():
            path.unlink()

    for folder in [FULL_TEXT_DIR, RAW_DIR]:
        for file_path in folder.glob("*"):
            if file_path.is_file():
                file_path.unlink()


def compact_result_for_jsonl(obj: dict[str, Any], include_full_text: bool) -> dict[str, Any]:
    """
    Par défaut, le JSONL peut inclure ou exclure le full_text.

    Pour éviter des fichiers énormes, on peut sauvegarder seulement le chemin.
    """
    if include_full_text:
        return obj

    compact = obj.copy()
    compact.pop("full_text", None)
    return compact


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Paperclip prototype full-text test.")

    parser.add_argument(
        "--manifest",
        default=str(MANIFEST_PATH),
        help="Path to documents_manifest_test.csv",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional limit on number of PMCID articles to fetch.",
    )

    parser.add_argument(
        "--sleep",
        type=float,
        default=SLEEP_BETWEEN,
        help="Sleep between Paperclip article fetches.",
    )

    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Delete previous prototype Paperclip outputs before running.",
    )

    parser.add_argument(
        "--include-full-text-in-jsonl",
        action="store_true",
        help="Store full_text directly inside JSONL. Default: store only file paths.",
    )

    args = parser.parse_args()

    manifest_path = Path(args.manifest)

    clean_previous_outputs(args.fresh)

    log.info("=" * 80)
    log.info("PAPERCLIP TEST FETCH — FULL TEXT ONLY")
    log.info("=" * 80)

    check_paperclip_available()

    manifest = load_manifest(manifest_path)

    candidates = manifest[manifest["pmc_id"].apply(is_non_empty)].copy()

    if args.limit is not None:
        candidates = candidates.head(args.limit).copy()

    log.info(f"Manifest rows: {len(manifest)}")
    log.info(f"PMCID candidates: {len(candidates)}")

    results = []

    for _, row in candidates.iterrows():
        pmid = row["pmid"]
        pmc_id = row["pmc_id"]

        log.info(f"[{len(results) + 1}/{len(candidates)}] PMID={pmid} PMC={pmc_id}")

        try:
            obj = fetch_article_from_paperclip(pmid=pmid, pmc_id=pmc_id)

        except Exception as exc:
            obj = {
                "pmid": pmid,
                "pmc_id": pmc_id,
                "paperclip_id": pmc_id,
                "retrieved_at": datetime.now().isoformat(timespec="seconds"),

                "status": "failed:error",
                "error": str(exc),
                "warnings": [],

                "full_text": None,
                "paperclip_content_chars": 0,
                "full_text_path": "",
                "raw_content_path": "",
            }

        results.append(obj)

        if obj["status"] == "success":
            log.info(
                "  OK — chars=%s path=%s",
                f"{obj['paperclip_content_chars']:,}",
                obj["full_text_path"],
            )
        else:
            log.warning(f"  {obj['status']} — {obj.get('error')}")

        time.sleep(args.sleep)

    # JSONL
    jsonl_rows = [
        compact_result_for_jsonl(
            obj,
            include_full_text=args.include_full_text_in_jsonl,
        )
        for obj in results
    ]

    write_jsonl(RESULTS_JSONL, jsonl_rows)

    # Failed JSON
    failed = {
        obj["pmid"]: {
            "pmc_id": obj.get("pmc_id"),
            "status": obj.get("status"),
            "error": obj.get("error"),
            "raw_content_path": obj.get("raw_content_path"),
        }
        for obj in results
        if obj.get("status") != "success"
    }

    with open(FAILED_JSON, "w", encoding="utf-8") as f:
        json.dump(failed, f, ensure_ascii=False, indent=2)

    # Mise à jour du manifest
    result_by_pmid = {obj["pmid"]: obj for obj in results}

    manifest["paperclip_attempted"] = manifest["pmid"].isin(result_by_pmid)

    manifest["paperclip_status"] = manifest["pmid"].map(
        lambda pmid: result_by_pmid.get(pmid, {}).get("status", "not_attempted")
    )

    manifest["has_full_text"] = manifest["pmid"].map(
        lambda pmid: result_by_pmid.get(pmid, {}).get("status") == "success"
    )

    manifest["paperclip_content_chars"] = manifest["pmid"].map(
        lambda pmid: result_by_pmid.get(pmid, {}).get("paperclip_content_chars", 0)
    )

    manifest["full_text_path"] = manifest["pmid"].map(
        lambda pmid: result_by_pmid.get(pmid, {}).get("full_text_path", "")
    )

    manifest["raw_content_path"] = manifest["pmid"].map(
        lambda pmid: result_by_pmid.get(pmid, {}).get("raw_content_path", "")
    )

    manifest.to_csv(UPDATED_MANIFEST, index=False)

    # Audit
    status_counter = Counter(obj["status"] for obj in results)
    successful_results = [obj for obj in results if obj["status"] == "success"]

    if successful_results:
        content_lengths = [
            obj.get("paperclip_content_chars", 0)
            for obj in successful_results
        ]

        avg_content_chars = sum(content_lengths) / len(content_lengths)
        min_content_chars = min(content_lengths)
        max_content_chars = max(content_lengths)

    else:
        avg_content_chars = 0
        min_content_chars = 0
        max_content_chars = 0

    audit = {
        "run_date": datetime.now().isoformat(timespec="seconds"),
        "mode": "paperclip_full_text_only",
        "input_manifest": str(manifest_path),

        "manifest_rows": int(len(manifest)),
        "pmcid_candidates": int(len(candidates)),
        "attempted": int(len(results)),
        "success": int(len(successful_results)),
        "failed": int(len(results) - len(successful_results)),

        "articles_without_pmcid": int(
            len(manifest) - manifest["pmc_id"].apply(is_non_empty).sum()
        ),

        "status_distribution": dict(status_counter),

        "avg_content_chars": avg_content_chars,
        "min_content_chars": min_content_chars,
        "max_content_chars": max_content_chars,

        "outputs": {
            "jsonl": str(RESULTS_JSONL),
            "failed": str(FAILED_JSON),
            "updated_manifest": str(UPDATED_MANIFEST),
            "full_text_dir": str(FULL_TEXT_DIR),
            "raw_dir": str(RAW_DIR),
        },

        "decision": {
            "paperclip_source": "/papers/{PMC}/content.lines",
            "native_sections_used": False,
            "native_tables_used": False,
            "failed_paperclip_articles_fallback": "abstract_only",
        },
    }

    with open(AUDIT_JSON, "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)

    log.info("=" * 80)
    log.info("PAPERCLIP TEST FETCH COMPLETE")
    log.info(json.dumps(audit, indent=2, ensure_ascii=False))
    log.info("=" * 80)


if __name__ == "__main__":
    main()