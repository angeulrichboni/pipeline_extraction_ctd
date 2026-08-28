"""Build canonical JSONL inputs from CTD, PubMed and Paperclip data."""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from src.io.csv_io import read_csv_rows, write_csv_rows
from src.io.json_io import read_json_or_empty, write_json


# Constants

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


def safe_int(value: Any, default: int = 0) -> int:
    text = safe_str(value)

    if not text:
        return default

    try:
        return int(float(text))
    except Exception:
        return default


def safe_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value

    if isinstance(value, str) and value.strip():
        return [value.strip()]

    return []


def normalize_text(value: Any) -> str:
    text = safe_str(value).lower()
    text = text.replace("₂", "2").replace("₃", "3").replace("ₓ", "x")
    text = text.replace("μ", "µ")
    text = text.replace("–", "-").replace("—", "-")
    text = text.replace("_", " ")
    text = " ".join(text.split())
    return text


def clean_text(text: str) -> str:
    if not text:
        return ""

    text = text.replace("\u00a0", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"^\s*L\d+\s*:\s*", "", text, flags=re.MULTILINE)

    lines = []

    for line in text.splitlines():
        line = " ".join(line.split())

        if line:
            lines.append(line)
        else:
            lines.append("")

    cleaned = "\n".join(lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

    return cleaned.strip()


def is_valid_full_text(text: str, min_chars: int = MIN_FULL_TEXT_CHARS) -> bool:
    cleaned = clean_text(text)
    return len(cleaned) >= min_chars


def read_text_or_empty(path: Path | str | None) -> str:
    if path is None:
        return ""

    path_obj = Path(str(path))

    if not path_obj.exists() or not path_obj.is_file():
        return ""

    return path_obj.read_text(encoding="utf-8", errors="ignore")


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


# CTD manifest loading

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
            for key in ["rows", "data", "records", "pmids"]:
                value = payload.get(key)

                if isinstance(value, list):
                    return value

            return [payload]

    return []


def normalize_ctd_context(row: dict[str, Any]) -> dict[str, Any]:
    existing_context = row.get("ctd_context")

    if isinstance(existing_context, dict):
        context = dict(existing_context)
    else:
        context = {}

    def get_value(name: str, alternatives: list[str]) -> str:
        if safe_str(context.get(name)):
            return safe_str(context.get(name))

        return first_value(row, alternatives)

    context["source_pollutant"] = get_value(
        "source_pollutant",
        [
            "source_pollutant",
            "pollutant",
            "chemical",
            "stressor",
            "stressor_agent",
            "ctd_context.source_pollutant",
        ],
    )

    context["source_file"] = get_value(
        "source_file",
        [
            "source_file",
            "ctd_source_file",
            "file",
            "ctd_context.source_file",
        ],
    )

    context["stressor_agent"] = get_value(
        "stressor_agent",
        [
            "stressor_agent",
            "stressor",
            "chemical",
            "ctd_context.stressor_agent",
        ],
    )

    context["stressor_agent_primary"] = get_value(
        "stressor_agent_primary",
        [
            "stressor_agent_primary",
            "stressor_agent",
            "pollutant",
            "chemical",
            "ctd_context.stressor_agent_primary",
        ],
    )

    context["receptors"] = get_value(
        "receptors",
        [
            "receptors",
            "receptor",
            "ctd_context.receptors",
        ],
    )

    context["receptors_primary"] = get_value(
        "receptors_primary",
        [
            "receptors_primary",
            "receptor_primary",
            "receptors",
            "ctd_context.receptors_primary",
        ],
    )

    context["outcome_ctd"] = get_value(
        "outcome_ctd",
        [
            "outcome_ctd",
            "outcome",
            "disease",
            "ctd_context.outcome_ctd",
        ],
    )

    context["outcome_ctd_primary"] = get_value(
        "outcome_ctd_primary",
        [
            "outcome_ctd_primary",
            "outcome_ctd",
            "outcome",
            "disease",
            "ctd_context.outcome_ctd_primary",
        ],
    )

    context["country"] = get_value(
        "country",
        [
            "country",
            "location",
            "ctd_context.country",
        ],
    )

    context["country_primary"] = get_value(
        "country_primary",
        [
            "country_primary",
            "country",
            "location",
            "ctd_context.country_primary",
        ],
    )

    context["medium"] = get_value(
        "medium",
        [
            "medium",
            "exposure_medium",
            "ctd_context.medium",
        ],
    )

    context["exposure_marker"] = get_value(
        "exposure_marker",
        [
            "exposure_marker",
            "marker",
            "ctd_context.exposure_marker",
        ],
    )

    context["anatomy"] = get_value(
        "anatomy",
        [
            "anatomy",
            "tissue",
            "organ",
            "ctd_context.anatomy",
        ],
    )

    context["associated_study_title_ctd"] = get_value(
        "associated_study_title_ctd",
        [
            "associated_study_title_ctd",
            "study_title",
            "title_ctd",
            "ctd_context.associated_study_title_ctd",
        ],
    )

    context["author_summary_ctd"] = get_value(
        "author_summary_ctd",
        [
            "author_summary_ctd",
            "summary",
            "ctd_context.author_summary_ctd",
        ],
    )

    return context


def extract_pmid_from_manifest_row(row: dict[str, Any]) -> str:
    return first_value(
        row,
        [
            "pmid",
            "PMID",
            "pubmed_id",
            "PubMedID",
            "ctd_context.pmid",
        ],
    )


# PubMed metadata loading

def find_pubmed_json_path(pmid: str, pubmed_dir: Path) -> Path | None:
    candidates = [
        pubmed_dir / f"{pmid}_pubmed.json",
        pubmed_dir / f"{pmid}_pubmed_metadata.json",
        pubmed_dir / f"{pmid}_metadata.json",
        pubmed_dir / f"pubmed_{pmid}.json",
        pubmed_dir / f"{pmid}.json",
    ]

    for path in candidates:
        if path.exists():
            return path

    matches = list(pubmed_dir.glob(f"*{pmid}*.json"))

    if matches:
        return matches[0]

    return None


def load_pubmed_jsonl_index(pubmed_dir: Path) -> dict[str, dict[str, Any]]:
    """Load PubMed batch JSONL files by PMID."""
    index: dict[str, dict[str, Any]] = {}

    if not pubmed_dir.exists():
        return index

    candidates = [
        pubmed_dir / "pubmed_test_results.jsonl",
        pubmed_dir / "pubmed_results.jsonl",
    ]

    candidates.extend(sorted(pubmed_dir.glob("*.jsonl")))

    seen_paths = set()

    for path in candidates:
        if path in seen_paths:
            continue

        seen_paths.add(path)

        if not path.exists():
            continue

        for row in read_jsonl(path):
            pmid = safe_str(row.get("pmid"))

            if pmid:
                index[pmid] = row

    return index


def normalize_authors(value: Any) -> list[str]:
    if isinstance(value, list):
        authors = []

        for item in value:
            if isinstance(item, str):
                authors.append(item)
            elif isinstance(item, dict):
                name = (
                    safe_str(item.get("name"))
                    or " ".join(
                        part
                        for part in [
                            safe_str(item.get("fore_name")),
                            safe_str(item.get("last_name")),
                        ]
                        if part
                    )
                )

                if name:
                    authors.append(name)

        return authors

    if isinstance(value, str) and value.strip():
        return [item.strip() for item in value.split(";") if item.strip()]

    return []


def normalize_pubmed_metadata(
    pmid: str,
    manifest_row: dict[str, Any],
    pubmed_dir: Path,
    pubmed_index: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    embedded = manifest_row.get("pubmed")

    if isinstance(embedded, dict):
        source_payload = dict(embedded)
        source_path = ""
    else:
        indexed_payload = (pubmed_index or {}).get(pmid)

        if indexed_payload:
            source_payload = indexed_payload
            source_path = "pubmed_jsonl_index"
        else:
            pubmed_path = find_pubmed_json_path(pmid, pubmed_dir)

            if pubmed_path is not None:
                source_payload = read_json_or_empty(pubmed_path)
                source_path = str(pubmed_path)
            else:
                source_payload = {}
                source_path = ""

    title = (
        first_value(source_payload, ["title", "article_title", "pubmed_title"])
        or first_value(manifest_row, ["title", "pubmed.title"])
    )

    abstract = (
        first_value(
            source_payload,
            ["abstract", "abstract_text", "pubmed_abstract", "abstract_raw"],
        )
        or first_value(
            manifest_row,
            [
                "abstract",
                "pubmed_abstract",
                "pubmed.abstract",
            ],
        )
    )

    journal = (
        first_value(source_payload, ["journal", "journal_title", "source"])
        or first_value(manifest_row, ["journal", "pubmed.journal"])
    )

    year = (
        first_value(source_payload, ["year", "publication_year", "pub_year"])
        or first_value(manifest_row, ["year", "pubmed.year"])
    )

    doi = (
        first_value(source_payload, ["doi", "article_doi"])
        or first_value(manifest_row, ["doi", "pubmed.doi"])
    )

    pmc_id = normalize_pmc_id(
        first_value(
            source_payload,
            ["pmc_id", "pmcid", "pmc", "PMC"],
        )
        or first_value(
            manifest_row,
            [
                "pmc_id",
                "pmcid",
                "pubmed.pmc_id",
            ],
        )
    )

    authors = normalize_authors(
        source_payload.get("authors")
        or get_nested_raw(manifest_row, "pubmed.authors")
        or manifest_row.get("authors")
    )

    mesh_terms = safe_list(
        source_payload.get("mesh_terms")
        or get_nested_raw(manifest_row, "pubmed.mesh_terms")
    )

    keywords = safe_list(
        source_payload.get("keywords")
        or get_nested_raw(manifest_row, "pubmed.keywords")
    )

    publication_types = safe_list(
        source_payload.get("publication_types")
        or get_nested_raw(manifest_row, "pubmed.publication_types")
    )

    pubmed_status = (
        first_value(source_payload, ["pubmed_status", "status"])
        or first_value(manifest_row, ["pubmed_status", "pubmed.pubmed_status"])
    )

    title = clean_text(title)
    abstract = clean_text(abstract)

    return {
        "title": title,
        "year": year,
        "journal": journal,
        "doi": doi,
        "pmc_id": pmc_id,
        "abstract": abstract,
        "has_abstract": bool(abstract),
        "authors": authors,
        "mesh_terms": mesh_terms,
        "keywords": keywords,
        "publication_types": publication_types,
        "pubmed_status": pubmed_status,
        "source_path": source_path,
    }


# Paperclip full text loading

def find_paperclip_text_path(
    pmid: str,
    pmc_id: str,
    paperclip_dir: Path,
    manifest_row: dict[str, Any],
) -> Path | None:
    embedded_path = first_value(
        manifest_row,
        [
            "paperclip.full_text_path",
            "paperclip.raw_content_path",
            "paperclip_path",
            "paperclip_full_text_path",
            "full_text_path",
        ],
    )

    if embedded_path:
        path = Path(embedded_path)

        if path.exists():
            return path

    candidates = [
        paperclip_dir / f"{pmid}.txt",
        paperclip_dir / f"{pmid}_full_text.txt",
        paperclip_dir / f"{pmid}_paperclip_full_text.txt",
        paperclip_dir / f"{pmid}_content.lines",
        paperclip_dir / f"{pmid}.lines",
    ]

    if pmc_id:
        candidates.extend(
            [
                paperclip_dir / f"{pmc_id}.txt",
                paperclip_dir / f"{pmc_id}_full_text.txt",
                paperclip_dir / f"{pmc_id}_paperclip_full_text.txt",
                paperclip_dir / f"{pmc_id}_content.lines",
                paperclip_dir / f"{pmc_id}.lines",
                paperclip_dir / "papers" / pmc_id / "content.lines",
                paperclip_dir / pmc_id / "content.lines",
            ]
        )

    for path in candidates:
        if path.exists():
            return path

    matches = list(paperclip_dir.glob(f"*{pmid}*"))

    if matches:
        for path in matches:
            if path.is_file():
                return path

    if pmc_id:
        matches = list(paperclip_dir.glob(f"**/*{pmc_id}*"))

        for path in matches:
            if path.is_file() and path.name in {"content.lines", f"{pmc_id}.txt"}:
                return path

    return None


def normalize_paperclip_metadata(
    pmid: str,
    pmc_id: str,
    manifest_row: dict[str, Any],
    paperclip_dir: Path,
) -> tuple[dict[str, Any], str]:
    embedded = manifest_row.get("paperclip")

    if isinstance(embedded, dict):
        embedded_payload = embedded
    else:
        embedded_payload = {}

    manifest_status = (
        first_value(
            manifest_row,
            [
                "paperclip_status",
                "paperclip.paperclip_status",
            ],
        )
        or safe_str(embedded_payload.get("paperclip_status"))
    )

    manifest_has_full_text_raw = (
        first_value(
            manifest_row,
            [
                "has_full_text",
                "paperclip.has_full_text",
            ],
        )
        or safe_str(embedded_payload.get("has_full_text"))
    )

    manifest_full_text_path = (
        first_value(
            manifest_row,
            [
                "full_text_path",
                "paperclip.full_text_path",
                "paperclip_full_text_path",
            ],
        )
        or safe_str(embedded_payload.get("full_text_path"))
    )

    manifest_raw_content_path = (
        first_value(
            manifest_row,
            [
                "raw_content_path",
                "paperclip.raw_content_path",
            ],
        )
        or safe_str(embedded_payload.get("raw_content_path"))
    )

    manifest_invalid_content_path = (
        first_value(
            manifest_row,
            [
                "invalid_content_path",
                "paperclip.invalid_content_path",
            ],
        )
        or safe_str(embedded_payload.get("invalid_content_path"))
    )

    manifest_content_chars = safe_int(
        first_value(
            manifest_row,
            [
                "paperclip_content_chars",
                "paperclip.paperclip_content_chars",
            ],
        )
        or embedded_payload.get("paperclip_content_chars"),
        default=0,
    )

    manifest_contains_paperclip_decision = any(
        [
            manifest_status,
            manifest_has_full_text_raw,
            manifest_full_text_path,
            manifest_raw_content_path,
            manifest_invalid_content_path,
            manifest_content_chars,
        ]
    )

    manifest_has_full_text = safe_bool(manifest_has_full_text_raw)

    # -----------------------------------------------------------------
    # Rule 1:
    # If an enriched Paperclip manifest explicitly says no full text,
    # respect it. Do NOT rescan paperclip/full_texts and accidentally
    # reuse invalid short files like 19620729.txt.
    # -----------------------------------------------------------------
    if manifest_contains_paperclip_decision and not manifest_has_full_text:
        attempted = manifest_status not in {"", "not_attempted"}

        paperclip = {
            "paperclip_attempted": attempted,
            "paperclip_status": manifest_status or "no_full_text",
            "has_full_text": False,
            "full_text_path": "",
            "raw_content_path": "",
            "paperclip_content_chars": manifest_content_chars,
        }

        return paperclip, ""

    # -----------------------------------------------------------------
    # Rule 2:
    # If manifest says full text exists, read only the declared path.
    # Still validate length.
    # -----------------------------------------------------------------
    if manifest_contains_paperclip_decision and manifest_has_full_text:
        full_text = ""

        if manifest_full_text_path:
            full_text = read_text_or_empty(manifest_full_text_path)

        full_text = clean_text(full_text)

        if is_valid_full_text(full_text):
            paperclip = {
                "paperclip_attempted": True,
                "paperclip_status": manifest_status or "success",
                "has_full_text": True,
                "full_text_path": manifest_full_text_path,
                "raw_content_path": manifest_raw_content_path,
                "paperclip_content_chars": len(full_text),
            }

            return paperclip, full_text

        paperclip = {
            "paperclip_attempted": True,
            "paperclip_status": "no_full_text",
            "has_full_text": False,
            "full_text_path": "",
            "raw_content_path": "",
            "paperclip_content_chars": len(full_text),
        }

        return paperclip, ""

    # -----------------------------------------------------------------
    # Rule 3:
    # Legacy fallback only when there is no enriched Paperclip decision.
    # This allows the builder to work with older manifests.
    # -----------------------------------------------------------------
    embedded_full_text = first_value(
        manifest_row,
        [
            "full_text",
            "paperclip_full_text",
            "paperclip.full_text",
            "paperclip.text",
            "paperclip.content",
        ],
    )

    full_text = clean_text(embedded_full_text)
    path = None

    if not full_text:
        path = find_paperclip_text_path(
            pmid=pmid,
            pmc_id=pmc_id,
            paperclip_dir=paperclip_dir,
            manifest_row=manifest_row,
        )

        if path is not None:
            full_text = clean_text(read_text_or_empty(path))

    if is_valid_full_text(full_text):
        paperclip = {
            "paperclip_attempted": bool(pmc_id) or path is not None,
            "paperclip_status": "success",
            "has_full_text": True,
            "full_text_path": str(path) if path is not None else "",
            "raw_content_path": str(path) if path is not None else "",
            "paperclip_content_chars": len(full_text),
        }

        return paperclip, full_text

    if pmc_id:
        status = "no_full_text"
        attempted = True
    else:
        status = "not_attempted"
        attempted = False

    paperclip = {
        "paperclip_attempted": attempted,
        "paperclip_status": status,
        "has_full_text": False,
        "full_text_path": "",
        "raw_content_path": "",
        "paperclip_content_chars": len(full_text),
    }

    return paperclip, ""


# LLM input construction

def build_document_text(
    title: str,
    abstract: str,
    full_text: str,
) -> str:
    blocks = []

    if title:
        blocks.append(f"### TITLE\n{title}")

    if abstract:
        blocks.append(f"### PUBMED ABSTRACT\n{abstract}")

    if full_text:
        blocks.append(f"### FULL TEXT\n{full_text}")

    return "\n\n".join(blocks).strip()


def build_processing_plan() -> dict[str, Any]:
    return {
        "intended_pipeline": [
            "document_segmentation",
            "pollutant_extractor",
            "outcome_extractor",
            "effect_measure_extractor",
            "association_builder",
            "final_quality_control",
        ],
        "agents": {
            "pollutant_extractor": (
                "Extract all pollutant/exposure mentions without discarding useful context."
            ),
            "outcome_extractor": (
                "Extract health outcomes/endpoints and mark final-analysis relevance."
            ),
            "effect_measure_extractor": (
                "Extract quantitative pollutant-outcome effect estimates."
            ),
            "association_builder": (
                "Build one row per distinct scientific association."
            ),
        },
        "output_rule": (
            "A PMID may produce multiple final rows; each distinct scientific "
            "association is one row."
        ),
        "non_significant_results": (
            "Non-significant quantitative direct effects must be preserved."
        ),
        "deduplication_rule": (
            "Only merge associations when scientific key fields are identical; "
            "otherwise keep separate rows."
        ),
    }


def build_one_llm_input(
    pmid: str,
    manifest_row: dict[str, Any],
    pubmed_dir: Path,
    paperclip_dir: Path,
    pubmed_index: dict[str, dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    ctd_context = normalize_ctd_context(manifest_row)

    pubmed = normalize_pubmed_metadata(
        pmid=pmid,
        manifest_row=manifest_row,
        pubmed_dir=pubmed_dir,
        pubmed_index=pubmed_index,
    )

    paperclip, full_text = normalize_paperclip_metadata(
        pmid=pmid,
        pmc_id=safe_str(pubmed.get("pmc_id")),
        manifest_row=manifest_row,
        paperclip_dir=paperclip_dir,
    )

    title = safe_str(pubmed.get("title"))
    abstract = safe_str(pubmed.get("abstract"))

    text_source = "full_text" if full_text else "abstract_only"

    document_text = build_document_text(
        title=title,
        abstract=abstract,
        full_text=full_text,
    )

    stats = {
        "title_chars": len(title),
        "abstract_chars": len(abstract),
        "full_text_chars": len(full_text),
        "document_text_chars": len(document_text),
    }

    row = {
        "pmid": pmid,
        "created_at": now_iso(),
        "ctd_context": ctd_context,
        "pubmed": {
            "title": title,
            "year": safe_str(pubmed.get("year")),
            "journal": safe_str(pubmed.get("journal")),
            "doi": safe_str(pubmed.get("doi")),
            "pmc_id": safe_str(pubmed.get("pmc_id")),
            "abstract": abstract,
            "has_abstract": bool(abstract),
            "authors": safe_list(pubmed.get("authors")),
            "mesh_terms": safe_list(pubmed.get("mesh_terms")),
            "keywords": safe_list(pubmed.get("keywords")),
            "publication_types": safe_list(pubmed.get("publication_types")),
            "pubmed_status": safe_str(pubmed.get("pubmed_status")),
        },
        "paperclip": paperclip,
        "text_source": text_source,
        "document_text": document_text,
        "stats": stats,
        "llm_processing_plan": build_processing_plan(),
    }

    summary = {
        "pmid": pmid,
        "text_source": text_source,
        "has_title": bool(title),
        "has_abstract": bool(abstract),
        "has_full_text": bool(full_text),
        "pmc_id": safe_str(pubmed.get("pmc_id")),
        "paperclip_status": paperclip["paperclip_status"],
        "paperclip_attempted": paperclip["paperclip_attempted"],
        "paperclip_full_text_path": paperclip["full_text_path"],
        "pubmed_source_path": safe_str(pubmed.get("source_path")),
        "source_pollutant": safe_str(ctd_context.get("source_pollutant")),
        "stressor_agent_primary": safe_str(ctd_context.get("stressor_agent_primary")),
        "outcome_ctd_primary": safe_str(ctd_context.get("outcome_ctd_primary")),
        "title_chars": stats["title_chars"],
        "abstract_chars": stats["abstract_chars"],
        "full_text_chars": stats["full_text_chars"],
        "document_text_chars": stats["document_text_chars"],
    }

    return row, summary


def discover_pmids_from_sources(
    manifest_rows: list[dict[str, Any]],
    pubmed_dir: Path,
    paperclip_dir: Path,
) -> list[str]:
    pmids = []

    for row in manifest_rows:
        pmid = extract_pmid_from_manifest_row(row)

        if pmid:
            pmids.append(pmid)

    if not pmids and pubmed_dir.exists():
        for path in pubmed_dir.glob("*.json"):
            match = re.search(r"(\d{6,9})", path.name)

            if match:
                pmids.append(match.group(1))

        for path in pubmed_dir.glob("*.jsonl"):
            for row in read_jsonl(path):
                pmid = safe_str(row.get("pmid"))

                if pmid:
                    pmids.append(pmid)

    if not pmids and paperclip_dir.exists():
        for path in paperclip_dir.glob("**/*"):
            match = re.search(r"(\d{6,9})", path.name)

            if match:
                pmids.append(match.group(1))

    return sorted(set(pmids))


def run_llm_input_builder(
    manifest_path: Path,
    pubmed_dir: Path,
    paperclip_dir: Path,
    output_jsonl: Path,
    manifest_csv: Path,
    audit_json: Path,
    pmids_filter: list[str] | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    manifest_rows = load_manifest_rows(manifest_path)
    pubmed_index = load_pubmed_jsonl_index(pubmed_dir)

    row_by_pmid: dict[str, dict[str, Any]] = {}

    for row in manifest_rows:
        pmid = extract_pmid_from_manifest_row(row)

        if pmid:
            row_by_pmid[pmid] = row

    pmids = discover_pmids_from_sources(
        manifest_rows=manifest_rows,
        pubmed_dir=pubmed_dir,
        paperclip_dir=paperclip_dir,
    )

    if pmids_filter:
        wanted = set(pmids_filter)
        pmids = [pmid for pmid in pmids if pmid in wanted]

    if limit is not None:
        pmids = pmids[:limit]

    if not pmids:
        raise ValueError(
            "No PMIDs discovered. Check manifest_path, pubmed_dir, and paperclip_dir. "
            f"manifest_path={manifest_path}, pubmed_dir={pubmed_dir}, "
            f"paperclip_dir={paperclip_dir}"
        )

    llm_rows = []
    summaries = []
    errors = []

    for pmid in pmids:
        manifest_row = row_by_pmid.get(pmid, {"pmid": pmid})

        try:
            llm_row, summary = build_one_llm_input(
                pmid=pmid,
                manifest_row=manifest_row,
                pubmed_dir=pubmed_dir,
                paperclip_dir=paperclip_dir,
                pubmed_index=pubmed_index,
            )

            llm_rows.append(llm_row)
            summaries.append(summary)

        except Exception as exc:
            errors.append(
                {
                    "pmid": pmid,
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                }
            )

    write_jsonl(output_jsonl, llm_rows)
    write_csv_rows(manifest_csv, summaries)

    n_rows = len(llm_rows)
    with_full_text = sum(1 for row in summaries if safe_bool(row["has_full_text"]))
    abstract_only = sum(1 for row in summaries if not safe_bool(row["has_full_text"]))
    missing_abstract = sum(1 for row in summaries if not safe_bool(row["has_abstract"]))

    text_source_distribution = dict(
        Counter(row["text_source"] for row in summaries)
    )

    paperclip_status_distribution = dict(
        Counter(row["paperclip_status"] for row in summaries)
    )

    audit = {
        "run_date": now_iso(),
        "input_manifest": str(manifest_path),
        "pubmed_dir": str(pubmed_dir),
        "paperclip_dir": str(paperclip_dir),
        "min_full_text_chars": MIN_FULL_TEXT_CHARS,
        "n_manifest_rows": len(manifest_rows),
        "n_pmids_requested": len(pmids),
        "n_llm_input_rows": n_rows,
        "with_full_text": with_full_text,
        "abstract_only": abstract_only,
        "missing_abstract": missing_abstract,
        "text_source_distribution": text_source_distribution,
        "paperclip_status_distribution": paperclip_status_distribution,
        "errors": errors,
        "outputs": {
            "jsonl": str(output_jsonl),
            "manifest_csv": str(manifest_csv),
            "audit_json": str(audit_json),
        },
        "next_step": "Run document segmentation.",
    }

    write_json(audit_json, audit)

    return {
        "rows": llm_rows,
        "summaries": summaries,
        "audit": audit,
    }
