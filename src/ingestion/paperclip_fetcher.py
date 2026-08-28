"""Fetch and validate Paperclip full text from PMCIDs."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from src.config.settings import settings
from src.io.csv_io import read_csv_rows, write_csv_rows
from src.io.json_io import read_json_or_empty, write_json
from src.ingestion.europepmc_fetcher import fetch_one_europepmc_document


# Defaults

DEFAULT_TIMEOUT_SECONDS = 120
DEFAULT_MAX_RETRIES = 3
DEFAULT_SLEEP_SECONDS = 1.0
DEFAULT_PAPERCLIP_COMMAND = "paperclip"

# Important quality guard:
# Very short "full texts" are usually empty pages, service messages,
# headers, or non-article fragments. They must not be treated as full text.
MIN_FULL_TEXT_CHARS = 1000


# Generic helpers

def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def safe_str(value: Any) -> str:
    if value is None:
        return ""

    text = str(value).strip()

    if text.lower() in {"nan", "none", "null", "not available", "n/a"}:
        return ""

    return text


def safe_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value

    text = safe_str(value).lower()

    return text in {"true", "1", "yes", "y"}


def strip_line_prefix(line: str) -> str:
    """Strip common Paperclip line prefixes."""
    line = safe_str(line)
    line = re.sub(r"^\s*L\d+\s*:\s*", "", line)
    line = re.sub(r"^\s*\d+\s*:\s*", "", line)

    return line.strip()


def clean_text(text: str) -> str:
    if not text:
        return ""

    text = text.replace("\u00a0", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    lines = []

    for raw_line in text.splitlines():
        line = strip_line_prefix(raw_line)
        line = " ".join(line.split())

        if line:
            lines.append(line)
        else:
            lines.append("")

    cleaned = "\n".join(lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

    return cleaned.strip()


def is_valid_full_text(text: str, min_chars: int = MIN_FULL_TEXT_CHARS) -> bool:
    """Reject very short Paperclip content as unusable full text."""
    cleaned = clean_text(text)

    return len(cleaned) >= min_chars


def normalize_pmid(value: Any) -> str:
    text = safe_str(value)

    if not text:
        return ""

    digits = re.sub(r"\D", "", text)

    return digits


def normalize_pmc_id(value: Any) -> str:
    text = safe_str(value)

    if not text:
        return ""

    text = text.strip()

    if text.upper().startswith("PMC"):
        digits = re.sub(r"\D", "", text)

        if digits:
            return f"PMC{digits}"

    digits = re.sub(r"\D", "", text)

    if digits:
        return f"PMC{digits}"

    return ""


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []

    if not path.exists():
        return rows

    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()

            if not line:
                continue

            rows.append(json.loads(line))

    return rows


def read_text_or_empty(path: Path | str | None) -> str:
    if path is None:
        return ""

    path_obj = Path(str(path))

    if not path_obj.exists() or not path_obj.is_file():
        return ""

    return path_obj.read_text(encoding="utf-8", errors="ignore")


def get_nested_raw(row: dict[str, Any], path: str) -> Any:
    current: Any = row

    for part in path.split("."):
        if not isinstance(current, dict):
            return None

        current = current.get(part)

    return current


def get_nested_value(row: dict[str, Any], path: str) -> str:
    value = get_nested_raw(row, path)

    if isinstance(value, str) and value.strip():
        return value.strip()

    return ""


def first_value(row: dict[str, Any], keys: list[str]) -> str:
    for key in keys:
        if "." in key:
            value = get_nested_value(row, key)
        else:
            raw_value = row.get(key)

            if isinstance(raw_value, str):
                value = raw_value.strip()
            else:
                value = ""

        if value:
            return value

    return ""


# PubMed and manifest loading

def load_pubmed_index(pubmed_jsonl: Path, pubmed_dir: Path) -> dict[str, dict[str, Any]]:
    """Load PubMed metadata by PMID from JSONL and per-PMID JSON files."""
    index: dict[str, dict[str, Any]] = {}

    if pubmed_jsonl.exists():
        for row in read_jsonl(pubmed_jsonl):
            pmid = normalize_pmid(row.get("pmid"))

            if pmid:
                index[pmid] = row

    if pubmed_dir.exists():
        for path in pubmed_dir.glob("*_pubmed.json"):
            payload = read_json_or_empty(path)
            pmid = normalize_pmid(payload.get("pmid"))

            if pmid and pmid not in index:
                index[pmid] = payload

    return index


def extract_pmid_from_manifest_row(row: dict[str, Any]) -> str:
    return normalize_pmid(
        first_value(
            row,
            [
                "pmid",
                "PMID",
                "pubmed_id",
                "PubMedID",
                "ctd_context.pmid",
            ],
        )
    )


def extract_pmc_id(
    manifest_row: dict[str, Any],
    pubmed_row: dict[str, Any] | None,
) -> str:
    pubmed_row = pubmed_row or {}

    return normalize_pmc_id(
        first_value(
            manifest_row,
            [
                "pmc_id",
                "pmcid",
                "PMC",
                "pubmed.pmc_id",
                "paperclip.pmc_id",
            ],
        )
        or first_value(
            pubmed_row,
            [
                "pmc_id",
                "pmcid",
                "PMC",
            ],
        )
    )


def load_manifest_rows(manifest_path: Path) -> list[dict[str, Any]]:
    if not manifest_path.exists():
        return []

    suffix = manifest_path.suffix.lower()

    if suffix == ".csv":
        return read_csv_rows(manifest_path)

    if suffix == ".jsonl":
        return read_jsonl(manifest_path)

    if suffix == ".json":
        payload = read_json_or_empty(manifest_path)

        if isinstance(payload, list):
            return payload

        if isinstance(payload, dict):
            for key in ["rows", "data", "records"]:
                value = payload.get(key)

                if isinstance(value, list):
                    return value

            return [payload]

    return []


def build_rows_to_process(
    manifest_path: Path,
    pubmed_jsonl: Path,
    pubmed_dir: Path,
    pmids_filter: list[str] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    manifest_rows = load_manifest_rows(manifest_path)
    pubmed_index = load_pubmed_index(pubmed_jsonl, pubmed_dir)

    rows: list[dict[str, Any]] = []

    if manifest_rows:
        for manifest_row in manifest_rows:
            pmid = extract_pmid_from_manifest_row(manifest_row)

            if not pmid:
                continue

            pubmed_row = pubmed_index.get(pmid, {})
            pmc_id = extract_pmc_id(manifest_row, pubmed_row)

            rows.append(
                {
                    "pmid": pmid,
                    "pmc_id": pmc_id,
                    "manifest_row": manifest_row,
                    "pubmed_row": pubmed_row,
                }
            )

    else:
        for pmid, pubmed_row in pubmed_index.items():
            pmc_id = extract_pmc_id({}, pubmed_row)

            rows.append(
                {
                    "pmid": pmid,
                    "pmc_id": pmc_id,
                    "manifest_row": {"pmid": pmid},
                    "pubmed_row": pubmed_row,
                }
            )

    if pmids_filter:
        wanted = set(pmids_filter)
        rows = [row for row in rows if row["pmid"] in wanted]

    if limit is not None:
        rows = rows[:limit]

    return rows


# Paperclip HTTP API

def resolve_paperclip_base_url(base_url: str | None = None) -> str:
    value = (
        safe_str(base_url)
        or safe_str(getattr(settings, "paperclip_base_url", ""))
        or safe_str(os.getenv("PAPERCLIP_BASE_URL"))
    )

    return value.rstrip("/")


def resolve_paperclip_api_key(api_key: str | None = None) -> str:
    return (
        safe_str(api_key)
        or safe_str(getattr(settings, "paperclip_api_key", ""))
        or safe_str(os.getenv("PAPERCLIP_API_KEY"))
    )


def build_headers(api_key: str = "") -> dict[str, str]:
    headers = {
        "Accept": "text/plain, application/json;q=0.9, */*;q=0.8",
    }

    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    return headers


def paperclip_content_url(base_url: str, pmc_id: str) -> str:
    return f"{base_url}/papers/{pmc_id}/content.lines"


def is_retryable_status(status_code: int) -> bool:
    return status_code in {408, 409, 425, 429, 500, 502, 503, 504}


def fetch_paperclip_content_lines_http(
    base_url: str,
    pmc_id: str,
    api_key: str = "",
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    max_retries: int = DEFAULT_MAX_RETRIES,
    sleep_seconds: float = DEFAULT_SLEEP_SECONDS,
) -> tuple[str, dict[str, Any]]:
    if not base_url:
        raise ValueError(
            "Missing Paperclip base URL. Set PAPERCLIP_BASE_URL, "
            "settings.paperclip_base_url, or pass --base-url."
        )

    url = paperclip_content_url(base_url, pmc_id)
    headers = build_headers(api_key)

    last_error: Exception | None = None
    last_status_code = 0

    for attempt in range(1, max_retries + 1):
        try:
            response = requests.get(
                url,
                headers=headers,
                timeout=timeout_seconds,
            )

            last_status_code = response.status_code

            if is_retryable_status(response.status_code):
                if attempt < max_retries:
                    time.sleep(sleep_seconds * attempt)
                    continue

            if response.status_code == 404:
                return "", {
                    "url": url,
                    "status_code": response.status_code,
                    "status": "not_found",
                    "attempts": attempt,
                    "fetch_mode": "http",
                }

            response.raise_for_status()

            return response.text, {
                "url": url,
                "status_code": response.status_code,
                "status": "success",
                "attempts": attempt,
                "fetch_mode": "http",
            }

        except Exception as exc:
            last_error = exc

            if attempt < max_retries:
                time.sleep(sleep_seconds * attempt)
                continue

            raise RuntimeError(
                f"Paperclip HTTP fetch failed for {pmc_id} after "
                f"{max_retries} attempts. "
                f"last_status_code={last_status_code}; error={exc}"
            ) from exc

    raise RuntimeError(
        f"Paperclip HTTP fetch failed for {pmc_id}. "
        f"last_status_code={last_status_code}; error={last_error}"
    )


# Backward-compatible alias if another module still imports this name.
fetch_paperclip_content_lines = fetch_paperclip_content_lines_http


# Paperclip local CLI

def resolve_paperclip_command(command: str | None = None) -> str:
    return (
        safe_str(command)
        or safe_str(getattr(settings, "paperclip_command", ""))
        or safe_str(os.getenv("PAPERCLIP_COMMAND"))
        or DEFAULT_PAPERCLIP_COMMAND
    )


def is_paperclip_cli_available(command: str = DEFAULT_PAPERCLIP_COMMAND) -> bool:
    return shutil.which(command) is not None


def paperclip_cli_path(pmc_id: str) -> str:
    return f"/papers/{pmc_id}/content.lines"


def fetch_paperclip_content_lines_cli(
    pmc_id: str,
    command: str = DEFAULT_PAPERCLIP_COMMAND,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> tuple[str, dict[str, Any]]:
    """Fetch Paperclip content using the local Paperclip CLI."""
    if not is_paperclip_cli_available(command):
        raise RuntimeError(
            f"Paperclip CLI command not found: {command}. "
            "Install Paperclip or set PAPERCLIP_COMMAND."
        )

    path = paperclip_cli_path(pmc_id)

    cmd = [
        command,
        "cat",
        path,
    ]

    completed = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )

    stdout = completed.stdout or ""
    stderr = completed.stderr or ""

    if completed.returncode != 0:
        raise RuntimeError(
            "Paperclip CLI fetch failed. "
            f"returncode={completed.returncode}; "
            f"path={path}; stderr={stderr[:500]}; stdout={stdout[:500]}"
        )

    return stdout, {
        "url": path,
        "status_code": "cli",
        "status": "success",
        "attempts": 1,
        "command": " ".join(cmd),
        "stderr": stderr[:1000],
        "fetch_mode": "cli",
    }


def fetch_paperclip_content_lines_auto(
    pmc_id: str,
    base_url: str = "",
    api_key: str = "",
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    max_retries: int = DEFAULT_MAX_RETRIES,
    sleep_seconds: float = DEFAULT_SLEEP_SECONDS,
) -> tuple[str, dict[str, Any]]:
    """
    Fetch content using HTTP when base_url is provided.
    Otherwise use the local Paperclip CLI.
    """
    if base_url:
        return fetch_paperclip_content_lines_http(
            base_url=base_url,
            pmc_id=pmc_id,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            sleep_seconds=sleep_seconds,
        )

    command = resolve_paperclip_command()

    return fetch_paperclip_content_lines_cli(
        pmc_id=pmc_id,
        command=command,
        timeout_seconds=timeout_seconds,
    )


# Paperclip content parsing

def parse_json_line_item(item: Any) -> str:
    if isinstance(item, str):
        return item

    if isinstance(item, dict):
        for key in ["text", "line", "content", "paragraph"]:
            value = item.get(key)

            if isinstance(value, str) and value.strip():
                return value.strip()

        values = [
            value.strip()
            for value in item.values()
            if isinstance(value, str) and value.strip()
        ]

        return " ".join(values)

    return ""


def parse_content_lines(raw_text: str) -> str:
    """Convert Paperclip /content.lines response to plain full text."""
    raw_text = safe_str(raw_text)

    if not raw_text:
        return ""

    try:
        payload = json.loads(raw_text)

        if isinstance(payload, list):
            lines = [parse_json_line_item(item) for item in payload]
            return clean_text("\n".join(line for line in lines if line))

        if isinstance(payload, dict):
            for key in ["lines", "content_lines", "content"]:
                value = payload.get(key)

                if isinstance(value, list):
                    lines = [parse_json_line_item(item) for item in value]
                    return clean_text("\n".join(line for line in lines if line))

                if isinstance(value, str):
                    return clean_text(value)

            for key in ["text", "full_text"]:
                value = payload.get(key)

                if isinstance(value, str):
                    return clean_text(value)

    except Exception:
        pass

    jsonl_lines = []
    all_jsonl = True

    for line in raw_text.splitlines():
        stripped = line.strip()

        if not stripped:
            continue

        try:
            item = json.loads(stripped)
            parsed = parse_json_line_item(item)

            if parsed:
                jsonl_lines.append(parsed)

        except Exception:
            all_jsonl = False
            break

    if all_jsonl and jsonl_lines:
        return clean_text("\n".join(jsonl_lines))

    return clean_text(raw_text)


# Existing files reuse

def find_existing_full_text_path(
    pmid: str,
    pmc_id: str,
    full_text_dir: Path,
) -> Path | None:
    candidates = [
        full_text_dir / f"{pmid}.txt",
        full_text_dir / f"{pmid}_full_text.txt",
        full_text_dir / f"{pmid}_paperclip_full_text.txt",
    ]

    if pmc_id:
        candidates.extend(
            [
                full_text_dir / f"{pmc_id}.txt",
                full_text_dir / f"{pmc_id}_full_text.txt",
                full_text_dir / f"{pmc_id}_paperclip_full_text.txt",
            ]
        )

    for path in candidates:
        if path.exists() and path.is_file():
            return path

    return None


def find_existing_raw_path(
    pmid: str,
    pmc_id: str,
    raw_dir: Path,
) -> Path | None:
    candidates = [
        raw_dir / f"{pmid}_content_raw.txt",
        raw_dir / f"{pmid}_raw.txt",
    ]

    if pmc_id:
        candidates.extend(
            [
                raw_dir / f"{pmc_id}_content_raw.txt",
                raw_dir / f"{pmc_id}_raw.txt",
            ]
        )

    for path in candidates:
        if path.exists() and path.is_file():
            return path

    return None


def no_full_text_result(
    pmid: str,
    pmc_id: str,
    status: str,
    chars: int = 0,
    fetch_url: str = "",
    http_status_code: str = "",
    error: str = "",
    invalid_content_path: str = "",
    fetch_mode: str = "",
) -> dict[str, Any]:
    """Return a result that cannot be promoted to full_text downstream."""
    return {
        "pmid": pmid,
        "pmc_id": pmc_id,
        "paperclip_attempted": bool(pmc_id),
        "paperclip_status": status,
        "has_full_text": False,
        "full_text_path": "",
        "raw_content_path": "",
        "invalid_content_path": invalid_content_path,
        "paperclip_content_chars": chars,
        "fetch_url": fetch_url,
        "http_status_code": http_status_code,
        "fetch_mode": fetch_mode,
        "error": error,
    }


# One-document fetch

def fetch_one_paperclip_document(
    pmid: str,
    pmc_id: str,
    full_text_dir: Path,
    raw_dir: Path,
    base_url: str = "",
    api_key: str = "",
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    max_retries: int = DEFAULT_MAX_RETRIES,
    sleep_seconds: float = DEFAULT_SLEEP_SECONDS,
    reuse_existing: bool = True,
) -> dict[str, Any]:
    full_text_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    if not pmc_id:
        return {
            "pmid": pmid,
            "pmc_id": pmc_id,
            "paperclip_attempted": False,
            "paperclip_status": "not_attempted",
            "has_full_text": False,
            "full_text_path": "",
            "raw_content_path": "",
            "invalid_content_path": "",
            "paperclip_content_chars": 0,
            "fetch_url": "",
            "http_status_code": "",
            "fetch_mode": "",
            "error": "",
        }

    existing_full_text_path = find_existing_full_text_path(
        pmid=pmid,
        pmc_id=pmc_id,
        full_text_dir=full_text_dir,
    )

    if reuse_existing and existing_full_text_path is not None:
        full_text = clean_text(read_text_or_empty(existing_full_text_path))

        if is_valid_full_text(full_text):
            existing_raw_path = find_existing_raw_path(
                pmid=pmid,
                pmc_id=pmc_id,
                raw_dir=raw_dir,
            )

            return {
                "pmid": pmid,
                "pmc_id": pmc_id,
                "paperclip_attempted": True,
                "paperclip_status": "success",
                "has_full_text": True,
                "full_text_path": str(existing_full_text_path),
                "raw_content_path": str(existing_raw_path) if existing_raw_path else "",
                "invalid_content_path": "",
                "paperclip_content_chars": len(full_text),
                "fetch_url": paperclip_content_url(base_url, pmc_id) if base_url else paperclip_cli_path(pmc_id),
                "http_status_code": "reused",
                "fetch_mode": "reuse_existing",
                "error": "",
            }

        # Invalid short file. Do not return it as full_text.
        # Continue below and try HTTP/CLI fetch again.
        invalid_existing_path = str(existing_full_text_path)
    else:
        invalid_existing_path = ""

    existing_raw_path = find_existing_raw_path(
        pmid=pmid,
        pmc_id=pmc_id,
        raw_dir=raw_dir,
    )

    if reuse_existing and existing_raw_path is not None:
        raw_text = read_text_or_empty(existing_raw_path)
        full_text = parse_content_lines(raw_text)

        if is_valid_full_text(full_text):
            full_text_path = full_text_dir / f"{pmid}.txt"
            full_text_path.write_text(full_text, encoding="utf-8")

            return {
                "pmid": pmid,
                "pmc_id": pmc_id,
                "paperclip_attempted": True,
                "paperclip_status": "success",
                "has_full_text": True,
                "full_text_path": str(full_text_path),
                "raw_content_path": str(existing_raw_path),
                "invalid_content_path": "",
                "paperclip_content_chars": len(full_text),
                "fetch_url": paperclip_content_url(base_url, pmc_id) if base_url else paperclip_cli_path(pmc_id),
                "http_status_code": "reused_raw",
                "fetch_mode": "reuse_raw",
                "error": "",
            }

        # Invalid raw file. Continue below and try HTTP/CLI fetch again.
        invalid_existing_path = str(existing_raw_path)

    raw_text, fetch_metadata = fetch_paperclip_content_lines_auto(
        pmc_id=pmc_id,
        base_url=base_url,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        sleep_seconds=sleep_seconds,
    )

    fetch_url = safe_str(fetch_metadata.get("url"))
    http_status_code = safe_str(fetch_metadata.get("status_code"))
    fetch_mode = safe_str(fetch_metadata.get("fetch_mode"))

    raw_path = raw_dir / f"{pmid}_content_raw.txt"
    raw_path.write_text(raw_text, encoding="utf-8")

    full_text = parse_content_lines(raw_text)

    if not is_valid_full_text(full_text):
        invalid_path = str(raw_path) or invalid_existing_path

        return no_full_text_result(
            pmid=pmid,
            pmc_id=pmc_id,
            status="no_full_text",
            chars=len(full_text),
            fetch_url=fetch_url,
            http_status_code=http_status_code,
            invalid_content_path=invalid_path,
            fetch_mode=fetch_mode,
            error=(
                f"Fetched Paperclip content is too short "
                f"({len(full_text)} chars < {MIN_FULL_TEXT_CHARS})."
            ),
        )

    full_text_path = full_text_dir / f"{pmid}.txt"
    full_text_path.write_text(full_text, encoding="utf-8")

    return {
        "pmid": pmid,
        "pmc_id": pmc_id,
        "paperclip_attempted": True,
        "paperclip_status": "success",
        "has_full_text": True,
        "full_text_path": str(full_text_path),
        "raw_content_path": str(raw_path),
        "invalid_content_path": "",
        "paperclip_content_chars": len(full_text),
        "fetch_url": fetch_url,
        "http_status_code": http_status_code,
        "fetch_mode": fetch_mode,
        "error": "",
    }


# Manifest enrichment

def merge_manifest_with_paperclip(
    input_row: dict[str, Any],
    pubmed_row: dict[str, Any],
    paperclip_result: dict[str, Any],
) -> dict[str, Any]:
    output = dict(input_row)

    pmid = safe_str(paperclip_result.get("pmid"))
    pmc_id = safe_str(paperclip_result.get("pmc_id"))

    if "pmid" not in output:
        output["pmid"] = pmid

    output["pmc_id"] = pmc_id or safe_str(pubmed_row.get("pmc_id"))

    output["paperclip_attempted"] = paperclip_result["paperclip_attempted"]
    output["paperclip_status"] = paperclip_result["paperclip_status"]
    output["has_full_text"] = paperclip_result["has_full_text"]
    output["full_text_path"] = paperclip_result["full_text_path"]
    output["raw_content_path"] = paperclip_result["raw_content_path"]
    output["invalid_content_path"] = paperclip_result.get("invalid_content_path", "")
    output["paperclip_content_chars"] = paperclip_result["paperclip_content_chars"]
    output["fetch_url"] = paperclip_result.get("fetch_url", "")
    output["http_status_code"] = paperclip_result.get("http_status_code", "")
    output["fetch_mode"] = paperclip_result.get("fetch_mode", "")
    output["paperclip_error"] = paperclip_result.get("error", "")

    output["title"] = safe_str(pubmed_row.get("title"))
    output["year"] = safe_str(pubmed_row.get("year"))
    output["journal"] = safe_str(pubmed_row.get("journal"))
    output["doi"] = safe_str(pubmed_row.get("doi"))
    output["abstract"] = safe_str(pubmed_row.get("abstract"))
    output["has_abstract"] = bool(pubmed_row.get("has_abstract"))

    return output


# Main public function

def fetch_one_document_with_fallback(
    pmid: str,
    pmc_id: str,
    full_text_dir: Path,
    raw_dir: Path,
    base_url: str = "",
    api_key: str = "",
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    max_retries: int = DEFAULT_MAX_RETRIES,
    sleep_seconds: float = DEFAULT_SLEEP_SECONDS,
    reuse_existing: bool = True,
) -> dict[str, Any]:
    """Essaie Paperclip d'abord ; si aucun texte complet n'est obtenu, retente
    via l'API Europe PMC avant d'abandonner (voir europepmc_fetcher.py)."""

    try:
        result = fetch_one_paperclip_document(
            pmid=pmid,
            pmc_id=pmc_id,
            full_text_dir=full_text_dir,
            raw_dir=raw_dir,
            base_url=base_url,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            sleep_seconds=sleep_seconds,
            reuse_existing=reuse_existing,
        )
    except Exception as exc:
        # Paperclip peut lever une exception (timeout, CLI absente, ...) au
        # lieu de retourner un resultat "failed" -- on la traite comme un
        # echec Paperclip normal et on tente le fallback ci-dessous.
        result = no_full_text_result(
            pmid=pmid,
            pmc_id=pmc_id,
            status="failed",
            chars=0,
            fetch_url="",
            fetch_mode="cli" if not base_url else "http",
            error=str(exc),
        )

    if result.get("has_full_text") or not pmc_id:
        return result

    fallback_result = fetch_one_europepmc_document(
        pmid=pmid,
        pmc_id=pmc_id,
        full_text_dir=full_text_dir,
        raw_dir=raw_dir,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        sleep_seconds=sleep_seconds,
    )

    if fallback_result.get("has_full_text"):
        fallback_result["error"] = (
            f"Paperclip failed ({result.get('error') or result.get('paperclip_status')}); "
            "recovered via Europe PMC fallback."
        )
        return fallback_result

    # Ni Paperclip ni Europe PMC n'ont donne de texte complet : on garde le
    # resultat Paperclip original (deja "abstract only"), en notant l'echec
    # du fallback pour transparence.
    result["error"] = (
        f"{result.get('error', '')} | Europe PMC fallback also failed: "
        f"{fallback_result.get('error', '')}"
    ).strip(" |")

    return result


def run_paperclip_fetcher(
    input_manifest: Path,
    pubmed_jsonl: Path,
    pubmed_dir: Path,
    output_manifest_csv: Path,
    results_jsonl: Path,
    audit_json: Path,
    full_text_dir: Path,
    raw_dir: Path,
    base_url: str | None = None,
    api_key: str | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    max_retries: int = DEFAULT_MAX_RETRIES,
    sleep_seconds: float = DEFAULT_SLEEP_SECONDS,
    reuse_existing: bool = True,
    pmids_filter: list[str] | None = None,
    limit: int | None = None,
    max_workers: int = 1,
) -> dict[str, Any]:
    resolved_base_url = resolve_paperclip_base_url(base_url)
    resolved_api_key = resolve_paperclip_api_key(api_key)
    resolved_command = resolve_paperclip_command()

    rows_to_process = build_rows_to_process(
        manifest_path=input_manifest,
        pubmed_jsonl=pubmed_jsonl,
        pubmed_dir=pubmed_dir,
        pmids_filter=pmids_filter,
        limit=limit,
    )

    if not rows_to_process:
        raise ValueError(
            "No rows to process. Check input_manifest and PubMed outputs. "
            f"input_manifest={input_manifest}, pubmed_jsonl={pubmed_jsonl}, "
            f"pubmed_dir={pubmed_dir}"
        )

    total = len(rows_to_process)
    print(f"Paperclip: {total} PMIDs a traiter (workers={max_workers}).")

    def process_one_row(row: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None]:
        pmid = safe_str(row["pmid"])
        pmc_id = normalize_pmc_id(row.get("pmc_id"))
        manifest_row = row.get("manifest_row") or {}
        pubmed_row = row.get("pubmed_row") or {}

        error_entry: dict[str, Any] | None = None

        try:
            result = fetch_one_document_with_fallback(
                pmid=pmid,
                pmc_id=pmc_id,
                full_text_dir=full_text_dir,
                raw_dir=raw_dir,
                base_url=resolved_base_url,
                api_key=resolved_api_key,
                timeout_seconds=timeout_seconds,
                max_retries=max_retries,
                sleep_seconds=sleep_seconds,
                reuse_existing=reuse_existing,
            )

            print(
                f"PMID={pmid} | pmc={pmc_id or '-'} | "
                f"status={result.get('paperclip_status')} | "
                f"full_text={result.get('has_full_text')} | "
                f"source={result.get('fetch_mode')} | "
                f"chars={result.get('paperclip_content_chars')}"
            )

        except Exception as exc:
            fetch_url = (
                paperclip_content_url(resolved_base_url, pmc_id)
                if resolved_base_url and pmc_id
                else paperclip_cli_path(pmc_id)
                if pmc_id
                else ""
            )

            fetch_mode = "http" if resolved_base_url else "cli"

            result = no_full_text_result(
                pmid=pmid,
                pmc_id=pmc_id,
                status="failed",
                chars=0,
                fetch_url=fetch_url,
                fetch_mode=fetch_mode,
                error=str(exc),
            )

            error_entry = {
                "pmid": pmid,
                "pmc_id": pmc_id,
                "error_type": type(exc).__name__,
                "message": str(exc),
                "fetch_mode": fetch_mode,
            }

            print(f"PMID={pmid} | pmc={pmc_id or '-'} | FAILED: {exc}")

        enriched_row = merge_manifest_with_paperclip(
            input_row=manifest_row,
            pubmed_row=pubmed_row,
            paperclip_result=result,
        )

        if max_workers <= 1:
            time.sleep(sleep_seconds)

        return result, enriched_row, error_entry

    results: list[dict[str, Any]] = []
    enriched_manifest_rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    if max_workers <= 1:
        for index, row in enumerate(rows_to_process, start=1):
            result, enriched_row, error_entry = process_one_row(row)
            results.append(result)
            enriched_manifest_rows.append(enriched_row)
            if error_entry is not None:
                errors.append(error_entry)
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(process_one_row, row): row
                for row in rows_to_process
            }

            for future in as_completed(futures):
                result, enriched_row, error_entry = future.result()
                results.append(result)
                enriched_manifest_rows.append(enriched_row)
                if error_entry is not None:
                    errors.append(error_entry)

    write_jsonl(results_jsonl, results)
    write_csv_rows(output_manifest_csv, enriched_manifest_rows)

    status_distribution = dict(
        Counter(safe_str(row.get("paperclip_status")) for row in results)
    )

    fetch_mode_distribution = dict(
        Counter(safe_str(row.get("fetch_mode")) for row in results)
    )

    attempted = sum(1 for row in results if safe_bool(row.get("paperclip_attempted")))
    success = sum(1 for row in results if safe_bool(row.get("has_full_text")))
    no_pmc_id = sum(1 for row in results if not safe_str(row.get("pmc_id")))

    audit = {
        "run_date": now_iso(),
        "input_manifest": str(input_manifest),
        "pubmed_jsonl": str(pubmed_jsonl),
        "pubmed_dir": str(pubmed_dir),
        "base_url_configured": bool(resolved_base_url),
        "paperclip_command": resolved_command,
        "paperclip_cli_available": is_paperclip_cli_available(resolved_command),
        "reuse_existing": reuse_existing,
        "min_full_text_chars": MIN_FULL_TEXT_CHARS,
        "n_rows_processed": len(results),
        "paperclip_attempted": attempted,
        "success_full_text": success,
        "abstract_only": len(results) - success,
        "no_pmc_id": no_pmc_id,
        "status_distribution": status_distribution,
        "fetch_mode_distribution": fetch_mode_distribution,
        "errors": errors,
        "outputs": {
            "output_manifest_csv": str(output_manifest_csv),
            "results_jsonl": str(results_jsonl),
            "audit_json": str(audit_json),
            "full_text_dir": str(full_text_dir),
            "raw_dir": str(raw_dir),
        },
        "next_step": "Run prepare_llm_inputs using output_manifest_csv.",
    }

    write_json(audit_json, audit)

    return {
        "results": results,
        "manifest_rows": enriched_manifest_rows,
        "audit": audit,
    }
