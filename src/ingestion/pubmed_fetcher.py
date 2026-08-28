"""Fetch PubMed metadata and abstracts for PMID lists."""

from __future__ import annotations

import csv
import json
import re
import time
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from src.config.settings import settings
from src.io.csv_io import read_csv_rows, write_csv_rows
from src.io.json_io import write_json


# Constants

NCBI_EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

DEFAULT_BATCH_SIZE = 100
DEFAULT_SLEEP_SECONDS = 0.34


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


def clean_text(text: str) -> str:
    if not text:
        return ""

    text = text.replace("\u00a0", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def text_content(node: ET.Element | None) -> str:
    if node is None:
        return ""

    return clean_text("".join(node.itertext()))


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


def chunk_list(values: list[str], batch_size: int) -> list[list[str]]:
    return [
        values[index:index + batch_size]
        for index in range(0, len(values), batch_size)
    ]


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

    if text.upper().startswith("PMC"):
        digits = re.sub(r"\D", "", text)

        if digits:
            return f"PMC{digits}"

    digits = re.sub(r"\D", "", text)

    if digits:
        return f"PMC{digits}"

    return ""


# PMID loading

def extract_pmid_from_row(row: dict[str, Any]) -> str:
    for key in [
        "pmid",
        "PMID",
        "pubmed_id",
        "PubMedID",
        "pubmed.pmid",
        "ctd_context.pmid",
    ]:
        if "." in key:
            current: Any = row

            for part in key.split("."):
                if not isinstance(current, dict):
                    current = None
                    break

                current = current.get(part)

            pmid = normalize_pmid(current)
        else:
            pmid = normalize_pmid(row.get(key))

        if pmid:
            return pmid

    return ""


def load_pmids_from_txt(path: Path) -> list[str]:
    pmids = []

    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        pmid = normalize_pmid(line)

        if pmid:
            pmids.append(pmid)

    return pmids


def load_pmids_from_csv(path: Path) -> list[str]:
    rows = read_csv_rows(path)

    pmids = []

    for row in rows:
        pmid = extract_pmid_from_row(row)

        if pmid:
            pmids.append(pmid)

    return pmids


def load_pmids_from_jsonl(path: Path) -> list[str]:
    rows = read_jsonl(path)

    pmids = []

    for row in rows:
        pmid = extract_pmid_from_row(row)

        if pmid:
            pmids.append(pmid)

    return pmids


def load_pmids_from_json(path: Path) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8", errors="ignore"))

    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = []

        for key in ["rows", "data", "records", "pmids"]:
            value = payload.get(key)

            if isinstance(value, list):
                rows = value
                break

        if not rows:
            rows = [payload]
    else:
        rows = []

    pmids = []

    for item in rows:
        if isinstance(item, dict):
            pmid = extract_pmid_from_row(item)
        else:
            pmid = normalize_pmid(item)

        if pmid:
            pmids.append(pmid)

    return pmids


def load_pmids(input_path: Path) -> list[str]:
    if not input_path.exists():
        raise FileNotFoundError(f"PMID input file not found: {input_path}")

    suffix = input_path.suffix.lower()

    if suffix == ".txt":
        pmids = load_pmids_from_txt(input_path)
    elif suffix == ".csv":
        pmids = load_pmids_from_csv(input_path)
    elif suffix == ".jsonl":
        pmids = load_pmids_from_jsonl(input_path)
    elif suffix == ".json":
        pmids = load_pmids_from_json(input_path)
    else:
        raise ValueError(
            f"Unsupported PMID input format: {input_path}. "
            "Use .txt, .csv, .jsonl, or .json."
        )

    # Preserve order while deduplicating.
    seen = set()
    unique_pmids = []

    for pmid in pmids:
        if pmid in seen:
            continue

        seen.add(pmid)
        unique_pmids.append(pmid)

    return unique_pmids


# PubMed XML fetching

def build_ncbi_params(pmids: list[str]) -> dict[str, str]:
    params = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "xml",
    }

    email = safe_str(getattr(settings, "ncbi_email", ""))
    api_key = safe_str(getattr(settings, "ncbi_api_key", ""))

    if email:
        params["email"] = email

    if api_key:
        params["api_key"] = api_key

    return params


def fetch_pubmed_batch_xml(
    pmids: list[str],
    timeout_seconds: int = 60,
    max_retries: int = 3,
    sleep_seconds: float = DEFAULT_SLEEP_SECONDS,
) -> str:
    params = build_ncbi_params(pmids)

    last_error: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            response = requests.get(
                NCBI_EFETCH_URL,
                params=params,
                timeout=timeout_seconds,
            )

            if response.status_code in {408, 429, 500, 502, 503, 504}:
                if attempt < max_retries:
                    time.sleep(sleep_seconds * attempt)
                    continue

            response.raise_for_status()

            text = response.text.strip()

            if not text:
                raise RuntimeError("Empty PubMed XML response.")

            return text

        except Exception as exc:
            last_error = exc

            if attempt < max_retries:
                time.sleep(sleep_seconds * attempt)
                continue

            raise RuntimeError(
                f"PubMed batch fetch failed after {max_retries} attempts: {exc}"
            ) from exc

    raise RuntimeError(f"PubMed batch fetch failed: {last_error}")


# PubMed XML parsing

def extract_article_ids(article: ET.Element) -> dict[str, str]:
    ids = {
        "pmid": "",
        "doi": "",
        "pmc_id": "",
    }

    pmid_node = article.find(".//MedlineCitation/PMID")

    if pmid_node is not None and pmid_node.text:
        ids["pmid"] = normalize_pmid(pmid_node.text)

    for node in article.findall(".//PubmedData/ArticleIdList/ArticleId"):
        id_type = safe_str(node.attrib.get("IdType")).lower()
        value = safe_str(node.text)

        if not value:
            continue

        if id_type == "doi":
            ids["doi"] = value

        if id_type == "pmc":
            ids["pmc_id"] = normalize_pmc_id(value)

        if id_type == "pubmed" and not ids["pmid"]:
            ids["pmid"] = normalize_pmid(value)

    return ids


def extract_year(article: ET.Element) -> str:
    year_paths = [
        ".//MedlineCitation/Article/Journal/JournalIssue/PubDate/Year",
        ".//MedlineCitation/Article/ArticleDate/Year",
        ".//PubmedData/History/PubMedPubDate/Year",
    ]

    for path in year_paths:
        node = article.find(path)

        if node is not None and node.text:
            return safe_str(node.text)

    medline_date = text_content(
        article.find(".//MedlineCitation/Article/Journal/JournalIssue/PubDate/MedlineDate")
    )

    match = re.search(r"\b(19|20)\d{2}\b", medline_date)

    if match:
        return match.group(0)

    return ""


def extract_abstract(article: ET.Element) -> str:
    abstract_nodes = article.findall(".//MedlineCitation/Article/Abstract/AbstractText")

    parts = []

    for node in abstract_nodes:
        label = safe_str(node.attrib.get("Label"))
        nlm_category = safe_str(node.attrib.get("NlmCategory"))
        text = text_content(node)

        if not text:
            continue

        prefix = label or nlm_category

        if prefix:
            parts.append(f"{prefix}: {text}")
        else:
            parts.append(text)

    return clean_text(" ".join(parts))


def extract_authors(article: ET.Element) -> list[str]:
    authors = []

    for node in article.findall(".//MedlineCitation/Article/AuthorList/Author"):
        collective_name = text_content(node.find("CollectiveName"))

        if collective_name:
            authors.append(collective_name)
            continue

        last_name = text_content(node.find("LastName"))
        fore_name = text_content(node.find("ForeName"))
        initials = text_content(node.find("Initials"))

        name_parts = []

        if fore_name:
            name_parts.append(fore_name)
        elif initials:
            name_parts.append(initials)

        if last_name:
            name_parts.append(last_name)

        name = " ".join(name_parts).strip()

        if name:
            authors.append(name)

    return authors


def extract_mesh_terms(article: ET.Element) -> list[str]:
    terms = []

    for node in article.findall(".//MedlineCitation/MeshHeadingList/MeshHeading/DescriptorName"):
        text = text_content(node)

        if text:
            terms.append(text)

    return terms


def extract_keywords(article: ET.Element) -> list[str]:
    terms = []

    for node in article.findall(".//MedlineCitation/KeywordList/Keyword"):
        text = text_content(node)

        if text:
            terms.append(text)

    return terms


def extract_publication_types(article: ET.Element) -> list[str]:
    types = []

    for node in article.findall(".//MedlineCitation/Article/PublicationTypeList/PublicationType"):
        text = text_content(node)

        if text:
            types.append(text)

    return types


def extract_pubmed_status(article: ET.Element) -> str:
    status = text_content(article.find(".//PubmedData/PublicationStatus"))

    if status:
        return status

    citation_status = safe_str(
        article.find(".//MedlineCitation").attrib.get("Status")
        if article.find(".//MedlineCitation") is not None
        else ""
    )

    return citation_status


def parse_pubmed_article(article: ET.Element) -> dict[str, Any]:
    ids = extract_article_ids(article)

    title = text_content(article.find(".//MedlineCitation/Article/ArticleTitle"))
    abstract = extract_abstract(article)

    journal = (
        text_content(article.find(".//MedlineCitation/Article/Journal/Title"))
        or text_content(article.find(".//MedlineCitation/Article/Journal/ISOAbbreviation"))
    )

    year = extract_year(article)

    result = {
        "pmid": ids["pmid"],
        "title": title,
        "year": year,
        "journal": journal,
        "doi": ids["doi"],
        "pmc_id": ids["pmc_id"],
        "abstract": abstract,
        "has_abstract": bool(abstract),
        "authors": extract_authors(article),
        "mesh_terms": extract_mesh_terms(article),
        "keywords": extract_keywords(article),
        "publication_types": extract_publication_types(article),
        "pubmed_status": extract_pubmed_status(article),
    }

    return result


def parse_pubmed_xml(xml_text: str) -> list[dict[str, Any]]:
    root = ET.fromstring(xml_text)

    articles = []

    for article in root.findall(".//PubmedArticle"):
        parsed = parse_pubmed_article(article)

        if parsed.get("pmid"):
            articles.append(parsed)

    return articles


# Output helpers

def write_per_pmid_jsons(
    rows: list[dict[str, Any]],
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    for row in rows:
        pmid = safe_str(row.get("pmid"))

        if not pmid:
            continue

        path = output_dir / f"{pmid}_pubmed.json"
        write_json(path, row)


def write_pmc_ids(path: Path, rows: list[dict[str, Any]]) -> None:
    pmc_ids = []

    for row in rows:
        pmc_id = normalize_pmc_id(row.get("pmc_id"))

        if pmc_id:
            pmc_ids.append(pmc_id)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(sorted(set(pmc_ids))) + "\n", encoding="utf-8")


def write_missing_pmids(
    path: Path,
    requested_pmids: list[str],
    found_rows: list[dict[str, Any]],
) -> list[str]:
    found = {safe_str(row.get("pmid")) for row in found_rows}
    missing = [pmid for pmid in requested_pmids if pmid not in found]

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(missing) + ("\n" if missing else ""), encoding="utf-8")

    return missing


def rows_for_csv(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    csv_rows = []

    for row in rows:
        csv_rows.append(
            {
                "pmid": safe_str(row.get("pmid")),
                "title": safe_str(row.get("title")),
                "year": safe_str(row.get("year")),
                "journal": safe_str(row.get("journal")),
                "doi": safe_str(row.get("doi")),
                "pmc_id": safe_str(row.get("pmc_id")),
                "has_abstract": bool(row.get("has_abstract")),
                "abstract_chars": len(safe_str(row.get("abstract"))),
                "authors_count": len(row.get("authors") or []),
                "mesh_terms_count": len(row.get("mesh_terms") or []),
                "keywords_count": len(row.get("keywords") or []),
                "publication_types": "; ".join(row.get("publication_types") or []),
                "pubmed_status": safe_str(row.get("pubmed_status")),
            }
        )

    return csv_rows


# Main public function

def run_pubmed_fetcher(
    pmid_input: Path,
    output_dir: Path,
    results_jsonl: Path,
    results_csv: Path,
    audit_json: Path,
    pmc_ids_txt: Path,
    missing_pmids_txt: Path,
    raw_dir: Path,
    batch_size: int = DEFAULT_BATCH_SIZE,
    timeout_seconds: int = 60,
    max_retries: int = 3,
    sleep_seconds: float = DEFAULT_SLEEP_SECONDS,
    limit: int | None = None,
) -> dict[str, Any]:
    pmids = load_pmids(pmid_input)

    if limit is not None:
        pmids = pmids[:limit]

    if not pmids:
        raise ValueError(f"No PMIDs found in input: {pmid_input}")

    output_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    batches = chunk_list(pmids, batch_size)

    all_rows = []
    batch_summaries = []
    errors = []

    for batch_index, batch_pmids in enumerate(batches, start=1):
        raw_path = raw_dir / f"batch_{batch_index:04d}.xml"

        try:
            xml_text = fetch_pubmed_batch_xml(
                pmids=batch_pmids,
                timeout_seconds=timeout_seconds,
                max_retries=max_retries,
                sleep_seconds=sleep_seconds,
            )

            raw_path.write_text(xml_text, encoding="utf-8")

            parsed_rows = parse_pubmed_xml(xml_text)
            all_rows.extend(parsed_rows)

            batch_summaries.append(
                {
                    "batch_index": batch_index,
                    "requested": len(batch_pmids),
                    "parsed": len(parsed_rows),
                    "raw_path": str(raw_path),
                    "status": "success",
                }
            )

        except Exception as exc:
            errors.append(
                {
                    "batch_index": batch_index,
                    "pmids": batch_pmids,
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                }
            )

            batch_summaries.append(
                {
                    "batch_index": batch_index,
                    "requested": len(batch_pmids),
                    "parsed": 0,
                    "raw_path": str(raw_path),
                    "status": "failed",
                }
            )

        time.sleep(sleep_seconds)

    # Deduplicate by PMID.
    by_pmid = {}

    for row in all_rows:
        pmid = safe_str(row.get("pmid"))

        if pmid:
            by_pmid[pmid] = row

    rows = [by_pmid[pmid] for pmid in pmids if pmid in by_pmid]

    write_jsonl(results_jsonl, rows)
    write_csv_rows(results_csv, rows_for_csv(rows))
    write_per_pmid_jsons(rows, output_dir)
    write_pmc_ids(pmc_ids_txt, rows)

    missing_pmids = write_missing_pmids(
        missing_pmids_txt,
        requested_pmids=pmids,
        found_rows=rows,
    )

    with_abstract = sum(1 for row in rows if bool(row.get("has_abstract")))
    without_abstract = sum(1 for row in rows if not bool(row.get("has_abstract")))
    with_pmc_id = sum(1 for row in rows if safe_str(row.get("pmc_id")))

    publication_years = Counter(
        safe_str(row.get("year")) or "unknown"
        for row in rows
    )

    audit = {
        "run_date": now_iso(),
        "pmid_input": str(pmid_input),
        "n_pmids_requested": len(pmids),
        "n_pubmed_records": len(rows),
        "n_missing_pmids": len(missing_pmids),
        "with_abstract": with_abstract,
        "without_abstract": without_abstract,
        "with_pmc_id": with_pmc_id,
        "publication_year_distribution": dict(publication_years),
        "batch_size": batch_size,
        "batches": batch_summaries,
        "errors": errors,
        "outputs": {
            "results_jsonl": str(results_jsonl),
            "results_csv": str(results_csv),
            "pmc_ids_txt": str(pmc_ids_txt),
            "missing_pmids_txt": str(missing_pmids_txt),
            "raw_dir": str(raw_dir),
            "per_pmid_json_dir": str(output_dir),
            "audit_json": str(audit_json),
        },
        "next_step": "Run Paperclip fetcher using pmc_ids_txt or PubMed metadata.",
    }

    write_json(audit_json, audit)

    return {
        "rows": rows,
        "missing_pmids": missing_pmids,
        "audit": audit,
    }
