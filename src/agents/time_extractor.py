# -*- coding: utf-8 -*-
"""Extract exposure temporality/window for pollutant-outcome associations."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from src.config.settings import settings
from src.io.json_io import read_json, write_json
from src.agents.document_chunks import write_reasoning_file


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def safe_str(value: Any) -> str:
    if value is None:
        return ""

    text = str(value).strip()

    if text.lower() in {"nan", "none", "null"}:
        return ""

    return text


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", safe_str(text)).strip()


def split_sentences(text: str) -> list[str]:
    text = normalize_space(text)
    if not text:
        return []

    return [
        s.strip()
        for s in re.split(r"(?<=[.!?])\s+", text)
        if s.strip()
    ]


# ============================================================
# Article text (depuis le document deja segmente, pas de fichier
# intermediaire separe)
# ============================================================

TEMPORAL_KEYWORDS = [
    "short-term", "short term", "long-term", "long term", "acute", "chronic",
    "daily", "hourly", "weekly", "monthly", "annual", "annually", "yearly",
    "years", "days", "hours", "lag", "lags", "lagged", "lag 0", "lag0",
    "lag 1", "lag1", "moving average", "averaged over", "average exposure",
    "cumulative", "cumulative exposure", "prenatal", "pregnancy",
    "gestational", "trimester", "birth", "lifetime", "residential history",
    "exposure window", "exposure period", "exposure assessment",
    "exposure estimates", "exposure was assessed",
    "concentrations were estimated",
]


def collect_article_text(payload: dict[str, Any]) -> str:
    """Reconstruit le texte complet d'un document deja segmente (titre,
    abstract, toutes les sections/chunks), pour la selection de phrases
    par mot-cle ci-dessous."""

    parts = []

    for key in ["title", "article_title", "abstract"]:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(f"[{key.upper()}]\n{value.strip()}")

    for key in ["focus_chunks", "chunks", "selected_chunks", "full_text_chunks"]:
        value = payload.get(key)

        if not isinstance(value, list):
            continue

        for item in value:
            if not isinstance(item, dict):
                continue

            section_title = (
                item.get("section_title") or item.get("title")
                or item.get("section") or item.get("heading") or "unknown_section"
            )
            text = (
                item.get("chunk_text") or item.get("text")
                or item.get("content") or item.get("section_text") or ""
            )

            if text:
                parts.append(f"[SECTION: {section_title}]\n{text}")

        if value:
            break

    return "\n\n".join(parts)


def build_temporal_context(
    article_text: str,
    pollutant: str,
    outcome: str,
    association_evidence: str,
    max_chars: int = 18000,
) -> str:

    sentences = split_sentences(article_text)

    selected = []

    pollutant_l = pollutant.lower()
    outcome_l = outcome.lower()

    for sent in sentences:
        s = sent.lower()

        has_temporal = any(k in s for k in TEMPORAL_KEYWORDS)
        has_pollutant = pollutant_l and pollutant_l in s
        has_outcome = outcome_l and outcome_l in s

        if has_temporal or has_pollutant or has_outcome:
            selected.append(sent)

    context_parts = []

    if association_evidence:
        context_parts.append(f"[ASSOCIATION_EVIDENCE]\n{association_evidence}")

    if selected:
        context_parts.append("[ARTICLE_TEMPORAL_CONTEXT]\n" + "\n".join(selected))
    else:
        context_parts.append("[ARTICLE_TEXT_PREFIX]\n" + article_text[:max_chars])

    context = "\n\n".join(context_parts)

    return context[:max_chars]


# ============================================================
# Prompt
# ============================================================

def build_exposure_temporal_prompt(item: dict[str, Any]) -> list[dict[str, str]]:

    system_prompt = """
You are a scientific information extraction agent.

Task:
Extract the exposure temporality/window for ONE pollutant-health association.

Strict rules:
- Extract only information explicitly stated in the provided text.
- Do not infer exposure duration from disease type, study type, pollutant type, or external knowledge.
- Do not guess.
- If the temporal information is absent, return "not_reported".
- If the temporal information is vague, return "ambiguous".
- If multiple temporal windows are explicitly present for the same association, return all in semicolon-separated form and set status to "multiple".
- The extraction must correspond to the given pollutant and outcome association.
- Always provide a short evidence sentence copied from the provided text.
- Before answering, think step by step in the "reasoning" field: identify which passages mention the exposure window for this specific pollutant-outcome pair, and note why anything else was left as not_reported or ambiguous. Keep it concise (2-5 short sentences).
- Return only valid JSON.
- No markdown.
- No code fences.

Allowed exposure_window_category values:
- short_term
- long_term
- prenatal
- trimester_specific
- early_life
- lifetime
- occupational
- cumulative
- lagged
- repeated_measure
- not_reported
- ambiguous
- multiple

Return exactly this JSON schema:

{
  "reasoning": "brief step-by-step notes on what was found and why",
  "association_id": "string",
  "pmid": "string",
  "exposure_window_category": "short_term/long_term/prenatal/trimester_specific/early_life/lifetime/occupational/cumulative/lagged/repeated_measure/not_reported/ambiguous/multiple",
  "exposure_window_text": "string or not_reported",
  "exposure_duration_value": "number or null",
  "exposure_duration_unit": "hour/day/week/month/year/trimester/pregnancy/lifetime/not_reported",
  "exposure_lag": "string or not_reported",
  "exposure_period": "string or not_reported",
  "exposure_averaging_window": "string or not_reported",
  "exposure_assessment_method": "string or not_reported",
  "temporal_evidence_sentence": "string or not_reported",
  "temporal_source_section": "string or not_reported",
  "temporal_confidence": "high/medium/low",
  "temporal_status": "explicit/not_reported/ambiguous/multiple/review"
}
""".strip()

    user_prompt = f"""
ASSOCIATION_ID:
{item["association_id"]}

PMID:
{item["pmid"]}

TITLE:
{item["title"]}

TARGET ASSOCIATION:
Pollutant: {item["pollutant_specific"]}
Outcome: {item["outcome_normalized"]}
Measure: {item["measure_type"]}
Effect value: {item["effect_value"]}
Exposure increment: {item["exposure_increment"]}
Association claim: {item["association_claim"]}
Association evidence: {item["evidence_sentence"]}

ARTICLE CONTEXT:
{item["article_context"]}
""".strip()

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


# ============================================================
# Normalization
# ============================================================

EXPECTED_FIELDS = [
    "association_id", "pmid", "exposure_window_category", "exposure_window_text",
    "exposure_duration_value", "exposure_duration_unit", "exposure_lag",
    "exposure_period", "exposure_averaging_window", "exposure_assessment_method",
    "temporal_evidence_sentence", "temporal_source_section", "temporal_confidence",
    "temporal_status",
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


def normalize_temporal_payload(
    item: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:

    row = {field: payload.get(field) for field in EXPECTED_FIELDS}

    row["association_id"] = safe_str(item["association_id"])
    row["pmid"] = safe_str(item["pmid"])

    text_fields = [
        "exposure_window_category", "exposure_window_text", "exposure_duration_unit",
        "exposure_lag", "exposure_period", "exposure_averaging_window",
        "exposure_assessment_method", "temporal_evidence_sentence",
        "temporal_source_section", "temporal_confidence", "temporal_status",
    ]

    for field in text_fields:
        value = safe_str(row.get(field))
        row[field] = value if value else "not_reported"

    row["exposure_duration_value"] = normalize_number_or_none(
        row.get("exposure_duration_value")
    )

    return row


# ============================================================
# One PMID extraction (toutes les associations de ce PMID)
# ============================================================

def run_time_extractor_for_pmid(
    pmid: str,
    segmented_document_path: Path,
    associations: list[dict[str, Any]],
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

    title = safe_str(
        segmented_payload.get("title") or segmented_payload.get("article_title")
    )
    article_text = collect_article_text(segmented_payload)

    results: list[dict[str, Any]] = []
    reasoning_entries: list[dict[str, Any]] = []
    raw_response_parts: list[str] = []
    repair_used_any = False

    for assoc in associations:
        association_id = safe_str(assoc.get("association_id"))
        pollutant = safe_str(assoc.get("pollutant_specific"))
        outcome = safe_str(assoc.get("outcome_normalized"))
        evidence = safe_str(assoc.get("evidence_sentence"))

        article_context = build_temporal_context(
            article_text=article_text,
            pollutant=pollutant,
            outcome=outcome,
            association_evidence=evidence,
        )

        item = {
            "association_id": association_id,
            "pmid": pmid,
            "title": title,
            "pollutant_specific": pollutant,
            "outcome_normalized": outcome,
            "measure_type": safe_str(assoc.get("measure_type")),
            "effect_value": safe_str(assoc.get("effect_value")),
            "exposure_increment": safe_str(assoc.get("exposure_increment")),
            "association_claim": safe_str(assoc.get("association_claim")),
            "evidence_sentence": evidence,
            "article_context": article_context,
        }

        messages = build_exposure_temporal_prompt(item)

        chunk_payload, first_response, repair_response = client.chat_json(
            messages=messages,
            model=model,
            max_tokens=max_output_tokens,
            temperature=0.0,
            repair_on_fail=True,
        )

        raw_response_parts.append(
            f"--- association {association_id} ---\n{first_response.content}"
        )

        if repair_response is not None:
            repair_used_any = True

        normalized = normalize_temporal_payload(item=item, payload=chunk_payload)
        results.append(normalized)

        reasoning_text = safe_str(chunk_payload.get("reasoning"))

        if reasoning_text:
            reasoning_entries.append(
                {
                    "chunk_index": len(reasoning_entries) + 1,
                    "section_title": f"association_{association_id}",
                    "reasoning": reasoning_text,
                }
            )

    raw_response_path.parent.mkdir(parents=True, exist_ok=True)
    raw_response_path.write_text("\n\n".join(raw_response_parts), encoding="utf-8")

    repair_response_path.parent.mkdir(parents=True, exist_ok=True)
    repair_response_path.write_text("used" if repair_used_any else "", encoding="utf-8")

    reasoning_path = write_reasoning_file(
        reasoning_dir=reasoning_dir,
        pmid=pmid,
        agent_name="time_extractor",
        entries=reasoning_entries,
    )

    output_payload = {
        "pmid": pmid,
        "created_at": now_iso(),
        "provider": "ILAAS",
        "base_url": settings.ilaas_base_url,
        "model": model or settings.ilaas_model,
        "agent": "time_extractor",
        "exposure_temporal_found": results,
        "metadata": {
            "segmented_document_path": str(segmented_document_path),
            "raw_response_path": str(raw_response_path),
            "repair_response_path": str(repair_response_path),
            "reasoning_path": reasoning_path,
            "json_repair_used": repair_used_any,
            "n_associations_processed": len(results),
        },
    }

    state_payload = {
        "pmid": pmid,
        "time_extractor": output_payload,
        "exposure_temporal_found": results,
        "metadata": output_payload["metadata"],
    }

    write_json(output_json, output_payload)
    write_json(output_state_json, state_payload)

    return output_payload