#!/usr/bin/env python3
"""
Deuxième agent LangGraph : outcome_extractor.

Version adaptée à l'API LLM du labo ILAAS:
    BASE_URL = https://llm.ilaas.fr/v1

Entrée:
    data/prototype/segmented_documents/{pmid}_segmented.json

Optionnel:
    data/prototype/agent_outputs/pollutant_extractor/{pmid}_pollutants.json

Sorties:
    data/prototype/agent_outputs/outcome_extractor/{pmid}_outcomes.json
    data/prototype/agent_outputs/outcome_extractor/{pmid}_state.json
    data/prototype/agent_outputs/outcome_extractor/{pmid}_raw_response.txt
    data/prototype/agent_outputs/outcome_extractor/{pmid}_repair_response.txt

Objectif:
    Extraire les outcomes / endpoints de santé explicitement mentionnés,
    puis les classer automatiquement:
        - primary_outcome
        - endpoint_variant
        - case_definition_component
        - secondary_outcome
        - ambiguous

Important:
    - Aucun polluant n'est extrait ici.
    - Aucun OR/RR/HR n'est extrait ici.
    - Aucune association finale n'est construite ici.
    - Les gènes ne doivent pas être extraits comme outcomes.
"""

import argparse
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, TypedDict

import requests
from dotenv import load_dotenv
from langgraph.graph import END, START, StateGraph


# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------

load_dotenv()

ILAAS_API_KEY = os.getenv("ILAAS_API_KEY", "").strip()
ILAAS_BASE_URL = os.getenv("ILAAS_BASE_URL", "https://llm.ilaas.fr/v1").rstrip("/")
DEFAULT_ILAAS_MODEL = os.getenv("ILAAS_MODEL", "mistral-medium-latest").strip()
ILAAS_MAX_TOKENS = int(os.getenv("ILAAS_MAX_TOKENS", "6144"))

if not ILAAS_API_KEY:
    raise ValueError("Missing ILAAS_API_KEY in .env")

SEGMENTED_DIR = Path("data/prototype/segmented_documents")
POLLUTANT_OUT_DIR = Path("data/prototype/agent_outputs/pollutant_extractor")

OUT_DIR = Path("data/prototype/agent_outputs/outcome_extractor")
OUT_DIR.mkdir(parents=True, exist_ok=True)

MAX_RETRIES = 3
RETRY_SLEEP_SECONDS = 3


# ---------------------------------------------------------------------
# LangGraph state
# ---------------------------------------------------------------------

class OutcomeExtractionState(TypedDict, total=False):
    pmid: str
    segmented_doc_path: str

    ctd_context: dict[str, Any]
    pubmed: dict[str, Any]

    focus_text: str
    focus_chunks: list[dict[str, Any]]
    focus_sections: list[dict[str, Any]]

    pollutants_found: list[dict[str, Any]]
    outcomes_found: list[dict[str, Any]]

    warnings: list[dict[str, Any]]
    errors: list[dict[str, Any]]

    metadata: dict[str, Any]


# ---------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------

def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")

    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, obj: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(obj, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_text(path: Path, text: str) -> None:
    path.write_text(text or "", encoding="utf-8")


def load_segmented_document(pmid: str) -> dict[str, Any]:
    path = SEGMENTED_DIR / f"{pmid}_segmented.json"
    return read_json(path)


def load_pollutants_if_available(pmid: str) -> list[dict[str, Any]]:
    path = POLLUTANT_OUT_DIR / f"{pmid}_pollutants.json"

    if not path.exists():
        return []

    try:
        payload = read_json(path)
        return payload.get("pollutants_found", [])
    except Exception:
        return []


# ---------------------------------------------------------------------
# JSON parsing helpers
# ---------------------------------------------------------------------

def strip_markdown_code_fence(text: str) -> str:
    text = str(text or "").strip()

    if text.startswith("```json"):
        text = text[len("```json"):].strip()

    if text.startswith("```"):
        text = text[len("```"):].strip()

    if text.endswith("```"):
        text = text[:-3].strip()

    return text.strip()


def extract_json_object(text: str) -> dict[str, Any]:
    text = strip_markdown_code_fence(text)

    try:
        return json.loads(text)
    except Exception:
        pass

    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1 or end <= start:
        raise ValueError(
            f"No JSON object found in model output. Preview: {text[:800]}"
        )

    candidate = text[start:end + 1]

    try:
        return json.loads(candidate)
    except Exception as exc:
        raise ValueError(
            f"Could not parse JSON object. Error={exc}. "
            f"Output preview={text[:1200]}"
        )


def normalize_text_key(value: str) -> str:
    value = str(value or "").strip().lower()
    value = value.replace("-", " ")
    value = value.replace("_", " ")
    value = value.replace("’", "'")
    value = value.replace("“", '"').replace("”", '"')
    value = " ".join(value.split())
    return value


def trim_text(value: str, max_chars: int) -> str:
    value = str(value or "").strip()

    if len(value) <= max_chars:
        return value

    return value[:max_chars].rstrip() + "..."


def clean_markdown_emphasis(text: str) -> str:
    return str(text or "").replace("**", "").replace("__", "").strip()


def parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value

    return str(value).strip().lower() in {"true", "1", "yes", "y"}


# ---------------------------------------------------------------------
# Outcome classification
# ---------------------------------------------------------------------

def infer_is_human_study(item: dict[str, Any]) -> bool:
    text = " ".join(
        [
            str(item.get("population_group", "")),
            str(item.get("population_details", "")),
            str(item.get("evidence_sentence", "")),
            str(item.get("study_design", "")),
        ]
    ).lower()

    human_terms = [
        "children",
        "child",
        "adults",
        "adult",
        "patients",
        "subjects",
        "participants",
        "cohort",
        "case",
        "control",
        "births",
        "mothers",
        "population",
        "uk biobank",
        "european ancestry",
        "human",
        "study subjects",
    ]

    non_human_terms = [
        "mouse",
        "mice",
        "rat",
        "rats",
        "murine",
        "cell line",
        "in vitro",
        "zebrafish",
        "animal model",
    ]

    if any(term in text for term in non_human_terms):
        return False

    if any(term in text for term in human_terms):
        return True

    return parse_bool(item.get("is_human_study", False))


def infer_outcome_core(
    outcome_normalized: str,
    outcome_original: str,
) -> str:
    """
    Normalise le noyau scientifique de l'outcome.

    Exemples:
        asthma diagnosis -> asthma
        hospital admission for asthma -> asthma
        ALS incidence -> amyotrophic lateral sclerosis
    """
    text = normalize_text_key(f"{outcome_normalized} {outcome_original}")

    if "asthma" in text:
        return "asthma"

    if (
        "amyotrophic lateral sclerosis" in text
        or text.strip() == "als"
        or " als " in f" {text} "
        or "incidence of als" in text
        or "risk of als" in text
    ):
        return "amyotrophic lateral sclerosis"

    if "alzheimer" in text:
        return "Alzheimer disease"

    if "acute kidney injury" in text:
        return "acute kidney injury"

    if "adenocarcinoma of lung" in text or "lung adenocarcinoma" in text:
        return "lung adenocarcinoma"

    if "adenocarcinoma" in text:
        return "adenocarcinoma"

    if "angina" in text:
        return "angina pectoris"

    if "spontaneous abortion" in text or "abortion" in text:
        return "spontaneous abortion"

    if "mortality" in text:
        return "mortality"

    return outcome_normalized.strip()


def infer_outcome_category(
    outcome_core: str,
    outcome_normalized: str,
    outcome_original: str,
) -> str:
    text = normalize_text_key(f"{outcome_core} {outcome_normalized} {outcome_original}")

    if "asthma" in text or "respiratory" in text or "copd" in text:
        return "respiratory_disease"

    if "amyotrophic lateral sclerosis" in text or " als " in f" {text} ":
        return "neurodegenerative_disease"

    if "alzheimer" in text or "dementia" in text:
        return "neurodegenerative_disease"

    if "mortality" in text or "death" in text:
        return "mortality"

    if "cancer" in text or "carcinoma" in text or "adenocarcinoma" in text:
        return "cancer"

    if "angina" in text or "cardiovascular" in text or "myocardial" in text:
        return "cardiovascular_disease"

    if "kidney" in text or "renal" in text:
        return "renal_disease"

    if "abortion" in text or "birth" in text or "pregnancy" in text:
        return "reproductive_or_perinatal_outcome"

    return "health_outcome"


def infer_outcome_role(
    outcome_core: str,
    outcome_normalized: str,
    outcome_original: str,
    outcome_type: str,
    evidence_sentence: str,
) -> str:
    """
    Classe le rôle initial de l'outcome.
    L'harmonisation finale se fait ensuite dans harmonize_outcome_roles().
    """
    text = normalize_text_key(
        f"{outcome_core} {outcome_normalized} {outcome_original} "
        f"{outcome_type} {evidence_sentence}"
    )

    case_definition_signals = [
        "case definition",
        "cases were defined",
        "case were defined",
        "defined as",
        "minimum of one hospital admission",
        "minimum of two primary care",
        "physician diagnoses",
        "hospital admission for asthma",
        "hospitalization for asthma",
        "icd",
    ]

    if any(signal in text for signal in case_definition_signals):
        if "asthma" in text and (
            "hospital admission" in text
            or "physician diagnoses" in text
            or "defined as" in text
        ):
            return "case_definition_component"

    if "amyotrophic lateral sclerosis" in text or " als " in f" {text} ":
        if "incidence" in text:
            return "endpoint_variant"
        if "risk of" in text:
            return "primary_outcome"
        return "primary_outcome"

    if "asthma" in text:
        if "asthma diagnosis" in text or "risk of subsequent asthma" in text:
            return "primary_outcome"
        if "hospital admission" in text or "hospitalization" in text:
            return "case_definition_component"

    primary_signals = [
        "main outcome",
        "primary outcome",
        "risk of subsequent",
        "risk of",
        "development of",
        "incidence of",
        "classified as",
        "outcome",
    ]

    if any(signal in text for signal in primary_signals):
        return "primary_outcome"

    if outcome_core:
        return "primary_outcome"

    return "ambiguous"


def compute_keep_for_final_analysis(outcome_role: str) -> bool:
    if outcome_role in {"primary_outcome", "endpoint_variant", "secondary_outcome"}:
        return True

    return False


def infer_reason_for_role(
    outcome_role: str,
    outcome_core: str,
) -> str:
    if outcome_role == "primary_outcome":
        return f"Retained as primary health outcome: {outcome_core}."

    if outcome_role == "endpoint_variant":
        return (
            f"Retained as endpoint variant linked to core outcome: {outcome_core}."
        )

    if outcome_role == "case_definition_component":
        return (
            "Extracted as case definition component; not treated as an independent "
            "final association unless quantitative results are reported separately."
        )

    if outcome_role == "secondary_outcome":
        return f"Retained as secondary health outcome: {outcome_core}."

    return "Outcome role is ambiguous and should be reviewed manually."


def deduplicate_outcomes(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Déduplique par:
        outcome_core + outcome_role + population_group

    On ne fusionne pas primary_outcome et case_definition_component,
    car ils n'ont pas le même rôle analytique.
    """
    by_key: dict[tuple[str, str, str], dict[str, Any]] = {}

    for item in items:
        key = (
            normalize_text_key(item.get("outcome_core", "")),
            normalize_text_key(item.get("outcome_role", "")),
            normalize_text_key(item.get("population_group", "")),
        )

        if key not in by_key:
            by_key[key] = item
            continue

        if item.get("confidence", 0) > by_key[key].get("confidence", 0):
            by_key[key] = item

    return list(by_key.values())


def harmonize_outcome_roles(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Harmonise les rôles des outcomes après extraction.

    Objectif:
        - un même outcome_core ne doit pas produire des rôles instables;
        - les composants de définition de cas restent case_definition_component;
        - les formulations risk/development/disease deviennent primary_outcome;
        - les formulations incidence/diagnosis/hospitalization deviennent endpoint_variant,
          sauf si elles sont le seul outcome disponible pour ce core.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}

    for item in items:
        core = normalize_text_key(item.get("outcome_core", ""))
        grouped.setdefault(core, []).append(item)

    harmonized = []

    for core, group in grouped.items():
        if not core:
            harmonized.extend(group)
            continue

        case_components = [
            item for item in group
            if item.get("outcome_role") == "case_definition_component"
        ]

        non_case = [
            item for item in group
            if item.get("outcome_role") != "case_definition_component"
        ]

        if not non_case:
            for item in case_components:
                item["outcome_role"] = "case_definition_component"
                item["keep_for_final_analysis"] = False
                item["reason_for_role"] = infer_reason_for_role(
                    "case_definition_component",
                    item.get("outcome_core", ""),
                )
            harmonized.extend(case_components)
            continue

        def primary_score(item: dict[str, Any]) -> tuple[int, float]:
            text = normalize_text_key(
                f"{item.get('outcome_normalized', '')} "
                f"{item.get('outcome_original_mention', '')} "
                f"{item.get('evidence_sentence', '')}"
            )

            score = 0

            if "risk of" in text:
                score += 6

            if "development of" in text:
                score += 5

            if core in text:
                score += 3

            if "amyotrophic lateral sclerosis" in text:
                score += 2

            if "asthma diagnosis" in text:
                score += 4

            if "incidence" in text:
                score -= 1

            if "hospital admission" in text or "hospitalization" in text:
                score -= 4

            if "physician diagnoses" in text or "defined as" in text:
                score -= 4

            return score, float(item.get("confidence", 0.0))

        primary_item = max(non_case, key=primary_score)

        # Si un seul item non-case existe, il devient primary_outcome.
        if len(non_case) == 1:
            primary_item = non_case[0]

        for item in non_case:
            text = normalize_text_key(
                f"{item.get('outcome_normalized', '')} "
                f"{item.get('outcome_original_mention', '')} "
                f"{item.get('evidence_sentence', '')}"
            )

            if item is primary_item:
                item["outcome_role"] = "primary_outcome"
                item["keep_for_final_analysis"] = True
                item["reason_for_role"] = (
                    f"Selected as canonical primary outcome for core outcome: "
                    f"{item.get('outcome_core', '')}."
                )
            else:
                item["outcome_role"] = "endpoint_variant"
                item["keep_for_final_analysis"] = True

                if "incidence" in text:
                    item["reason_for_role"] = (
                        f"Incidence endpoint variant linked to core outcome: "
                        f"{item.get('outcome_core', '')}."
                    )
                elif "diagnosis" in text:
                    item["reason_for_role"] = (
                        f"Diagnosis endpoint variant linked to core outcome: "
                        f"{item.get('outcome_core', '')}."
                    )
                elif "risk of" in text:
                    item["reason_for_role"] = (
                        f"Risk endpoint variant linked to core outcome: "
                        f"{item.get('outcome_core', '')}."
                    )
                else:
                    item["reason_for_role"] = (
                        f"Variant formulation linked to core outcome: "
                        f"{item.get('outcome_core', '')}."
                    )

        for item in case_components:
            item["outcome_role"] = "case_definition_component"
            item["keep_for_final_analysis"] = False
            item["reason_for_role"] = (
                "Extracted as a case definition component; not treated as an "
                "independent final association unless quantitative results are "
                "reported separately."
            )

        harmonized.extend(non_case)
        harmonized.extend(case_components)

    return harmonized


def validate_outcome_output(obj: dict[str, Any]) -> dict[str, Any]:
    """
    Validation et normalisation côté Python.

    Le modèle extrait large.
    Python force ensuite:
        - outcome_core
        - outcome_role
        - keep_for_final_analysis
        - reason_for_role
    """
    if not isinstance(obj, dict):
        raise ValueError("Model output must be a JSON object.")

    if "outcomes_found" not in obj:
        raise ValueError("Missing key: outcomes_found")

    if "warnings" not in obj:
        obj["warnings"] = []

    if not isinstance(obj["outcomes_found"], list):
        raise ValueError("outcomes_found must be a list.")

    if not isinstance(obj["warnings"], list):
        raise ValueError("warnings must be a list.")

    required = {
        "outcome_original_mention",
        "outcome_normalized",
        "outcome_type",
        "outcome_category",
        "population_group",
        "population_details",
        "is_human_study",
        "study_design",
        "evidence_sentence",
        "source_section",
        "source_type",
        "confidence",
        "reason_for_inclusion",
    }

    cleaned_items = []

    for idx, item in enumerate(obj["outcomes_found"], start=1):
        if not isinstance(item, dict):
            raise ValueError(f"outcomes_found[{idx}] must be an object.")

        missing = required - set(item.keys())

        if missing:
            raise ValueError(
                f"outcomes_found[{idx}] missing keys: {sorted(missing)}"
            )

        cleaned = {}

        for key in required:
            cleaned[key] = str(item.get(key, "")).strip()

        try:
            cleaned["confidence"] = float(item.get("confidence", 0.0))
        except Exception:
            cleaned["confidence"] = 0.0

        cleaned["confidence"] = max(0.0, min(1.0, cleaned["confidence"]))

        cleaned["outcome_original_mention"] = trim_text(
            cleaned["outcome_original_mention"],
            160,
        )
        cleaned["outcome_normalized"] = trim_text(
            cleaned["outcome_normalized"],
            160,
        )
        cleaned["outcome_type"] = trim_text(
            cleaned["outcome_type"],
            100,
        )
        cleaned["outcome_category"] = trim_text(
            cleaned["outcome_category"],
            120,
        )
        cleaned["population_group"] = trim_text(
            cleaned["population_group"],
            160,
        )
        cleaned["population_details"] = trim_text(
            cleaned["population_details"],
            300,
        )
        cleaned["study_design"] = trim_text(
            cleaned["study_design"],
            180,
        )
        cleaned["evidence_sentence"] = trim_text(
            cleaned["evidence_sentence"],
            350,
        )
        cleaned["evidence_sentence"] = clean_markdown_emphasis(
            cleaned["evidence_sentence"]
        )
        cleaned["source_section"] = trim_text(
            cleaned["source_section"],
            120,
        )
        cleaned["source_type"] = trim_text(
            cleaned["source_type"],
            80,
        )
        cleaned["reason_for_inclusion"] = trim_text(
            cleaned["reason_for_inclusion"],
            250,
        )

        cleaned["is_human_study"] = infer_is_human_study(cleaned)

        outcome_core = infer_outcome_core(
            cleaned["outcome_normalized"],
            cleaned["outcome_original_mention"],
        )

        outcome_category = infer_outcome_category(
            outcome_core,
            cleaned["outcome_normalized"],
            cleaned["outcome_original_mention"],
        )

        outcome_role = infer_outcome_role(
            outcome_core=outcome_core,
            outcome_normalized=cleaned["outcome_normalized"],
            outcome_original=cleaned["outcome_original_mention"],
            outcome_type=cleaned["outcome_type"],
            evidence_sentence=cleaned["evidence_sentence"],
        )

        keep_for_final_analysis = compute_keep_for_final_analysis(outcome_role)

        cleaned["outcome_core"] = outcome_core
        cleaned["outcome_category"] = outcome_category
        cleaned["outcome_role"] = outcome_role
        cleaned["keep_for_final_analysis"] = keep_for_final_analysis
        cleaned["reason_for_role"] = infer_reason_for_role(
            outcome_role=outcome_role,
            outcome_core=outcome_core,
        )

        cleaned_items.append(cleaned)

    deduped = deduplicate_outcomes(cleaned_items)
    obj["outcomes_found"] = harmonize_outcome_roles(deduped)

    cleaned_warnings = []

    for warning in obj.get("warnings", []):
        if not isinstance(warning, dict):
            continue

        cleaned_warnings.append(
            {
                "warning_type": trim_text(warning.get("warning_type", ""), 120),
                "message": trim_text(warning.get("message", ""), 350),
            }
        )

    obj["warnings"] = cleaned_warnings

    return obj


# ---------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------

SYSTEM_PROMPT = """
You are an outcome extraction agent specialized in environmental epidemiology.

Your task:
Extract health outcomes, diseases, clinical endpoints, or epidemiological endpoints explicitly mentioned in the provided scientific text.

Important rules:
- Extract outcomes only.
- Do not extract pollutants.
- Do not extract OR, RR, HR, beta coefficients, p-values, confidence intervals, or exposure units.
- Do not extract genes as outcomes. Genes may be mentioned mechanistically, but they are not health outcomes.
- Do not infer outcomes that are not explicitly stated.
- CTD context is supportive context only; the final extracted outcome must be supported by the document text.
- Extract broadly, but keep the evidence concise.
- Return one item per distinct normalized outcome or endpoint formulation.
- Prefer evidence from abstract, results, outcome assessment, methods, or clinical endpoint definitions.
- evidence_sentence must be short, maximum 300 characters.
- Do not copy long paragraphs.

Examples of valid outcomes:
- asthma
- asthma diagnosis
- amyotrophic lateral sclerosis
- incidence of ALS
- lung adenocarcinoma
- acute kidney injury
- Alzheimer disease
- mortality
- hospital admission for asthma
- spontaneous abortion

Examples of invalid outputs:
- PM2.5
- NO2
- odds ratio
- confidence interval
- TMEM175
- USP35
- exposure level
- statistical model

Output rules:
- Return only valid JSON.
- No markdown.
- No commentary.
- No trailing text after JSON.
- Reason internally, but do not output your reasoning.
""".strip()


OUTPUT_CONTRACT = """
Return exactly this JSON structure:

{
  "outcomes_found": [
    {
      "outcome_original_mention": "exact outcome mention from the text",
      "outcome_normalized": "normalized disease or health endpoint",
      "outcome_type": "disease | clinical_endpoint | mortality | hospitalization | diagnosis | symptom | biomarker_endpoint | other",
      "outcome_category": "respiratory_disease | neurodegenerative_disease | cardiovascular_disease | cancer | renal_disease | reproductive_or_perinatal_outcome | mortality | health_outcome | other",
      "population_group": "children | adults | pregnant women | study subjects | patients | general population | unknown",
      "population_details": "short population details explicitly supported by text",
      "is_human_study": true,
      "study_design": "cohort | nested case-control | case-control | time-series | Mendelian randomization | GWAS/TWAS | cross-sectional | unknown",
      "evidence_sentence": "short evidence, max 300 characters",
      "source_section": "PUBMED ABSTRACT | Results | Outcome measure | Methods | ...",
      "source_type": "pubmed_abstract | paperclip_full_text | focus_chunk | unknown",
      "confidence": 0.0,
      "reason_for_inclusion": "short explanation"
    }
  ],
  "warnings": [
    {
      "warning_type": "string",
      "message": "string"
    }
  ]
}

Do not include fields outside this JSON structure.
The Python pipeline will compute:
- outcome_core
- outcome_role
- keep_for_final_analysis
- reason_for_role
""".strip()


REPAIR_SYSTEM_PROMPT = """
You are a JSON repair assistant.

Your task:
Repair the provided malformed JSON-like model output into valid JSON.

Rules:
- Return only valid JSON.
- No markdown.
- No commentary.
- Keep the same intended content.
- Use this exact top-level structure:
{
  "outcomes_found": [],
  "warnings": []
}
- Each outcome item must contain:
  outcome_original_mention,
  outcome_normalized,
  outcome_type,
  outcome_category,
  population_group,
  population_details,
  is_human_study,
  study_design,
  evidence_sentence,
  source_section,
  source_type,
  confidence,
  reason_for_inclusion
- evidence_sentence must be short, maximum 300 characters.
- If an item is incomplete or impossible to repair, drop that item.
""".strip()


def summarize_pollutants_for_context(
    pollutants_found: list[dict[str, Any]],
) -> str:
    if not pollutants_found:
        return "No previous pollutant extraction available."

    parts = []

    for item in pollutants_found:
        parts.append(
            f"- {item.get('pollutant_specific', '')} "
            f"({item.get('pollutant_general', '')}), "
            f"role={item.get('pollutant_role', '')}, "
            f"target={item.get('is_project_target', '')}"
        )

    return "\n".join(parts)


def build_focus_input_for_agent(state: OutcomeExtractionState) -> str:
    ctd = state.get("ctd_context", {})
    pubmed = state.get("pubmed", {})
    focus_text = state.get("focus_text", "")
    pollutants_found = state.get("pollutants_found", [])

    pollutants_summary = summarize_pollutants_for_context(pollutants_found)

    return f"""
PMID: {state.get("pmid", "")}

CTD CONTEXT:
- source_pollutant: {ctd.get("source_pollutant", "")}
- stressor_agent: {ctd.get("stressor_agent", "")}
- outcome_ctd: {ctd.get("outcome_ctd", "")}
- receptors: {ctd.get("receptors", "")}
- country: {ctd.get("country", "")}

PUBMED:
- title: {pubmed.get("title", "")}
- year: {pubmed.get("year", "")}
- journal: {pubmed.get("journal", "")}

PREVIOUS POLLUTANT EXTRACTION CONTEXT:
{pollutants_summary}

{OUTPUT_CONTRACT}

DOCUMENT FOCUS TEXT:
{focus_text}
""".strip()


# ---------------------------------------------------------------------
# ILAAS client
# ---------------------------------------------------------------------

def call_ilaas_chat_completion(
    messages: list[dict[str, str]],
    model: str,
    max_tokens: int = ILAAS_MAX_TOKENS,
    temperature: float = 0.0,
) -> str:
    url = f"{ILAAS_BASE_URL}/chat/completions"

    headers = {
        "Authorization": f"Bearer {ILAAS_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=180,
            )

            if response.status_code >= 400:
                raise RuntimeError(
                    f"HTTP {response.status_code}: {response.text[:1500]}"
                )

            data = response.json()

            return data["choices"][0]["message"]["content"]

        except Exception as exc:
            last_error = exc

            if attempt < MAX_RETRIES:
                time.sleep(RETRY_SLEEP_SECONDS * attempt)

    raise RuntimeError(f"ILAAS chat completion failed after retries: {last_error}")


def call_outcome_extractor_raw(
    agent_input: str,
    model: str,
) -> str:
    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT,
        },
        {
            "role": "user",
            "content": agent_input,
        },
    ]

    return call_ilaas_chat_completion(
        messages=messages,
        model=model,
        max_tokens=ILAAS_MAX_TOKENS,
        temperature=0.0,
    )


def call_json_repair(
    raw_response: str,
    model: str,
) -> str:
    messages = [
        {
            "role": "system",
            "content": REPAIR_SYSTEM_PROMPT,
        },
        {
            "role": "user",
            "content": (
                "Repair this malformed JSON-like output:\n\n"
                f"{raw_response}"
            ),
        },
    ]

    return call_ilaas_chat_completion(
        messages=messages,
        model=model,
        max_tokens=ILAAS_MAX_TOKENS,
        temperature=0.0,
    )


# ---------------------------------------------------------------------
# LangGraph node
# ---------------------------------------------------------------------

def outcome_extractor_node(
    state: OutcomeExtractionState,
) -> dict[str, Any]:
    selected_model = (
        state.get("metadata", {}).get("selected_model")
        or DEFAULT_ILAAS_MODEL
    )

    pmid = state.get("pmid", "unknown")

    raw_response_path = OUT_DIR / f"{pmid}_raw_response.txt"
    repair_response_path = OUT_DIR / f"{pmid}_repair_response.txt"

    try:
        agent_input = build_focus_input_for_agent(state)

        raw_response = call_outcome_extractor_raw(
            agent_input=agent_input,
            model=selected_model,
        )

        write_text(raw_response_path, raw_response)

        try:
            parsed = extract_json_object(raw_response)
            result = validate_outcome_output(parsed)
            repair_used = False

        except Exception as parse_exc:
            repair_response = call_json_repair(
                raw_response=raw_response,
                model=selected_model,
            )

            write_text(repair_response_path, repair_response)

            parsed = extract_json_object(repair_response)
            result = validate_outcome_output(parsed)

            repair_used = True

            result["warnings"] = result.get("warnings", []) + [
                {
                    "warning_type": "json_repair_used",
                    "message": (
                        "Initial model output was not valid JSON. "
                        f"Repair step was used. Initial parse error: "
                        f"{type(parse_exc).__name__}: {parse_exc}"
                    ),
                }
            ]

        return {
            "outcomes_found": result.get("outcomes_found", []),
            "warnings": state.get("warnings", []) + result.get("warnings", []),
            "metadata": {
                **state.get("metadata", {}),
                "llm_provider": "ilaas",
                "llm_base_url": ILAAS_BASE_URL,
                "outcome_extractor_model": selected_model,
                "outcome_extractor_ran_at": datetime.now().isoformat(timespec="seconds"),
                "outcome_extractor_status": "success",
                "json_repair_used": repair_used,
                "raw_response_path": str(raw_response_path),
                "repair_response_path": str(repair_response_path) if repair_used else "",
            },
        }

    except Exception as exc:
        return {
            "errors": state.get("errors", []) + [
                {
                    "agent": "outcome_extractor",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                }
            ],
            "metadata": {
                **state.get("metadata", {}),
                "llm_provider": "ilaas",
                "llm_base_url": ILAAS_BASE_URL,
                "outcome_extractor_model": selected_model,
                "outcome_extractor_ran_at": datetime.now().isoformat(timespec="seconds"),
                "outcome_extractor_status": "failed",
                "raw_response_path": str(raw_response_path),
                "repair_response_path": str(repair_response_path),
            },
        }


# ---------------------------------------------------------------------
# LangGraph
# ---------------------------------------------------------------------

def build_graph():
    graph = StateGraph(OutcomeExtractionState)

    graph.add_node("outcome_extractor", outcome_extractor_node)

    graph.add_edge(START, "outcome_extractor")
    graph.add_edge("outcome_extractor", END)

    return graph.compile()


# ---------------------------------------------------------------------
# Initial state
# ---------------------------------------------------------------------

def build_initial_state(
    pmid: str,
    selected_model: str,
) -> OutcomeExtractionState:
    doc = load_segmented_document(pmid)
    pollutants_found = load_pollutants_if_available(pmid)

    return {
        "pmid": pmid,
        "segmented_doc_path": str(SEGMENTED_DIR / f"{pmid}_segmented.json"),

        "ctd_context": doc.get("ctd_context", {}),
        "pubmed": doc.get("pubmed", {}),

        "focus_text": doc.get("focus_text", ""),
        "focus_chunks": doc.get("focus_chunks", []),
        "focus_sections": doc.get("focus_sections", []),

        "pollutants_found": pollutants_found,
        "outcomes_found": [],

        "warnings": [],
        "errors": [],

        "metadata": {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "agent_pipeline": "outcome_extractor_test",
            "selected_model": selected_model,
            "input_focus_text_chars": len(doc.get("focus_text", "")),
            "input_focus_chunks": len(doc.get("focus_chunks", [])),
            "segmented_doc_path": str(SEGMENTED_DIR / f"{pmid}_segmented.json"),
            "previous_pollutants_loaded": len(pollutants_found),
            "extraction_scope": "human_health_outcomes",
            "classification_policy": (
                "extract broadly, classify primary/variant/case_definition in Python"
            ),
        },
    }


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run outcome_extractor agent on one segmented document using ILAAS."
    )

    parser.add_argument(
        "--pmid",
        default="20123607",
        help="PMID to process. Default: 20123607.",
    )

    parser.add_argument(
        "--model",
        default=DEFAULT_ILAAS_MODEL,
        help=f"ILAAS model name. Default from .env: {DEFAULT_ILAAS_MODEL}",
    )

    args = parser.parse_args()

    pmid = args.pmid
    selected_model = args.model

    initial_state = build_initial_state(
        pmid=pmid,
        selected_model=selected_model,
    )

    app = build_graph()
    final_state = app.invoke(initial_state)

    out_state_path = OUT_DIR / f"{pmid}_state.json"
    out_outcomes_path = OUT_DIR / f"{pmid}_outcomes.json"

    write_json(out_state_path, final_state)

    outcome_payload = {
        "pmid": pmid,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "outcomes_found": final_state.get("outcomes_found", []),
        "warnings": final_state.get("warnings", []),
        "errors": final_state.get("errors", []),
        "metadata": final_state.get("metadata", {}),
    }

    write_json(out_outcomes_path, outcome_payload)

    print("=" * 80)
    print("OUTCOME EXTRACTOR COMPLETE")
    print("=" * 80)
    print(f"PMID: {pmid}")
    print(f"Provider: ILAAS")
    print(f"Base URL: {ILAAS_BASE_URL}")
    print(f"Model: {selected_model}")
    print(f"Outcomes found: {len(final_state.get('outcomes_found', []))}")
    print(f"Warnings: {len(final_state.get('warnings', []))}")
    print(f"Errors: {len(final_state.get('errors', []))}")
    print(f"JSON repair used: {final_state.get('metadata', {}).get('json_repair_used', False)}")
    print(f"Previous pollutants loaded: {final_state.get('metadata', {}).get('previous_pollutants_loaded', 0)}")
    print(f"State output: {out_state_path}")
    print(f"Outcome output: {out_outcomes_path}")
    print(f"Raw response: {final_state.get('metadata', {}).get('raw_response_path', '')}")
    print(f"Repair response: {final_state.get('metadata', {}).get('repair_response_path', '')}")
    print("=" * 80)

    if final_state.get("errors"):
        print("ERRORS")
        print("-" * 80)
        for err in final_state["errors"]:
            print(f"- {err.get('error_type')}: {err.get('message')}")
        print("=" * 80)
        return

    print("OUTCOMES")
    print("-" * 80)

    for item in final_state.get("outcomes_found", []):
        print(
            f"- {item.get('outcome_normalized')} "
            f"| core={item.get('outcome_core')} "
            f"| role={item.get('outcome_role')} "
            f"| keep_final={item.get('keep_for_final_analysis')} "
            f"| type={item.get('outcome_type')} "
            f"| category={item.get('outcome_category')} "
            f"| human={item.get('is_human_study')} "
            f"| confidence={item.get('confidence')}"
        )
        print(f"  mention: {item.get('outcome_original_mention')}")
        print(f"  population: {item.get('population_group')}")
        print(f"  study_design: {item.get('study_design')}")
        print(f"  section: {item.get('source_section')}")
        print(f"  evidence: {item.get('evidence_sentence')}")
        print(f"  role_reason: {item.get('reason_for_role')}")
        print()

    if final_state.get("warnings"):
        print("WARNINGS")
        print("-" * 80)
        for warning in final_state["warnings"]:
            print(f"- {warning.get('warning_type')}: {warning.get('message')}")
        print("=" * 80)


if __name__ == "__main__":
    main()