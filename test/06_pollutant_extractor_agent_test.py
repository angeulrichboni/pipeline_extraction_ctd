#!/usr/bin/env python3
"""
Premier agent LangGraph : pollutant_extractor.

Version adaptée à l'API LLM du labo ILAAS:
    BASE_URL = https://llm.ilaas.fr/v1

Entrée:
    data/prototype/segmented_documents/{pmid}_segmented.json

Sorties:
    data/prototype/agent_outputs/pollutant_extractor/{pmid}_pollutants.json
    data/prototype/agent_outputs/pollutant_extractor/{pmid}_state.json
    data/prototype/agent_outputs/pollutant_extractor/{pmid}_raw_response.txt
    data/prototype/agent_outputs/pollutant_extractor/{pmid}_repair_response.txt

Objectif:
    Extraire tous les polluants explicitement mentionnés dans le texte,
    puis les classer automatiquement:
        - target du projet
        - contextual
        - secondary
        - source_marker
        - ambiguous

Important:
    - Aucun OR/RR/HR n'est extrait ici.
    - Aucune association scientifique finale n'est construite ici.
    - Cet agent ne fait que détecter et classer les polluants.
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

OUT_DIR = Path("data/prototype/agent_outputs/pollutant_extractor")
OUT_DIR.mkdir(parents=True, exist_ok=True)

MAX_RETRIES = 3
RETRY_SLEEP_SECONDS = 3


# ---------------------------------------------------------------------
# LangGraph state
# ---------------------------------------------------------------------

class PollutantExtractionState(TypedDict, total=False):
    pmid: str
    segmented_doc_path: str

    ctd_context: dict[str, Any]
    pubmed: dict[str, Any]

    focus_text: str
    focus_chunks: list[dict[str, Any]]
    focus_sections: list[dict[str, Any]]

    pollutants_found: list[dict[str, Any]]

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
    """
    Les modèles peuvent parfois renvoyer un bloc markdown ou du texte autour.
    On récupère le premier objet JSON valide.
    """
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


def normalize_pollutant_key(value: str) -> str:
    value = str(value or "").strip().lower()

    replacements = {
        "₂": "2",
        "₃": "3",
        "ₓ": "x",
        ".": "",
        "-": "",
        "_": "",
        " ": "",
        "<sub>2</sub>": "2",
        "<sub>3</sub>": "3",
        "<sub>x</sub>": "x",
        "<sub>X</sub>": "x",
    }

    for old, new in replacements.items():
        value = value.replace(old, new)

    return value


def compute_is_project_target(
    pollutant_general: str,
    pollutant_specific: str,
) -> bool:
    """
    Cibles principales du projet:
        PM / PM2.5 / PM10 / PM1 / UFP
        NO
        NO2
        O3 / ozone

    Important:
        CO, SO2, black carbon, soot, woodsmoke, NOx ne sont pas
        des cibles principales, mais peuvent être gardés comme contexte.
    """
    g = normalize_pollutant_key(pollutant_general)
    s = normalize_pollutant_key(pollutant_specific)

    target_terms = {
        "pm",
        "particulatematter",
        "pm25",
        "pm10",
        "pm1",
        "ultrafineparticles",
        "ufp",
        "no",
        "nitricoxide",
        "no2",
        "nitrogendioxide",
        "o3",
        "ozone",
    }

    return g in target_terms or s in target_terms


def infer_pollutant_role(
    pollutant_general: str,
    pollutant_specific: str,
    is_project_target: bool,
) -> str:
    g = normalize_pollutant_key(pollutant_general)
    s = normalize_pollutant_key(pollutant_specific)

    if is_project_target:
        return "target"

    source_markers = {
        "woodsmoke",
        "roadproximity",
        "roadwayproximity",
        "pointsource",
        "pointsources",
        "trafficrelatedpollutants",
    }

    secondary_pollutants = {
        "blackcarbon",
        "soot",
    }

    contextual_pollutants = {
        "co",
        "carbonmonoxide",
        "so2",
        "sulfurdioxide",
        "sulphurdioxide",
        "nox",
        "nitrogenoxides",
        "airpollutants",
    }

    if g in source_markers or s in source_markers:
        return "source_marker"

    if g in secondary_pollutants or s in secondary_pollutants:
        return "secondary"

    if g in contextual_pollutants or s in contextual_pollutants:
        return "contextual"

    return "ambiguous"


def compute_keep_for_final_analysis(
    is_project_target: bool,
    pollutant_role: str,
) -> bool:
    """
    Par défaut:
        - les cibles du projet sont gardées pour l'analyse finale;
        - les autres sont conservées dans le JSON mais non incluses
          dans la table finale principale sauf décision manuelle.
    """
    if is_project_target:
        return True

    return False


def trim_text(value: str, max_chars: int) -> str:
    value = str(value or "").strip()

    if len(value) <= max_chars:
        return value

    return value[:max_chars].rstrip() + "..."


def deduplicate_pollutants(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Déduplique par pollutant_general + pollutant_specific.
    Si doublon, garde l'item avec la meilleure confiance.
    """
    by_key: dict[tuple[str, str], dict[str, Any]] = {}

    for item in items:
        key = (
            normalize_pollutant_key(item.get("pollutant_general", "")),
            normalize_pollutant_key(item.get("pollutant_specific", "")),
        )

        if key not in by_key:
            by_key[key] = item
            continue

        if item.get("confidence", 0) > by_key[key].get("confidence", 0):
            by_key[key] = item

    return list(by_key.values())


def validate_pollutant_output(obj: dict[str, Any]) -> dict[str, Any]:
    """
    Validation et correction légère côté Python.

    On ne dépend pas de response_format=json_schema, car l'API ILAAS
    peut ne pas le supporter.

    Le modèle extrait large, mais le pipeline force:
        - is_project_target
        - pollutant_role
        - keep_for_final_analysis
    """
    if not isinstance(obj, dict):
        raise ValueError("Model output must be a JSON object.")

    if "pollutants_found" not in obj:
        raise ValueError("Missing key: pollutants_found")

    if "warnings" not in obj:
        obj["warnings"] = []

    if not isinstance(obj["pollutants_found"], list):
        raise ValueError("pollutants_found must be a list.")

    if not isinstance(obj["warnings"], list):
        raise ValueError("warnings must be a list.")

    required = {
        "pollutant_general",
        "pollutant_specific",
        "pollutant_original_mention",
        "normalization_note",
        "evidence_sentence",
        "source_section",
        "source_type",
        "confidence",
    }

    cleaned_items = []

    for idx, item in enumerate(obj["pollutants_found"], start=1):
        if not isinstance(item, dict):
            raise ValueError(f"pollutants_found[{idx}] must be an object.")

        missing = required - set(item.keys())

        if missing:
            raise ValueError(
                f"pollutants_found[{idx}] missing keys: {sorted(missing)}"
            )

        cleaned = {}

        for key in required:
            cleaned[key] = str(item.get(key, "")).strip()

        try:
            cleaned["confidence"] = float(item.get("confidence", 0.0))
        except Exception:
            cleaned["confidence"] = 0.0

        cleaned["confidence"] = max(0.0, min(1.0, cleaned["confidence"]))

        # Limiter les champs textuels pour éviter les JSON énormes.
        cleaned["pollutant_original_mention"] = trim_text(
            cleaned["pollutant_original_mention"],
            120,
        )
        cleaned["normalization_note"] = trim_text(
            cleaned["normalization_note"],
            180,
        )
        cleaned["evidence_sentence"] = trim_text(
            cleaned["evidence_sentence"],
            350,
        )
        cleaned["source_section"] = trim_text(
            cleaned["source_section"],
            120,
        )
        cleaned["source_type"] = trim_text(
            cleaned["source_type"],
            80,
        )

        is_project_target = compute_is_project_target(
            cleaned["pollutant_general"],
            cleaned["pollutant_specific"],
        )

        pollutant_role = infer_pollutant_role(
            cleaned["pollutant_general"],
            cleaned["pollutant_specific"],
            is_project_target=is_project_target,
        )

        keep_for_final_analysis = compute_keep_for_final_analysis(
            is_project_target=is_project_target,
            pollutant_role=pollutant_role,
        )

        cleaned["is_project_target"] = is_project_target
        cleaned["pollutant_role"] = pollutant_role
        cleaned["keep_for_final_analysis"] = keep_for_final_analysis

        reason_from_model = str(item.get("reason_for_role", "")).strip()

        if reason_from_model:
            cleaned["reason_for_role"] = trim_text(reason_from_model, 220)
        elif is_project_target:
            cleaned["reason_for_role"] = "Project target pollutant."
        else:
            cleaned["reason_for_role"] = (
                f"Non-target pollutant retained as {pollutant_role} context."
            )

        cleaned_items.append(cleaned)

    obj["pollutants_found"] = deduplicate_pollutants(cleaned_items)

    # Nettoyage warnings
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
You are a pollutant extraction agent specialized in environmental epidemiology.

Your task:
Extract all air-pollution-related pollutants explicitly mentioned in the provided text.

Important rules:
- Do not extract diseases, outcomes, genes, statistical measures, or associations.
- Do not infer pollutants that are not explicitly stated.
- CTD context is supportive context only; the final extracted pollutant must be supported by the document text.
- Extract broadly: do not discard useful contextual pollutants.
- Return one item per distinct normalized pollutant only.
- Do not repeat the same pollutant from multiple sections.
- Prefer evidence from abstract, results, exposure assessment, statistical analysis, or quantitative results.
- evidence_sentence must be short, maximum 300 characters.
- Do not copy long paragraphs.
- If many pollutants are mentioned, keep one concise item for each distinct pollutant.

Normalization:
- PM2.5, PM10, PM1, ultrafine particles and particulate matter belong to pollutant_general = "PM".
- NO is nitric oxide.
- NO2 is nitrogen dioxide.
- NOx is nitrogen oxides; keep pollutant_specific = "NOx" unless the text explicitly says NO or NO2.
- O3 and ozone should be normalized as pollutant_general = "O3", pollutant_specific = "O3".
- Carbon monoxide should be pollutant_general = "CO".
- Sulfur dioxide should be pollutant_general = "SO2".
- Black carbon should be pollutant_general = "black_carbon".
- Soot should be pollutant_general = "soot".
- Woodsmoke should be pollutant_general = "woodsmoke".
- General "air pollutants" or "traffic-related pollutants" can be kept as contextual if explicitly mentioned.

Project target pollutants:
- PM / PM2.5 / PM10 / PM1 / ultrafine particles
- NO / nitric oxide
- NO2 / nitrogen dioxide
- O3 / ozone

Non-target but useful contextual pollutants may include:
- CO / carbon monoxide
- SO2 / sulfur dioxide
- black carbon
- soot
- woodsmoke
- NOx
- air pollutants
- traffic-related pollutants

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
  "pollutants_found": [
    {
      "pollutant_general": "PM | NO | NO2 | NOx | O3 | CO | SO2 | black_carbon | soot | woodsmoke | air_pollutants | traffic_related_pollutants | other",
      "pollutant_specific": "PM2.5 | PM10 | PM1 | ultrafine particles | particulate matter | NO | NO2 | NOx | O3 | ozone | CO | SO2 | black carbon | soot | woodsmoke | air pollutants | traffic-related pollutants | ...",
      "pollutant_original_mention": "exact mention from the text",
      "normalization_note": "short note or empty string",
      "evidence_sentence": "short evidence, max 300 characters",
      "source_section": "PUBMED ABSTRACT | Results | Methods | Exposure measures | Logistic regression | ...",
      "source_type": "pubmed_abstract | paperclip_full_text | focus_chunk | unknown",
      "confidence": 0.0,
      "reason_for_role": "short explanation if useful"
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
The Python pipeline will compute is_project_target, pollutant_role and keep_for_final_analysis.
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
  "pollutants_found": [],
  "warnings": []
}
- Each pollutant item must contain:
  pollutant_general,
  pollutant_specific,
  pollutant_original_mention,
  normalization_note,
  evidence_sentence,
  source_section,
  source_type,
  confidence,
  reason_for_role
- evidence_sentence must be short, maximum 300 characters.
- If an item is incomplete or impossible to repair, drop that item.
""".strip()


def build_focus_input_for_agent(state: PollutantExtractionState) -> str:
    ctd = state.get("ctd_context", {})
    pubmed = state.get("pubmed", {})
    focus_text = state.get("focus_text", "")

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


def call_pollutant_extractor_raw(
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

def pollutant_extractor_node(
    state: PollutantExtractionState,
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

        raw_response = call_pollutant_extractor_raw(
            agent_input=agent_input,
            model=selected_model,
        )

        write_text(raw_response_path, raw_response)

        try:
            parsed = extract_json_object(raw_response)
            result = validate_pollutant_output(parsed)
            repair_used = False

        except Exception as parse_exc:
            repair_response = call_json_repair(
                raw_response=raw_response,
                model=selected_model,
            )

            write_text(repair_response_path, repair_response)

            parsed = extract_json_object(repair_response)
            result = validate_pollutant_output(parsed)

            repair_used = True

            result["warnings"] = result.get("warnings", []) + [
                {
                    "warning_type": "json_repair_used",
                    "message": (
                        "Initial model output was not valid JSON. "
                        f"Repair step was used. Initial parse error: {type(parse_exc).__name__}: {parse_exc}"
                    ),
                }
            ]

        return {
            "pollutants_found": result.get("pollutants_found", []),
            "warnings": state.get("warnings", []) + result.get("warnings", []),
            "metadata": {
                **state.get("metadata", {}),
                "llm_provider": "ilaas",
                "llm_base_url": ILAAS_BASE_URL,
                "pollutant_extractor_model": selected_model,
                "pollutant_extractor_ran_at": datetime.now().isoformat(timespec="seconds"),
                "pollutant_extractor_status": "success",
                "json_repair_used": repair_used,
                "raw_response_path": str(raw_response_path),
                "repair_response_path": str(repair_response_path) if repair_used else "",
            },
        }

    except Exception as exc:
        return {
            "errors": state.get("errors", []) + [
                {
                    "agent": "pollutant_extractor",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                }
            ],
            "metadata": {
                **state.get("metadata", {}),
                "llm_provider": "ilaas",
                "llm_base_url": ILAAS_BASE_URL,
                "pollutant_extractor_model": selected_model,
                "pollutant_extractor_ran_at": datetime.now().isoformat(timespec="seconds"),
                "pollutant_extractor_status": "failed",
                "raw_response_path": str(raw_response_path),
                "repair_response_path": str(repair_response_path),
            },
        }


# ---------------------------------------------------------------------
# LangGraph
# ---------------------------------------------------------------------

def build_graph():
    graph = StateGraph(PollutantExtractionState)

    graph.add_node("pollutant_extractor", pollutant_extractor_node)

    graph.add_edge(START, "pollutant_extractor")
    graph.add_edge("pollutant_extractor", END)

    return graph.compile()


# ---------------------------------------------------------------------
# Initial state
# ---------------------------------------------------------------------

def build_initial_state(
    pmid: str,
    selected_model: str,
) -> PollutantExtractionState:
    doc = load_segmented_document(pmid)

    return {
        "pmid": pmid,
        "segmented_doc_path": str(SEGMENTED_DIR / f"{pmid}_segmented.json"),

        "ctd_context": doc.get("ctd_context", {}),
        "pubmed": doc.get("pubmed", {}),

        "focus_text": doc.get("focus_text", ""),
        "focus_chunks": doc.get("focus_chunks", []),
        "focus_sections": doc.get("focus_sections", []),

        "pollutants_found": [],
        "warnings": [],
        "errors": [],

        "metadata": {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "agent_pipeline": "pollutant_extractor_test",
            "selected_model": selected_model,
            "input_focus_text_chars": len(doc.get("focus_text", "")),
            "input_focus_chunks": len(doc.get("focus_chunks", [])),
            "segmented_doc_path": str(SEGMENTED_DIR / f"{pmid}_segmented.json"),
            "extraction_scope": "broad_air_pollution_pollutants",
            "classification_policy": (
                "extract broadly, classify target/contextual/secondary/source_marker in Python"
            ),
        },
    }


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run pollutant_extractor agent on one segmented document using ILAAS."
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
    out_pollutants_path = OUT_DIR / f"{pmid}_pollutants.json"

    write_json(out_state_path, final_state)

    pollutant_payload = {
        "pmid": pmid,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "pollutants_found": final_state.get("pollutants_found", []),
        "warnings": final_state.get("warnings", []),
        "errors": final_state.get("errors", []),
        "metadata": final_state.get("metadata", {}),
    }

    write_json(out_pollutants_path, pollutant_payload)

    print("=" * 80)
    print("POLLUTANT EXTRACTOR COMPLETE")
    print("=" * 80)
    print(f"PMID: {pmid}")
    print(f"Provider: ILAAS")
    print(f"Base URL: {ILAAS_BASE_URL}")
    print(f"Model: {selected_model}")
    print(f"Pollutants found: {len(final_state.get('pollutants_found', []))}")
    print(f"Warnings: {len(final_state.get('warnings', []))}")
    print(f"Errors: {len(final_state.get('errors', []))}")
    print(f"JSON repair used: {final_state.get('metadata', {}).get('json_repair_used', False)}")
    print(f"State output: {out_state_path}")
    print(f"Pollutant output: {out_pollutants_path}")
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

    print("POLLUTANTS")
    print("-" * 80)

    for item in final_state.get("pollutants_found", []):
        print(
            f"- {item.get('pollutant_specific')} "
            f"({item.get('pollutant_general')}) | "
            f"project_target={item.get('is_project_target')} | "
            f"role={item.get('pollutant_role')} | "
            f"keep_final={item.get('keep_for_final_analysis')} | "
            f"confidence={item.get('confidence')}"
        )
        print(f"  mention: {item.get('pollutant_original_mention')}")
        print(f"  section: {item.get('source_section')}")
        print(f"  evidence: {item.get('evidence_sentence')}")
        print()

    if final_state.get("warnings"):
        print("WARNINGS")
        print("-" * 80)
        for warning in final_state["warnings"]:
            print(f"- {warning.get('warning_type')}: {warning.get('message')}")
        print("=" * 80)


if __name__ == "__main__":
    main()