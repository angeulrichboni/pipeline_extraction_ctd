#!/usr/bin/env python3
"""
Runner multi-PMID pour le prototype CTD extraction.

Ce script orchestre les agents déjà validés:

    06_pollutant_extractor_agent_test.py
    07_outcome_extractor_agent_test.py
    08_effect_measure_extractor_agent_test.py
    09_association_builder_agent_test.py

Entrées attendues:
    data/prototype/segmented_documents/{pmid}_segmented.json

Sorties finales:
    data/prototype/agent_outputs/multi_pmid_runner/associations_all_test.csv
    data/prototype/agent_outputs/multi_pmid_runner/associations_all_test.json
    data/prototype/agent_outputs/multi_pmid_runner/multi_pmid_audit_test.csv
    data/prototype/agent_outputs/multi_pmid_runner/multi_pmid_audit_test.json

Usage:
    python test/10_multi_pmid_runner_test.py --limit 10

    python test/10_multi_pmid_runner_test.py --pmids 20123607,38970158

    python test/10_multi_pmid_runner_test.py --limit 10 --model mistral-medium-latest
"""

import argparse
import csv
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------

SEGMENTED_DIR = Path("data/prototype/segmented_documents")
SEGMENTED_MANIFEST = SEGMENTED_DIR / "segmented_documents_manifest_test.csv"

AGENT_OUTPUTS_DIR = Path("data/prototype/agent_outputs")

POLLUTANT_OUT_DIR = AGENT_OUTPUTS_DIR / "pollutant_extractor"
OUTCOME_OUT_DIR = AGENT_OUTPUTS_DIR / "outcome_extractor"
EFFECT_OUT_DIR = AGENT_OUTPUTS_DIR / "effect_measure_extractor"
ASSOCIATION_OUT_DIR = AGENT_OUTPUTS_DIR / "association_builder"

RUNNER_OUT_DIR = AGENT_OUTPUTS_DIR / "multi_pmid_runner"
LOG_DIR = RUNNER_OUT_DIR / "logs"

RUNNER_OUT_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

ASSOCIATIONS_ALL_CSV = RUNNER_OUT_DIR / "associations_all_test.csv"
ASSOCIATIONS_ALL_JSON = RUNNER_OUT_DIR / "associations_all_test.json"

AUDIT_CSV = RUNNER_OUT_DIR / "multi_pmid_audit_test.csv"
AUDIT_JSON = RUNNER_OUT_DIR / "multi_pmid_audit_test.json"


# ---------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------

def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_json(path: Path, obj: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(obj, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def safe_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    return []


def safe_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value

    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def safe_int(value: Any) -> int:
    try:
        return int(value)
    except Exception:
        return 0


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------------
# PMID discovery
# ---------------------------------------------------------------------

def discover_pmids_from_manifest() -> list[str]:
    if not SEGMENTED_MANIFEST.exists():
        return []

    pmids: list[str] = []

    with SEGMENTED_MANIFEST.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)

        if "pmid" not in reader.fieldnames:
            return []

        for row in reader:
            pmid = str(row.get("pmid", "")).strip()
            if pmid:
                pmids.append(pmid)

    return sorted(set(pmids))


def discover_pmids_from_segmented_files() -> list[str]:
    pmids = []

    for path in SEGMENTED_DIR.glob("*_segmented.json"):
        pmid = path.name.replace("_segmented.json", "").strip()
        if pmid.isdigit():
            pmids.append(pmid)

    return sorted(set(pmids))


def resolve_pmids(args: argparse.Namespace) -> list[str]:
    if args.pmids:
        pmids = [
            item.strip()
            for item in args.pmids.split(",")
            if item.strip()
        ]
    else:
        pmids = discover_pmids_from_manifest()

        if not pmids:
            pmids = discover_pmids_from_segmented_files()

    if args.limit is not None:
        pmids = pmids[: args.limit]

    if not pmids:
        raise ValueError(
            "No PMIDs found. Provide --pmids or ensure segmented documents exist."
        )

    return pmids


# ---------------------------------------------------------------------
# Subprocess runner
# ---------------------------------------------------------------------

def run_command(
    command: list[str],
    log_prefix: str,
    continue_on_error: bool,
) -> dict[str, Any]:
    stdout_path = LOG_DIR / f"{log_prefix}.stdout.log"
    stderr_path = LOG_DIR / f"{log_prefix}.stderr.log"

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    started_at = now_iso()

    completed = subprocess.run(
        command,
        text=True,
        capture_output=True,
        env=env,
    )

    finished_at = now_iso()

    stdout_path.write_text(completed.stdout or "", encoding="utf-8")
    stderr_path.write_text(completed.stderr or "", encoding="utf-8")

    result = {
        "command": command,
        "returncode": completed.returncode,
        "started_at": started_at,
        "finished_at": finished_at,
        "stdout_log": str(stdout_path),
        "stderr_log": str(stderr_path),
    }

    if completed.returncode != 0 and not continue_on_error:
        raise RuntimeError(
            f"Command failed with return code {completed.returncode}: "
            f"{' '.join(command)}\n"
            f"stderr log: {stderr_path}"
        )

    return result


def check_script_exists(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Missing script: {path}")


# ---------------------------------------------------------------------
# Output collection
# ---------------------------------------------------------------------

def pollutant_output_path(pmid: str) -> Path:
    return POLLUTANT_OUT_DIR / f"{pmid}_pollutants.json"


def outcome_output_path(pmid: str) -> Path:
    return OUTCOME_OUT_DIR / f"{pmid}_outcomes.json"


def effect_output_path(pmid: str) -> Path:
    return EFFECT_OUT_DIR / f"{pmid}_effect_measures.json"


def association_output_path(pmid: str) -> Path:
    return ASSOCIATION_OUT_DIR / f"{pmid}_associations.json"


def association_csv_path(pmid: str) -> Path:
    return ASSOCIATION_OUT_DIR / f"{pmid}_associations.csv"


def summarize_pmid_outputs(pmid: str) -> dict[str, Any]:
    pollutant_payload = read_json(pollutant_output_path(pmid))
    outcome_payload = read_json(outcome_output_path(pmid))
    effect_payload = read_json(effect_output_path(pmid))
    association_payload = read_json(association_output_path(pmid))

    pollutants = safe_list(pollutant_payload.get("pollutants_found"))
    outcomes = safe_list(outcome_payload.get("outcomes_found"))
    effects = safe_list(effect_payload.get("effect_measures_found"))
    associations = safe_list(association_payload.get("associations"))

    kept_effects = [
        item for item in effects
        if safe_bool(item.get("keep_for_association_builder"))
    ]

    main_associations = [
        item for item in associations
        if safe_bool(
            item.get("classification", {}).get("include_in_main_project_analysis")
        )
    ]

    contextual_associations = [
        item for item in associations
        if item.get("classification", {}).get("association_role")
        == "contextual_direct_association"
    ]

    all_warnings = (
        safe_list(pollutant_payload.get("warnings"))
        + safe_list(outcome_payload.get("warnings"))
        + safe_list(effect_payload.get("warnings"))
        + safe_list(association_payload.get("warnings"))
    )

    all_errors = (
        safe_list(pollutant_payload.get("errors"))
        + safe_list(outcome_payload.get("errors"))
        + safe_list(effect_payload.get("errors"))
        + safe_list(association_payload.get("errors"))
    )

    return {
        "pmid": pmid,

        "pollutants_found": len(pollutants),
        "outcomes_found": len(outcomes),
        "effect_measures_found": len(effects),
        "kept_effect_measures": len(kept_effects),

        "associations_built": len(associations),
        "main_project_associations": len(main_associations),
        "contextual_direct_associations": len(contextual_associations),

        "warnings_total": len(all_warnings),
        "errors_total": len(all_errors),

        "pollutant_errors": len(safe_list(pollutant_payload.get("errors"))),
        "outcome_errors": len(safe_list(outcome_payload.get("errors"))),
        "effect_errors": len(safe_list(effect_payload.get("errors"))),
        "association_errors": len(safe_list(association_payload.get("errors"))),

        "pollutant_output": str(pollutant_output_path(pmid)),
        "outcome_output": str(outcome_output_path(pmid)),
        "effect_output": str(effect_output_path(pmid)),
        "association_output": str(association_output_path(pmid)),
        "association_csv": str(association_csv_path(pmid)),
    }


# ---------------------------------------------------------------------
# Merge associations
# ---------------------------------------------------------------------

def read_csv_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader)


def write_csv_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = sorted(
        {
            key
            for row in rows
            for key in row.keys()
        }
    )

    if not fieldnames:
        fieldnames = ["pmid"]

    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for row in rows:
            writer.writerow(row)


def merge_association_csvs(pmids: list[str]) -> list[dict[str, Any]]:
    all_rows = []

    for pmid in pmids:
        rows = read_csv_rows(association_csv_path(pmid))
        all_rows.extend(rows)

    write_csv_rows(ASSOCIATIONS_ALL_CSV, all_rows)

    return all_rows


def merge_association_jsons(pmids: list[str]) -> list[dict[str, Any]]:
    all_associations = []

    for pmid in pmids:
        payload = read_json(association_output_path(pmid))
        associations = safe_list(payload.get("associations"))
        all_associations.extend(associations)

    return all_associations


# ---------------------------------------------------------------------
# Audit writing
# ---------------------------------------------------------------------

AUDIT_COLUMNS = [
    "pmid",
    "pollutants_found",
    "outcomes_found",
    "effect_measures_found",
    "kept_effect_measures",
    "associations_built",
    "main_project_associations",
    "contextual_direct_associations",
    "warnings_total",
    "errors_total",
    "pollutant_errors",
    "outcome_errors",
    "effect_errors",
    "association_errors",
    "pollutant_output",
    "outcome_output",
    "effect_output",
    "association_output",
    "association_csv",
]


def write_audit_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=AUDIT_COLUMNS)
        writer.writeheader()

        for row in rows:
            writer.writerow(
                {
                    col: row.get(col, "")
                    for col in AUDIT_COLUMNS
                }
            )


# ---------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------

def run_pipeline_for_pmid(
    pmid: str,
    scripts_dir: Path,
    model: str,
    continue_on_error: bool,
    skip_existing_associations: bool,
) -> dict[str, Any]:
    association_json = association_output_path(pmid)

    if skip_existing_associations and association_json.exists():
        return {
            "pmid": pmid,
            "skipped": True,
            "reason": "association_output_exists",
            "commands": [],
        }

    script_06 = scripts_dir / "06_pollutant_extractor_agent_test.py"
    script_07 = scripts_dir / "07_outcome_extractor_agent_test.py"
    script_08 = scripts_dir / "08_effect_measure_extractor_agent_test.py"
    script_09 = scripts_dir / "09_association_builder_agent_test.py"

    for script in [script_06, script_07, script_08, script_09]:
        check_script_exists(script)

    commands = [
        {
            "step": "pollutant_extractor",
            "command": [
                sys.executable,
                str(script_06),
                "--pmid",
                pmid,
                "--model",
                model,
            ],
        },
        {
            "step": "outcome_extractor",
            "command": [
                sys.executable,
                str(script_07),
                "--pmid",
                pmid,
                "--model",
                model,
            ],
        },
        {
            "step": "effect_measure_extractor",
            "command": [
                sys.executable,
                str(script_08),
                "--pmid",
                pmid,
                "--model",
                model,
            ],
        },
        {
            "step": "association_builder",
            "command": [
                sys.executable,
                str(script_09),
                "--pmid",
                pmid,
            ],
        },
    ]

    command_results = []

    for item in commands:
        step = item["step"]
        command = item["command"]

        print(f"[{pmid}] Running {step}...")

        result = run_command(
            command=command,
            log_prefix=f"{pmid}_{step}",
            continue_on_error=continue_on_error,
        )

        command_results.append(
            {
                "step": step,
                **result,
            }
        )

        if result["returncode"] != 0 and continue_on_error:
            print(f"[{pmid}] {step} failed, continuing due to --continue-on-error")
            break

    return {
        "pmid": pmid,
        "skipped": False,
        "commands": command_results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run all extraction agents on multiple PMIDs."
    )

    parser.add_argument(
        "--pmids",
        default="",
        help="Comma-separated PMIDs. If omitted, read segmented manifest.",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of PMIDs to process.",
    )

    parser.add_argument(
        "--model",
        default=os.getenv("ILAAS_MODEL", "mistral-medium-latest"),
        help="ILAAS model to use for LLM agents.",
    )

    parser.add_argument(
        "--scripts-dir",
        default="test",
        help="Directory containing agent scripts. Default: test",
    )

    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Continue processing next PMID if one command fails.",
    )

    parser.add_argument(
        "--skip-existing-associations",
        action="store_true",
        help="Skip a PMID if its association JSON already exists.",
    )

    args = parser.parse_args()

    scripts_dir = Path(args.scripts_dir)

    pmids = resolve_pmids(args)

    print("=" * 80)
    print("MULTI-PMID RUNNER START")
    print("=" * 80)
    print(f"PMIDs: {len(pmids)}")
    print(f"Model: {args.model}")
    print(f"Scripts dir: {scripts_dir}")
    print(f"Continue on error: {args.continue_on_error}")
    print(f"Skip existing associations: {args.skip_existing_associations}")
    print("=" * 80)

    run_results = []

    for i, pmid in enumerate(pmids, start=1):
        print(f"\n[{i}/{len(pmids)}] PMID={pmid}")
        print("-" * 80)

        result = run_pipeline_for_pmid(
            pmid=pmid,
            scripts_dir=scripts_dir,
            model=args.model,
            continue_on_error=args.continue_on_error,
            skip_existing_associations=args.skip_existing_associations,
        )

        run_results.append(result)

    print("\nCollecting outputs...")
    print("-" * 80)

    audit_rows = [
        summarize_pmid_outputs(pmid)
        for pmid in pmids
    ]

    write_audit_csv(AUDIT_CSV, audit_rows)

    all_csv_rows = merge_association_csvs(pmids)
    all_associations = merge_association_jsons(pmids)

    total_warnings = sum(safe_int(row.get("warnings_total")) for row in audit_rows)
    total_errors = sum(safe_int(row.get("errors_total")) for row in audit_rows)

    total_associations = sum(
        safe_int(row.get("associations_built"))
        for row in audit_rows
    )

    total_main = sum(
        safe_int(row.get("main_project_associations"))
        for row in audit_rows
    )

    total_contextual = sum(
        safe_int(row.get("contextual_direct_associations"))
        for row in audit_rows
    )

    audit_payload = {
        "run_date": now_iso(),
        "model": args.model,
        "scripts_dir": str(scripts_dir),
        "pmids_requested": pmids,
        "n_pmids": len(pmids),

        "totals": {
            "associations_built": total_associations,
            "main_project_associations": total_main,
            "contextual_direct_associations": total_contextual,
            "warnings_total": total_warnings,
            "errors_total": total_errors,
        },

        "outputs": {
            "associations_all_csv": str(ASSOCIATIONS_ALL_CSV),
            "associations_all_json": str(ASSOCIATIONS_ALL_JSON),
            "audit_csv": str(AUDIT_CSV),
            "audit_json": str(AUDIT_JSON),
            "logs_dir": str(LOG_DIR),
        },

        "run_results": run_results,
        "per_pmid": audit_rows,
    }

    write_json(
        ASSOCIATIONS_ALL_JSON,
        {
            "created_at": now_iso(),
            "n_associations": len(all_associations),
            "associations": all_associations,
        },
    )

    write_json(AUDIT_JSON, audit_payload)

    print("=" * 80)
    print("MULTI-PMID RUNNER COMPLETE")
    print("=" * 80)
    print(f"PMIDs processed: {len(pmids)}")
    print(f"Associations built: {total_associations}")
    print(f"Main project associations: {total_main}")
    print(f"Contextual direct associations: {total_contextual}")
    print(f"Warnings: {total_warnings}")
    print(f"Errors: {total_errors}")
    print(f"Associations CSV: {ASSOCIATIONS_ALL_CSV}")
    print(f"Associations JSON: {ASSOCIATIONS_ALL_JSON}")
    print(f"Audit CSV: {AUDIT_CSV}")
    print(f"Audit JSON: {AUDIT_JSON}")
    print(f"Logs: {LOG_DIR}")
    print("=" * 80)

    print("Per-PMID summary")
    print("-" * 80)

    for row in audit_rows:
        print(
            f"{row['pmid']} | "
            f"pollutants={row['pollutants_found']} | "
            f"outcomes={row['outcomes_found']} | "
            f"effects={row['effect_measures_found']} | "
            f"kept_effects={row['kept_effect_measures']} | "
            f"associations={row['associations_built']} | "
            f"main={row['main_project_associations']} | "
            f"contextual={row['contextual_direct_associations']} | "
            f"warnings={row['warnings_total']} | "
            f"errors={row['errors_total']}"
        )


if __name__ == "__main__":
    main()