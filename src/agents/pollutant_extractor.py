"""Extract and normalize air-pollution mentions from segmented documents."""

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
    build_chunk_text_with_context,
    write_reasoning_file,
)


# Constants

PROJECT_TARGET_KEYS = {
    "pm",
    "pm25",
    "pm10",
    "pm1",
    "ufp",
    "no",
    "no2",
    "o3",
    "ozone",
}

CONTEXTUAL_AIR_POLLUTANT_KEYS = {
    "co",
    "carbonmonoxide",
    "so2",
    "sulfurdioxide",
    "sulphurdioxide",
    "nox",
    "nitrogenoxides",
    "h2s",
    "hydrogensulfide",
}

SECONDARY_AIR_POLLUTANT_KEYS = {
    "blackcarbon",
    "soot",
    "bc",
}

SOURCE_MARKER_KEYS = {
    "woodsmoke",
    "trafficrelatedpollution",
    "trafficrelatedpollutants",
    "trafficrelatedairpollution",
    "roadproximity",
    "roadwayproximity",
    "proximitytoroads",
    "trp",

    # Umbrella exposure/source terms
    "airpollution",
    "airpollutants",
    "ambientairpollution",
}

POLLUTANT_CONTEXT_KEYWORDS = [
    "pm2.5",
    "pm 2.5",
    "pm10",
    "pm 10",
    "pm1",
    "pm 1",
    "particulate matter",
    "particles",
    "ultrafine",
    "ufp",
    "nitric oxide",
    "nitrogen dioxide",
    "nitrogen oxides",
    "no2",
    "nox",
    "no ",
    " ozone",
    "o3",
    "carbon monoxide",
    "co ",
    "sulfur dioxide",
    "sulphur dioxide",
    "so2",
    "black carbon",
    "soot",
    "woodsmoke",
    "wood smoke",
    "traffic",
    "road",
    "roadway",
    "air pollution",
    "air pollutants",
    "ambient air",
    "hydrogen sulfide",
    "hydrogen sulphide",
    "h2s",
]


# Helpers

def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def safe_str(value: Any) -> str:
    if value is None:
        return ""

    text = str(value).strip()

    if text.lower() in {"nan", "none", "null"}:
        return ""

    return text


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def safe_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    return []


def normalize_text(value: Any) -> str:
    text = safe_str(value).lower()
    text = text.replace("₂", "2").replace("₃", "3").replace("ₓ", "x")
    text = text.replace("<sub>2</sub>", "2")
    text = text.replace("<sub>3</sub>", "3")
    text = text.replace("<sub>x</sub>", "x")
    text = text.replace("<sub>X</sub>", "x")
    text = text.replace("μ", "µ")
    text = text.replace("–", "-").replace("—", "-")
    text = text.replace("_", " ")
    text = text.replace("-", " ")
    text = " ".join(text.split())
    return text


def compact(value: Any) -> str:
    text = normalize_text(value)
    return re.sub(r"[^a-z0-9]", "", text)


def normalize_pollutant_key(value: Any) -> str:
    text = compact(value)

    aliases = {
        "particulatematter": "pm",
        "pm": "pm",

        "pm25": "pm25",
        "particulatematter25": "pm25",

        "pm10": "pm10",
        "pm1": "pm1",

        "ultrafineparticles": "ufp",
        "ultrafineparticle": "ufp",
        "ufp": "ufp",

        "nitricoxide": "no",
        "no": "no",

        "nitrogendioxide": "no2",
        "no2": "no2",

        "nitrogenoxides": "nox",
        "nox": "nox",

        "ozone": "o3",
        "o3": "o3",

        "carbonmonoxide": "co",
        "co": "co",

        "sulfurdioxide": "so2",
        "sulphurdioxide": "so2",
        "so2": "so2",

        "hydrogensulfide": "h2s",
        "hydrogensulphide": "h2s",
        "h2s": "h2s",

        "blackcarbon": "blackcarbon",
        "bc": "blackcarbon",
        "soot": "soot",

        "woodsmoke": "woodsmoke",
        "woodsmokepollution": "woodsmoke",

        "trafficrelatedpollution": "trafficrelatedpollution",
        "trafficrelatedpollutants": "trafficrelatedpollutants",
        "trafficrelatedairpollution": "trafficrelatedpollution",
        "trp": "trp",

        "roadproximity": "roadproximity",
        "roadwayproximity": "roadwayproximity",
        "proximitytoroads": "proximitytoroads",

        "airpollution": "airpollution",
        "airpollutants": "airpollutants",
        "ambientairpollution": "ambientairpollution",
    }

    return aliases.get(text, text)


def detect_pollutant_key_from_text(value: Any) -> str:
    """Detect a normalized pollutant key from a raw mention."""
    text = normalize_text(value)
    compact_text = compact(value)

    alias_key = normalize_pollutant_key(value)

    if alias_key and alias_key != compact_text:
        return alias_key

    # PM size-specific
    if (
        "pm2.5" in text
        or "pm 2.5" in text
        or ("2.5" in text and "particulate" in text)
    ):
        return "pm25"

    if (
        "pm10" in text
        or "pm 10" in text
        or ("10" in text and "particulate" in text)
    ):
        return "pm10"

    if "pm1" in text or "pm 1" in text:
        return "pm1"

    if "ultrafine" in text:
        return "ufp"

    if "particulate matter" in text or "particles" in text:
        return "pm"

    # Gases
    if "nitric oxide" in text or compact_text == "no":
        return "no"

    if "nitrogen dioxide" in text or compact_text == "no2":
        return "no2"

    if "nitrogen oxides" in text or compact_text == "nox":
        return "nox"

    if "ozone" in text or compact_text == "o3":
        return "o3"

    if "carbon monoxide" in text or compact_text == "co":
        return "co"

    if (
        "sulfur dioxide" in text
        or "sulphur dioxide" in text
        or compact_text == "so2"
    ):
        return "so2"

    if (
        "hydrogen sulfide" in text
        or "hydrogen sulphide" in text
        or compact_text == "h2s"
    ):
        return "h2s"

    # Secondary/source markers
    if "black carbon" in text:
        return "blackcarbon"

    if "soot" in text:
        return "soot"

    if "woodsmoke" in text or "wood smoke" in text:
        return "woodsmoke"

    if "traffic" in text:
        return "trafficrelatedpollution"

    if (
        "road proximity" in text
        or "roadway proximity" in text
        or "proximity to roads" in text
        or "roads" in text
    ):
        return "roadproximity"

    if "ambient air pollution" in text:
        return "ambientairpollution"

    if "air pollutants" in text:
        return "airpollutants"

    if "air pollution" in text:
        return "airpollution"

    return alias_key


def infer_pollutant_general_and_specific(
    original_mention: str,
    pollutant_general: str = "",
    pollutant_specific: str = "",
) -> tuple[str, str]:
    """
    Normalize pollutant_general and pollutant_specific from model output
    and/or original mention.
    """
    raw = pollutant_specific or pollutant_general or original_mention
    key = detect_pollutant_key_from_text(raw)

    mapping = {
        "pm": ("PM", "particulate matter"),
        "pm25": ("PM", "PM2.5"),
        "pm10": ("PM", "PM10"),
        "pm1": ("PM", "PM1"),
        "ufp": ("PM", "ultrafine particles"),

        "no": ("NO", "NO"),
        "no2": ("NO2", "NO2"),
        "nox": ("NOx", "NOx"),
        "o3": ("O3", "O3"),

        "co": ("CO", "CO"),
        "so2": ("SO2", "SO2"),
        "h2s": ("H2S", "H2S"),

        "blackcarbon": ("black_carbon", "black carbon"),
        "soot": ("soot", "soot"),
        "woodsmoke": ("woodsmoke", "woodsmoke"),

        "trafficrelatedpollution": (
            "traffic_related_pollution",
            "traffic-related pollution",
        ),
        "trafficrelatedpollutants": (
            "traffic_related_pollution",
            "traffic-related pollutants",
        ),
        "trafficrelatedairpollution": (
            "traffic_related_pollution",
            "traffic-related air pollution",
        ),
        "trp": ("traffic_related_pollution", "TRP"),

        "roadproximity": ("road_proximity", "road proximity"),
        "roadwayproximity": ("road_proximity", "roadway proximity"),
        "proximitytoroads": ("road_proximity", "proximity to roads"),

        "airpollution": ("air_pollution", "air pollution"),
        "airpollutants": ("air_pollution", "air pollutants"),
        "ambientairpollution": ("air_pollution", "ambient air pollution"),
    }

    if key in mapping:
        return mapping[key]

    general = safe_str(pollutant_general) or "other"
    specific = safe_str(pollutant_specific) or safe_str(original_mention) or "unknown"

    return general, specific


def compute_is_project_target(
    pollutant_general: str,
    pollutant_specific: str,
    original_mention: str,
) -> bool:
    keys = {
        detect_pollutant_key_from_text(pollutant_general),
        detect_pollutant_key_from_text(pollutant_specific),
        detect_pollutant_key_from_text(original_mention),
    }

    return bool(keys & PROJECT_TARGET_KEYS)


def infer_pollutant_role(
    pollutant_general: str,
    pollutant_specific: str,
    original_mention: str,
    is_project_target: bool,
) -> str:
    if is_project_target:
        return "target"

    keys = {
        detect_pollutant_key_from_text(pollutant_general),
        detect_pollutant_key_from_text(pollutant_specific),
        detect_pollutant_key_from_text(original_mention),
    }

    if keys & CONTEXTUAL_AIR_POLLUTANT_KEYS:
        return "contextual"

    if keys & SECONDARY_AIR_POLLUTANT_KEYS:
        return "secondary"

    if keys & SOURCE_MARKER_KEYS:
        return "source_marker"

    original_text = normalize_text(original_mention)

    if "traffic related" in original_text:
        return "source_marker"

    if "road" in original_text:
        return "source_marker"

    if "air pollution" in original_text:
        return "source_marker"

    if "air pollutants" in original_text:
        return "source_marker"

    if "ambient air" in original_text:
        return "source_marker"

    return "ambiguous"



# Prompt

def build_pollutant_prompt(
    pmid: str,
    document_text: str,
) -> list[dict[str, str]]:
    system_prompt = """
You are a scientific information extraction agent.

Task:
Extract the unique air pollutants, air pollution exposures, and air pollution source markers explicitly mentioned in the document.

Rules:
- Return ONE item per unique pollutant/exposure concept.
- Do NOT return one item per sentence.
- Do NOT duplicate the same pollutant.
- Do NOT infer pollutants not explicitly mentioned.
- Keep evidence_sentence short.
- Before listing pollutants_found, think step by step in the "reasoning" field: identify candidate mentions, check each against the rules above, and note why any candidate was excluded. Keep it concise (2-5 short sentences).
- Return only valid JSON.
- No markdown.
- No code fences.
""".strip()

    user_prompt = f"""
PMID: {pmid}

Extract unique mentions among these categories:
- PM, PM2.5, PM10, PM1, ultrafine particles
- NO, NO2, NOx
- O3 / ozone
- CO
- SO2
- H2S
- black carbon / soot
- woodsmoke
- traffic-related pollution
- road proximity / proximity to roads
- air pollution / air pollutants / ambient air pollution

Return ONLY this compact JSON structure:

{{
  "reasoning": "brief step-by-step notes on candidate mentions and inclusion/exclusion decisions",
  "pollutants_found": [
    {{
      "pollutant_original_mention": "exact pollutant/exposure mention",
      "evidence_sentence": "short supporting sentence",
      "source_section": "section name if available",
      "confidence": 0.95
    }}
  ],
  "warnings": [],
  "errors": []
}}

Maximum output:
- Usually 3 to 12 items.
- No duplicate normalized pollutant concepts.

Document pollutant-focused context:
{document_text}
""".strip()

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


# Normalization and validation

def normalize_pollutant_item(item: dict[str, Any]) -> dict[str, Any]:
    original = safe_str(item.get("pollutant_original_mention"))
    general_raw = safe_str(item.get("pollutant_general"))
    specific_raw = safe_str(item.get("pollutant_specific"))

    general, specific = infer_pollutant_general_and_specific(
        original_mention=original,
        pollutant_general=general_raw,
        pollutant_specific=specific_raw,
    )

    is_project_target = compute_is_project_target(
        pollutant_general=general,
        pollutant_specific=specific,
        original_mention=original,
    )

    role = infer_pollutant_role(
        pollutant_general=general,
        pollutant_specific=specific,
        original_mention=original,
        is_project_target=is_project_target,
    )

    confidence = safe_float(item.get("confidence"), default=0.0)

    if confidence < 0:
        confidence = 0.0

    if confidence > 1:
        confidence = 1.0

    raw_source_type = safe_str(item.get("source_type"))

    if "|" in raw_source_type:
        source_type = "segmented_document"
    else:
        source_type = raw_source_type or "segmented_document"

    return {
        "pollutant_general": general,
        "pollutant_specific": specific,
        "pollutant_original_mention": original or specific,
        "is_project_target": is_project_target,
        "is_target_pollutant": is_project_target,
        "pollutant_role": role,
        "keep_for_final_analysis": is_project_target,
        "normalization_note": safe_str(item.get("normalization_note")),
        "evidence_sentence": safe_str(item.get("evidence_sentence")),
        "source_section": safe_str(item.get("source_section")),
        "source_type": source_type,
        "confidence": confidence,
    }


def pollutant_priority(item: dict[str, Any]) -> tuple[int, float, int]:
    role = safe_str(item.get("pollutant_role"))

    role_priority = {
        "target": 5,
        "contextual": 4,
        "secondary": 3,
        "source_marker": 2,
        "ambiguous": 1,
    }.get(role, 0)

    confidence = safe_float(item.get("confidence"), default=0.0)
    evidence_len = len(safe_str(item.get("evidence_sentence")))

    return role_priority, confidence, evidence_len


def deduplicate_pollutants(
    pollutants: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep one row per normalized pollutant concept."""
    by_key: dict[str, dict[str, Any]] = {}

    for item in pollutants:
        key = detect_pollutant_key_from_text(
            item.get("pollutant_specific")
            or item.get("pollutant_general")
            or item.get("pollutant_original_mention")
        )

        if not key:
            key = normalize_text(item.get("pollutant_original_mention"))

        if not key:
            continue

        if key not in by_key:
            by_key[key] = item
            continue

        existing = by_key[key]

        if pollutant_priority(item) > pollutant_priority(existing):
            by_key[key] = item

    return list(by_key.values())


def normalize_pollutant_payload(payload: dict[str, Any]) -> dict[str, Any]:
    raw_pollutants = safe_list(payload.get("pollutants_found"))

    pollutants = [
        normalize_pollutant_item(item)
        for item in raw_pollutants
        if isinstance(item, dict)
    ]

    pollutants = deduplicate_pollutants(pollutants)

    warnings = safe_list(payload.get("warnings"))
    errors = safe_list(payload.get("errors"))

    return {
        "pollutants_found": pollutants,
        "warnings": warnings,
        "errors": errors,
    }


# Public API

def run_pollutant_extractor_for_pmid(
    pmid: str,
    segmented_document_path: Path,
    output_json: Path,
    output_state_json: Path,
    raw_response_path: Path,
    repair_response_path: Path,
    reasoning_dir: Path,
    client: Any,
    model: str | None = None,
    max_output_tokens: int = 3000,
) -> dict[str, Any]:
    segmented_payload = read_json(segmented_document_path)

    title, abstract = extract_title_and_abstract(segmented_payload)
    chunks = extract_document_chunks(segmented_payload)

    combined_pollutants: list[Any] = []
    combined_warnings: list[Any] = []
    combined_errors: list[Any] = []
    reasoning_entries: list[dict[str, Any]] = []
    raw_response_parts: list[str] = []
    repair_used_any = False

    for chunk in chunks:
        chunk_text = build_chunk_text_with_context(title, abstract, chunk)

        messages = build_pollutant_prompt(
            pmid=pmid,
            document_text=chunk_text,
        )

        chunk_payload, first_response, repair_response = client.chat_json(
            messages=messages,
            model=model,
            max_tokens=max_output_tokens,
            temperature=0.0,
            repair_on_fail=True,
        )

        raw_response_parts.append(
            f"--- chunk {chunk['chunk_index']} ({chunk['section_title']}) ---\n"
            f"{first_response.content}"
        )

        if repair_response is not None:
            repair_used_any = True

        combined_pollutants.extend(safe_list(chunk_payload.get("pollutants_found")))
        combined_warnings.extend(safe_list(chunk_payload.get("warnings")))
        combined_errors.extend(safe_list(chunk_payload.get("errors")))

        chunk_reasoning = safe_str(chunk_payload.get("reasoning"))

        if chunk_reasoning:
            reasoning_entries.append(
                {
                    "chunk_index": chunk["chunk_index"],
                    "section_title": chunk["section_title"],
                    "reasoning": chunk_reasoning,
                }
            )

    raw_response_path.parent.mkdir(parents=True, exist_ok=True)
    raw_response_path.write_text("\n\n".join(raw_response_parts), encoding="utf-8")

    repair_response_path.parent.mkdir(parents=True, exist_ok=True)
    repair_response_path.write_text("used" if repair_used_any else "", encoding="utf-8")

    normalized_payload = normalize_pollutant_payload(
        {
            "pollutants_found": combined_pollutants,
            "warnings": combined_warnings,
            "errors": combined_errors,
        }
    )

    pollutants_found = normalized_payload["pollutants_found"]
    warnings = normalized_payload["warnings"]
    errors = normalized_payload["errors"]

    reasoning_path = write_reasoning_file(
        reasoning_dir=reasoning_dir,
        pmid=pmid,
        agent_name="pollutant_extractor",
        entries=reasoning_entries,
    )

    output_payload = {
        "pmid": pmid,
        "created_at": now_iso(),
        "provider": "ILAAS",
        "base_url": settings.ilaas_base_url,
        "model": model or settings.ilaas_model,
        "agent": "pollutant_extractor",
        "pollutants_found": pollutants_found,
        "warnings": warnings,
        "errors": errors,
        "metadata": {
            "segmented_document_path": str(segmented_document_path),
            "raw_response_path": str(raw_response_path),
            "repair_response_path": str(repair_response_path),
            "reasoning_path": reasoning_path,
            "json_repair_used": repair_used_any,
            "chunks_processed": len(chunks),
            "n_pollutants_found": len(pollutants_found),
        },
    }

    state_payload = {
        "pmid": pmid,
        "pollutant_extractor": output_payload,
        "pollutants_found": pollutants_found,
        "warnings": warnings,
        "errors": errors,
        "metadata": output_payload["metadata"],
    }

    write_json(output_json, output_payload)
    write_json(output_state_json, state_payload)

    return output_payload
