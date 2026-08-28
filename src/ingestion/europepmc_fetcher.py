"""
Recuperation de texte complet via l'API Europe PMC (EMBL-EBI), en secours de
Paperclip.

Endpoint documente : https://www.ebi.ac.uk/europepmc/webservices/rest/{PMCID}/fullTextXML
(API publique, sans cle, source : https://europepmc.org/RestfulWebService)

Le format de retour (dict avec les memes cles que fetch_one_paperclip_document)
est volontairement identique a celui de src.ingestion.paperclip_fetcher, pour
pouvoir servir de remplacement direct sans toucher au reste du pipeline
(merge_manifest_with_paperclip, etc. consomment ce dict tel quel).
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import requests

DEFAULT_TIMEOUT_SECONDS = 60
DEFAULT_MAX_RETRIES = 3
DEFAULT_SLEEP_SECONDS = 1.0
MIN_FULL_TEXT_CHARS = 200

EUROPEPMC_FULLTEXT_URL_TEMPLATE = (
    "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmc_id}/fullTextXML"
)


def clean_text(value: Any) -> str:
    if value is None:
        return ""

    text = str(value).strip()
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def is_valid_full_text(text: str, min_chars: int = MIN_FULL_TEXT_CHARS) -> bool:
    return bool(text) and len(text) >= min_chars


def europepmc_fulltext_url(pmc_id: str) -> str:
    return EUROPEPMC_FULLTEXT_URL_TEMPLATE.format(pmc_id=pmc_id)


def parse_jats_fulltext_xml(xml_text: str) -> str:
    """Extrait le texte brut d'un XML JATS (format Europe PMC / PMC)."""
    xml_text = clean_text(xml_text)

    if not xml_text:
        return ""

    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return ""

    parts: list[str] = []

    title_el = root.find(".//article-title")
    if title_el is not None:
        title_text = "".join(title_el.itertext()).strip()
        if title_text:
            parts.append(title_text)

    abstract_el = root.find(".//abstract")
    if abstract_el is not None:
        abstract_text = "".join(abstract_el.itertext()).strip()
        if abstract_text:
            parts.append(abstract_text)

    body_el = root.find(".//body")

    if body_el is not None:
        for paragraph in body_el.iter():
            tag = paragraph.tag.rsplit("}", 1)[-1]

            if tag not in {"p", "title"}:
                continue

            paragraph_text = "".join(paragraph.itertext()).strip()

            if paragraph_text:
                parts.append(paragraph_text)

    return clean_text("\n\n".join(parts))


def fetch_europepmc_fulltext_xml(
    pmc_id: str,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    max_retries: int = DEFAULT_MAX_RETRIES,
    sleep_seconds: float = DEFAULT_SLEEP_SECONDS,
) -> tuple[str, dict[str, Any]]:
    url = europepmc_fulltext_url(pmc_id)

    last_error = ""
    last_status_code = ""

    for attempt in range(1, max_retries + 1):
        try:
            response = requests.get(url, timeout=timeout_seconds)
            last_status_code = str(response.status_code)

            if response.status_code == 200 and response.text:
                return response.text, {
                    "url": url,
                    "status_code": last_status_code,
                    "fetch_mode": "europepmc",
                    "attempts": attempt,
                }

            if response.status_code == 404:
                # Pas de texte complet disponible pour ce PMC ID sur Europe PMC.
                return "", {
                    "url": url,
                    "status_code": last_status_code,
                    "fetch_mode": "europepmc",
                    "attempts": attempt,
                }

            last_error = f"HTTP {response.status_code}"

        except requests.RequestException as exc:
            last_error = str(exc)

        if attempt < max_retries:
            time.sleep(sleep_seconds * attempt)

    return "", {
        "url": url,
        "status_code": last_status_code,
        "fetch_mode": "europepmc",
        "attempts": max_retries,
        "error": last_error,
    }


def fetch_one_europepmc_document(
    pmid: str,
    pmc_id: str,
    full_text_dir: Path,
    raw_dir: Path,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    max_retries: int = DEFAULT_MAX_RETRIES,
    sleep_seconds: float = DEFAULT_SLEEP_SECONDS,
) -> dict[str, Any]:
    """Meme forme de retour que fetch_one_paperclip_document, pour pouvoir
    servir de remplacement direct sans toucher au reste du pipeline."""

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

    xml_text, fetch_metadata = fetch_europepmc_fulltext_xml(
        pmc_id=pmc_id,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        sleep_seconds=sleep_seconds,
    )

    fetch_url = str(fetch_metadata.get("url", ""))
    http_status_code = str(fetch_metadata.get("status_code", ""))

    raw_path = raw_dir / f"{pmid}_europepmc_raw.xml"
    if xml_text:
        raw_path.write_text(xml_text, encoding="utf-8")

    full_text = parse_jats_fulltext_xml(xml_text) if xml_text else ""

    if not is_valid_full_text(full_text):
        return {
            "pmid": pmid,
            "pmc_id": pmc_id,
            "paperclip_attempted": True,
            "paperclip_status": "no_full_text",
            "has_full_text": False,
            "full_text_path": "",
            "raw_content_path": str(raw_path) if xml_text else "",
            "invalid_content_path": "",
            "paperclip_content_chars": len(full_text),
            "fetch_url": fetch_url,
            "http_status_code": http_status_code,
            "fetch_mode": "europepmc",
            "error": fetch_metadata.get("error", "No full text on Europe PMC for this PMC ID."),
        }

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
        "fetch_mode": "europepmc",
        "error": "",
    }
