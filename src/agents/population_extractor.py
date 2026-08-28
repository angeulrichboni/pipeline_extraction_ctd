"""Extract study population, location, age and sex from segmented documents."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from src.config.settings import settings
from src.io.json_io import read_json, write_json
from src.agents.document_chunks import (
    extract_title_and_abstract,
    extract_document_chunks,
    write_reasoning_file,
)


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def safe_str(value: Any) -> str:
    if value is None:
        return ""

    text = str(value).strip()

    if text.lower() in {"nan", "none", "null"}:
        return ""

    return text


# ============================================================
# Normalization
# ============================================================

EXPECTED_FIELDS = [
    "pmid",
    "study_country",
    "study_city_or_region",
    "study_location_detail",
    "study_population",
    "age_group",
    "age_min",
    "age_max",
    "age_mean",
    "sex",
    "population_details",
    "evidence_sentence",
    "source_section",
    "confidence",
    "status",
]


def normalize_number_or_none(value: Any) -> float | None:
    if value is None:
        return None

    text = safe_str(value)

    if not text or text.lower() in {"not_reported", "ambiguous", "unknown"}:
        return None

    match = re.search(r"\d+(?:\.\d+)?", text)

    if not match:
        return None

    return float(match.group(0))


def normalize_choice(value: Any, allowed: set[str], default: str) -> str:
    text = safe_str(value).lower()

    if text in allowed:
        return text

    return default


COUNTRY_ALIASES = {
    "usa": "United States",
    "us": "United States",
    "u.s.": "United States",
    "u.s.a.": "United States",
    "united states of america": "United States",
    "california": "United States",

    "uk": "United Kingdom",
    "england": "United Kingdom",
    "scotland": "United Kingdom",
    "wales": "United Kingdom",
    "england and wales": "United Kingdom",
    "great britain": "United Kingdom",

    "the netherlands": "Netherlands",

    "korea": "South Korea",
    "republic of korea": "South Korea",
    "south korea": "South Korea",
}


def normalize_country_value(raw: str) -> str:
    """Normalise un champ study_country : une valeur simple ou une liste
    ';'-separee de pays. Chaque pays est mappe vers son nom canonique via
    COUNTRY_ALIASES, les doublons resultants sont retires, et la liste est
    rejointe avec un separateur homogene ('; ')."""

    text = safe_str(raw)

    if not text or text.lower() == "not_reported":
        return "not_reported"

    parts = [p.strip() for p in text.split(";") if p.strip()]

    if not parts:
        return "not_reported"

    normalized_parts = []

    for part in parts:
        if part.lower() == "not_reported":
            continue

        canonical = COUNTRY_ALIASES.get(part.lower(), part)

        if canonical not in normalized_parts:
            normalized_parts.append(canonical)

    if not normalized_parts:
        return "not_reported"

    return "; ".join(normalized_parts)


def normalize_population_location_payload(
    pmid: str,
    payload: dict[str, Any],
) -> dict[str, Any]:

    row = {}

    for field in EXPECTED_FIELDS:
        row[field] = payload.get(field)

    row["pmid"] = pmid

    text_fields = [
        "study_city_or_region",
        "study_location_detail",
        "study_population",
        "age_group",
        "population_details",
        "evidence_sentence",
        "source_section",
    ]

    for field in text_fields:
        value = safe_str(row.get(field))
        row[field] = value if value else "not_reported"

    row["study_country"] = normalize_country_value(row.get("study_country"))

    row["age_min"] = normalize_number_or_none(row.get("age_min"))
    row["age_max"] = normalize_number_or_none(row.get("age_max"))
    row["age_mean"] = normalize_number_or_none(row.get("age_mean"))

    row["sex"] = normalize_choice(
        row.get("sex"),
        allowed={"male", "female", "both", "not_reported", "ambiguous"},
        default="review",
    )

    row["confidence"] = normalize_choice(
        row.get("confidence"),
        allowed={"high", "medium", "low"},
        default="low",
    )

    row["status"] = normalize_choice(
        row.get("status"),
        allowed={"explicit", "not_reported", "ambiguous", "multiple", "review"},
        default="review",
    )

    return row


# ============================================================
# Prompt
# ============================================================

def build_population_location_prompt(
    pmid: str,
    document_text: str,
) -> list[dict[str, str]]:

    system_prompt = """
You are a scientific information extraction agent.

Task:
Extract study population, geographic location, age, and sex information from biomedical article text.

Strict scientific rules:
- Extract only information explicitly stated in the provided text.
- Do not infer country, city, age, or sex from author affiliations, journal name, PMID, references, or external knowledge.
- Do not infer a country from a city unless the country is explicitly written in the provided text.
- Do not infer sex unless the study text explicitly states male, female, men, women, boys, girls, both, or equivalent.
- If information is absent, return "not_reported".
- If information is vague, return "ambiguous".
- If multiple countries, regions, populations, or age groups are explicitly present, return them as a semicolon-separated string and set status to "multiple".
- Always provide a short evidence sentence copied from the provided text.
- Before answering, think step by step in the "reasoning" field: identify which passages state population/location/age/sex explicitly, and note why anything else was left as not_reported or ambiguous. Keep it concise (2-5 short sentences).
- Return only valid JSON.
- No markdown.
- No code fences.

Return exactly this JSON schema:

{
  "reasoning": "brief step-by-step notes on what was found and why",
  "pmid": "string",
  "study_country": "string or not_reported",
  "study_city_or_region": "string or not_reported",
  "study_location_detail": "string or not_reported",
  "study_population": "string or not_reported",
  "age_group": "string or not_reported",
  "age_min": "number or null",
  "age_max": "number or null",
  "age_mean": "number or null",
  "sex": "male/female/both/not_reported/ambiguous",
  "population_details": "string or not_reported",
  "evidence_sentence": "string or not_reported",
  "source_section": "string or not_reported",
  "confidence": "high/medium/low",
  "status": "explicit/not_reported/ambiguous/multiple/review"
}
""".strip()

    user_prompt = f"""
PMID:
{pmid}

DOCUMENT:
{document_text}
""".strip()

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


# ============================================================
# One PMID extraction
# ============================================================

def run_population_extractor_for_pmid(
    pmid: str,
    segmented_document_path: Path,
    output_json: Path,
    output_state_json: Path,
    raw_response_path: Path,
    repair_response_path: Path,
    reasoning_dir: Path,
    client: Any,
    model: str | None = None,
    max_output_tokens: int = 1500,
) -> dict[str, Any]:
    segmented_payload = read_json(segmented_document_path)

    title, abstract = extract_title_and_abstract(segmented_payload)
    chunks = extract_document_chunks(segmented_payload)

    # Population/localisation est une reponse unique par PMID (pas une liste
    # a dedupliquer) : on envoie tout le document en un seul appel plutot que
    # de faire du Map-Reduce comme pour pollutant/outcome/effect_measure.
    # Aucune troncature : toutes les sections deja segmentees sont incluses.
    document_parts = []

    if title:
        document_parts.append(f"[TITLE]\n{title}")

    if abstract:
        document_parts.append(f"[ABSTRACT]\n{abstract}")

    for chunk in chunks:
        if chunk["section_title"] == "abstract_only":
            continue
        document_parts.append(f"[SECTION: {chunk['section_title']}]\n{chunk['chunk_text']}")

    document_text = "\n\n".join(document_parts)

    messages = build_population_location_prompt(
        pmid=pmid,
        document_text=document_text,
    )

    parsed_payload, first_response, repair_response = client.chat_json(
        messages=messages,
        model=model,
        max_tokens=max_output_tokens,
        temperature=0.0,
        repair_on_fail=True,
    )

    raw_response_path.parent.mkdir(parents=True, exist_ok=True)
    raw_response_path.write_text(first_response.content, encoding="utf-8")

    repair_response_path.parent.mkdir(parents=True, exist_ok=True)

    if repair_response is not None:
        repair_response_path.write_text(repair_response.content, encoding="utf-8")
    else:
        repair_response_path.write_text("", encoding="utf-8")

    normalized = normalize_population_location_payload(
        pmid=pmid,
        payload=parsed_payload,
    )

    reasoning_text = safe_str(parsed_payload.get("reasoning"))
    reasoning_path = ""

    if reasoning_text:
        reasoning_path = write_reasoning_file(
            reasoning_dir=reasoning_dir,
            pmid=pmid,
            agent_name="population_extractor",
            entries=[{"chunk_index": 1, "section_title": "full_document", "reasoning": reasoning_text}],
        )

    output_payload = {
        **normalized,
        "created_at": now_iso(),
        "provider": "ILAAS",
        "base_url": settings.ilaas_base_url,
        "model": model or settings.ilaas_model,
        "agent": "population_extractor",
        "metadata": {
            "segmented_document_path": str(segmented_document_path),
            "raw_response_path": str(raw_response_path),
            "repair_response_path": str(repair_response_path),
            "reasoning_path": reasoning_path,
            "json_repair_used": repair_response is not None,
            "n_sections_used": len(chunks),
        },
    }

    state_payload = {
        "pmid": pmid,
        "population_extractor": output_payload,
    }

    write_json(output_json, output_payload)
    write_json(output_state_json, state_payload)

    return output_payload