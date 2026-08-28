#!/usr/bin/env python3
"""
Troisième agent LangGraph : effect_measure_extractor.

Version v2 adaptée à l'API LLM du labo ILAAS:
    BASE_URL = https://llm.ilaas.fr/v1

Entrée:
    data/prototype/segmented_documents/{pmid}_segmented.json

Optionnel:
    data/prototype/agent_outputs/pollutant_extractor/{pmid}_pollutants.json
    data/prototype/agent_outputs/outcome_extractor/{pmid}_outcomes.json

Sorties:
    data/prototype/agent_outputs/effect_measure_extractor/{pmid}_effect_measures.json
    data/prototype/agent_outputs/effect_measure_extractor/{pmid}_state.json
    data/prototype/agent_outputs/effect_measure_extractor/{pmid}_raw_response.txt
    data/prototype/agent_outputs/effect_measure_extractor/{pmid}_repair_response.txt

Objectif:
    Extraire les mesures statistiques explicitement rapportées:
        - OR, RR, HR, IRR, beta, coefficient, percent change, etc.
        - valeur de l'effet
        - intervalle de confiance
        - p-value
        - incrément/unité d'exposition si visible
        - direction d'effet
        - significativité

Décision v2:
    Le modèle extrait large.
    Python classe ensuite chaque mesure:
        - direct_effect_estimate
        - incomplete_effect_description
        - heterogeneity_test
        - pleiotropy_test
        - gene_association
        - model_diagnostic
        - other

    Seules les mesures direct_effect_estimate suffisamment complètes
    vont vers association_builder.

Important:
    - Cet agent ne construit pas encore l'association finale.
    - Il ne doit pas inventer le polluant ou l'outcome.
    - Les résultats non significatifs sont conservés SI un effet numérique est disponible.
"""

import argparse
import json
import os
import re
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
OUTCOME_OUT_DIR = Path("data/prototype/agent_outputs/outcome_extractor")

OUT_DIR = Path("data/prototype/agent_outputs/effect_measure_extractor")
OUT_DIR.mkdir(parents=True, exist_ok=True)

MAX_RETRIES = 3
RETRY_SLEEP_SECONDS = 3


# ---------------------------------------------------------------------
# LangGraph state
# ---------------------------------------------------------------------

class EffectMeasureExtractionState(TypedDict, total=False):
    pmid: str
    segmented_doc_path: str

    ctd_context: dict[str, Any]
    pubmed: dict[str, Any]

    focus_text: str
    focus_chunks: list[dict[str, Any]]
    focus_sections: list[dict[str, Any]]

    pollutants_found: list[dict[str, Any]]
    outcomes_found: list[dict[str, Any]]
    effect_measures_found: list[dict[str, Any]]

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


def load_outcomes_if_available(pmid: str) -> list[dict[str, Any]]:
    path = OUTCOME_OUT_DIR / f"{pmid}_outcomes.json"

    if not path.exists():
        return []

    try:
        payload = read_json(path)
        return payload.get("outcomes_found", [])
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
    value = value.replace("₂", "2").replace("₃", "3").replace("ₓ", "x")
    value = value.replace("<sub>2</sub>", "2")
    value = value.replace("<sub>3</sub>", "3")
    value = value.replace("<sub>x</sub>", "x")
    value = value.replace("<sub>X</sub>", "x")
    value = value.replace("μ", "µ")
    value = value.replace("–", "-").replace("—", "-")
    value = value.replace("_", " ")
    value = value.replace("-", " ")
    value = " ".join(value.split())
    return value


def normalize_pollutant_key(value: str) -> str:
    value = normalize_text_key(value)
    value = value.replace(" ", "")
    value = value.replace(".", "")
    return value


def normalize_outcome_key(value: str) -> str:
    text = normalize_text_key(value)

    if "asthma" in text:
        return "asthma"

    if "amyotrophic lateral sclerosis" in text or " als " in f" {text} ":
        return "amyotrophic lateral sclerosis"

    if "alzheimer" in text:
        return "alzheimer disease"

    if "acute kidney injury" in text:
        return "acute kidney injury"

    if "adenocarcinoma" in text and "lung" in text:
        return "lung adenocarcinoma"

    return text


def clean_markdown_emphasis(text: str) -> str:
    return str(text or "").replace("**", "").replace("__", "").strip()


def trim_text(value: str, max_chars: int) -> str:
    value = str(value or "").strip()

    if len(value) <= max_chars:
        return value

    return value[:max_chars].rstrip() + "..."


def parse_float_or_none(value: Any) -> float | None:
    if value is None:
        return None

    text = str(value).strip()

    if not text or text.lower() in {"nan", "none", "null", "not reported", "nr"}:
        return None

    text = text.replace(",", ".")
    text = text.replace("−", "-")
    text = re.sub(r"[^0-9eE\.\-\+]", "", text)

    if not text:
        return None

    # Évite de parser des plages comme "10-11" comme un nombre.
    if re.match(r"^\d+(\.\d+)?-\d+(\.\d+)?$", text):
        return None

    try:
        return float(text)
    except Exception:
        return None


# ---------------------------------------------------------------------
# Effect measure classification
# ---------------------------------------------------------------------

def normalize_measure_type(value: str) -> str:
    text = normalize_text_key(value)

    mapping = {
        "or": "OR",
        "odds ratio": "OR",
        "adjusted odds ratio": "OR",
        "aor": "OR",
        "ivw or": "OR",
        "mr presso or": "OR",
        "rr": "RR",
        "risk ratio": "RR",
        "relative risk": "RR",
        "hr": "HR",
        "hazard ratio": "HR",
        "irr": "IRR",
        "incidence rate ratio": "IRR",
        "beta": "beta",
        "β": "beta",
        "coefficient": "coefficient",
        "regression coefficient": "coefficient",
        "percent change": "percent_change",
        "percentage change": "percent_change",
    }

    return mapping.get(text, value.strip())


def infer_measure_family(measure_type: str) -> str:
    mt = normalize_measure_type(measure_type)

    if mt in {"OR", "RR", "HR", "IRR"}:
        return "ratio"

    if mt in {"beta", "coefficient"}:
        return "continuous_effect"

    if mt == "percent_change":
        return "percent_change"

    return "other"


def infer_analysis_method(
    measure_name: str,
    source_section: str,
    evidence_sentence: str,
) -> str:
    text = normalize_text_key(f"{measure_name} {source_section} {evidence_sentence}")

    if "mr presso" in text or "mr presso" in text.replace("-", " "):
        return "MR-PRESSO"

    if "ivw" in text or "inverse variance weighted" in text:
        return "IVW"

    if "mr egger" in text:
        return "MR-Egger"

    if "weighted median" in text:
        return "weighted median"

    if "logistic regression" in text or "adjusted odds ratio" in text:
        return "logistic regression"

    if "cox" in text:
        return "Cox regression"

    if "linear regression" in text:
        return "linear regression"

    if "twas" in text:
        return "TWAS"

    if "gwas" in text:
        return "GWAS"

    if "cochran" in text or "q test" in text:
        return "heterogeneity test"

    return "unknown"


def infer_effect_direction(
    effect_value: float | None,
    measure_type: str,
    evidence_sentence: str,
) -> str:
    text = normalize_text_key(evidence_sentence)
    mt = normalize_measure_type(measure_type)
    family = infer_measure_family(mt)

    if "protective" in text or "decreased risk" in text or "lower risk" in text:
        return "decrease"

    if "increased risk" in text or "elevated risk" in text or "increase" in text:
        return "increase"

    if effect_value is None:
        return "unknown"

    if family == "ratio":
        if effect_value > 1:
            return "increase"
        if effect_value < 1:
            return "decrease"
        return "null"

    if family in {"continuous_effect", "percent_change"}:
        if effect_value > 0:
            return "increase"
        if effect_value < 0:
            return "decrease"
        return "null"

    return "unknown"


def infer_ci_level(ci_level: str, evidence_sentence: str) -> str:
    if ci_level:
        return ci_level

    text = evidence_sentence.lower()

    if "95%" in text or "95 %" in text:
        return "95%"

    return ""


def infer_significance_status(
    ci_lower: float | None,
    ci_upper: float | None,
    p_value: str,
    measure_type: str,
    evidence_sentence: str,
) -> str:
    text = normalize_text_key(evidence_sentence)
    mt = normalize_measure_type(measure_type)
    family = infer_measure_family(mt)

    if "without sufficient significance" in text:
        return "non_significant"

    if "not significant" in text or "non significant" in text:
        return "non_significant"

    if "statistically significant" in text:
        return "significant"

    p_num = parse_float_or_none(p_value)

    if p_num is not None:
        if p_num < 0.05:
            return "significant"
        return "non_significant"

    if ci_lower is not None and ci_upper is not None:
        if family == "ratio":
            if ci_lower > 1 or ci_upper < 1:
                return "significant"
            if ci_lower <= 1 <= ci_upper:
                return "non_significant"

        if family in {"continuous_effect", "percent_change"}:
            if ci_lower > 0 or ci_upper < 0:
                return "significant"
            if ci_lower <= 0 <= ci_upper:
                return "non_significant"

    return "unknown"


def infer_adjustment_status(measure_name: str, evidence_sentence: str) -> str:
    text = normalize_text_key(f"{measure_name} {evidence_sentence}")

    if "adjusted" in text or "covariate adjusted" in text:
        return "adjusted"

    if "unadjusted" in text or "crude" in text:
        return "unadjusted"

    return "unknown"


def looks_like_source_marker_not_pollutant(pollutant_mention: str) -> bool:
    text = normalize_text_key(pollutant_mention)

    source_marker_terms = [
        "proximity to roads",
        "road proximity",
        "roadway proximity",
        "point source",
        "point sources",
        "industrial point source index",
        "source index",
        "traffic index",
        "distance to road",
    ]

    return any(term in text for term in source_marker_terms)


def infer_measure_role(item: dict[str, Any]) -> str:
    """
    Classe la mesure statistique.

    Correction v3:
        - ne pas classer "genetically increased" comme gene_association;
        - les OR/RR/HR/IRR avec polluant + outcome + effet numérique restent
          direct_effect_estimate, même dans un contexte Mendelian randomization;
        - les tests de pléiotropie/hétérogénéité sont classés avant gene_association.
    """
    measure_name = item.get("measure_name", "")
    measure_type = normalize_measure_type(item.get("measure_type", ""))
    pollutant = item.get("pollutant_mention", "")
    outcome = item.get("outcome_mention", "")
    evidence = item.get("evidence_sentence", "")
    section = item.get("source_section", "")
    method = item.get("analysis_method", "")

    text = normalize_text_key(
        f"{measure_name} {measure_type} {pollutant} {outcome} "
        f"{evidence} {section} {method}"
    )

    effect_value_numeric = item.get("effect_value_numeric")

    has_numeric_effect = effect_value_numeric is not None
    has_pollutant = bool(str(pollutant).strip())
    has_outcome = bool(str(outcome).strip())

    direct_measure_types = {"OR", "RR", "HR", "IRR", "beta", "coefficient", "percent_change"}

    # 1. Tests de diagnostic : priorité avant les gènes.
    heterogeneity_terms = [
        "heterogeneity",
        "cochran",
        "q test",
        "cochran s q",
        "cochrans q",
    ]

    pleiotropy_terms = [
        "pleiotropy",
        "horizontal pleiotropy",
        "mr presso global",
        "global test",
    ]

    if any(term in text for term in heterogeneity_terms):
        return "heterogeneity_test"

    if any(term in text for term in pleiotropy_terms):
        return "pleiotropy_test"

    # 2. Effet direct complet : priorité haute.
    # Important : "genetically increased" en MR ne veut pas dire gene_association.
    if (
        measure_type in direct_measure_types
        and has_numeric_effect
        and has_pollutant
        and has_outcome
    ):
        if not looks_like_source_marker_not_pollutant(pollutant):
            return "direct_effect_estimate"

    # 3. Associations gènes / TWAS / GWAS.
    # On évite de matcher "gene" dans "genetically".
    gene_patterns = [
        r"\bgenes?\b",
        r"\bgene expression\b",
        r"\btwas\b",
        r"\bgwas\b",
        r"\btmem175\b",
        r"\busp35\b",
        r"\bphenotype of higher exposure\b",
        r"\bsignificantly associated with pm2\.?5\b",
        r"\bsignificantly associated with als in twas\b",
    ]

    if any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in gene_patterns):
        return "gene_association"

    # 4. Diagnostics sans effet numérique.
    diagnostic_terms = [
        "sensitivity analysis",
        "mr egger and weighted median",
        "weighted median",
        "egger intercept",
        "f statistics",
        "f statistic",
    ]

    if any(term in text for term in diagnostic_terms) and effect_value_numeric is None:
        return "model_diagnostic"

    if effect_value_numeric is None:
        return "incomplete_effect_description"

    if measure_type == "other":
        return "model_diagnostic"

    if looks_like_source_marker_not_pollutant(pollutant):
        return "source_marker_effect"

    return "direct_effect_estimate"


def infer_keep_for_association_builder(item: dict[str, Any]) -> tuple[bool, str]:
    """
    Règle stricte v2.

    On garde pour association_builder seulement si:
        - direct_effect_estimate
        - effet numérique présent
        - polluant présent
        - outcome présent
        - au moins IC ou p-value ou incrément explicite
        - pas source marker de type route/point source
    """
    measure_role = item.get("measure_role", "")
    effect_value = item.get("effect_value_numeric")
    pollutant_mention = str(item.get("pollutant_mention", "")).strip()
    outcome_mention = str(item.get("outcome_mention", "")).strip()

    ci_lower = item.get("ci_lower_numeric")
    ci_upper = item.get("ci_upper_numeric")
    p_value = str(item.get("p_value", "")).strip()
    exposure_increment = str(item.get("exposure_increment", "")).strip()

    if measure_role != "direct_effect_estimate":
        return False, f"Excluded because measure_role={measure_role}."

    if effect_value is None:
        return False, "Excluded because numeric effect value is missing."

    if not pollutant_mention:
        return False, "Excluded because pollutant_mention is missing."

    if not outcome_mention:
        return False, "Excluded because outcome_mention is missing."

    if looks_like_source_marker_not_pollutant(pollutant_mention):
        return False, "Excluded because pollutant_mention is a source/proximity marker, not a pollutant."

    has_ci = ci_lower is not None and ci_upper is not None
    has_p = bool(p_value)
    has_increment = bool(exposure_increment)

    if not (has_ci or has_p or has_increment):
        return False, "Excluded because CI, p-value, and exposure increment are all missing."

    return True, "Kept as complete direct pollutant-outcome effect estimate."


def deduplicate_effect_measures(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Déduplication v2.

    On fusionne les doublons exacts IVW abstract/results.
    On ne fusionne pas IVW et MR-PRESSO.
    """
    by_key: dict[tuple[str, str, str, str, str, str, str, str], dict[str, Any]] = {}

    for item in items:
        effect_num = item.get("effect_value_numeric")
        ci_low = item.get("ci_lower_numeric")
        ci_up = item.get("ci_upper_numeric")

        key = (
            normalize_text_key(item.get("measure_type", "")),
            normalize_text_key(item.get("analysis_method", "")),
            str(round(effect_num, 6)) if effect_num is not None else "",
            str(round(ci_low, 6)) if ci_low is not None else "",
            str(round(ci_up, 6)) if ci_up is not None else "",
            normalize_text_key(item.get("p_value", "")),
            normalize_pollutant_key(item.get("pollutant_mention", "")),
            normalize_outcome_key(item.get("outcome_mention", "")),
        )

        if key not in by_key:
            by_key[key] = item
            continue

        existing = by_key[key]

        # Préférer l'item gardé pour builder, puis meilleure confiance,
        # puis evidence plus informative.
        existing_keep = bool(existing.get("keep_for_association_builder"))
        item_keep = bool(item.get("keep_for_association_builder"))

        if item_keep and not existing_keep:
            by_key[key] = item
            continue

        if item_keep == existing_keep:
            if item.get("confidence", 0.0) > existing.get("confidence", 0.0):
                by_key[key] = item
                continue

            if len(item.get("evidence_sentence", "")) > len(existing.get("evidence_sentence", "")):
                by_key[key] = item

    return list(by_key.values())


def validate_effect_measure_output(obj: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(obj, dict):
        raise ValueError("Model output must be a JSON object.")

    if "effect_measures_found" not in obj:
        raise ValueError("Missing key: effect_measures_found")

    if "warnings" not in obj:
        obj["warnings"] = []

    if not isinstance(obj["effect_measures_found"], list):
        raise ValueError("effect_measures_found must be a list.")

    if not isinstance(obj["warnings"], list):
        raise ValueError("warnings must be a list.")

    required = {
        "measure_type",
        "measure_name",
        "effect_value",
        "ci_lower",
        "ci_upper",
        "ci_level",
        "p_value",
        "pollutant_mention",
        "outcome_mention",
        "exposure_increment",
        "exposure_increment_value",
        "exposure_increment_unit",
        "effect_direction",
        "statistical_significance",
        "adjustment_status",
        "evidence_sentence",
        "source_section",
        "source_type",
        "confidence",
        "reason_for_inclusion",
    }

    cleaned_items = []

    for idx, item in enumerate(obj["effect_measures_found"], start=1):
        if not isinstance(item, dict):
            raise ValueError(f"effect_measures_found[{idx}] must be an object.")

        missing = required - set(item.keys())

        if missing:
            raise ValueError(
                f"effect_measures_found[{idx}] missing keys: {sorted(missing)}"
            )

        cleaned = {}

        for key in required:
            cleaned[key] = str(item.get(key, "")).strip()

        cleaned["measure_type"] = normalize_measure_type(cleaned["measure_type"])

        cleaned["measure_name"] = trim_text(cleaned["measure_name"], 160)
        cleaned["pollutant_mention"] = trim_text(cleaned["pollutant_mention"], 160)
        cleaned["outcome_mention"] = trim_text(cleaned["outcome_mention"], 160)
        cleaned["exposure_increment"] = trim_text(cleaned["exposure_increment"], 160)
        cleaned["exposure_increment_unit"] = trim_text(
            cleaned["exposure_increment_unit"],
            80,
        )
        cleaned["evidence_sentence"] = clean_markdown_emphasis(
            trim_text(cleaned["evidence_sentence"], 420)
        )
        cleaned["source_section"] = trim_text(cleaned["source_section"], 120)
        cleaned["source_type"] = trim_text(cleaned["source_type"], 80)
        cleaned["reason_for_inclusion"] = trim_text(
            cleaned["reason_for_inclusion"],
            250,
        )

        effect_value_numeric = parse_float_or_none(cleaned["effect_value"])
        ci_lower_numeric = parse_float_or_none(cleaned["ci_lower"])
        ci_upper_numeric = parse_float_or_none(cleaned["ci_upper"])
        exposure_increment_value_numeric = parse_float_or_none(
            cleaned["exposure_increment_value"]
        )

        try:
            confidence = float(cleaned["confidence"])
        except Exception:
            confidence = 0.0

        confidence = max(0.0, min(1.0, confidence))

        cleaned["effect_value_numeric"] = effect_value_numeric
        cleaned["ci_lower_numeric"] = ci_lower_numeric
        cleaned["ci_upper_numeric"] = ci_upper_numeric
        cleaned["exposure_increment_value_numeric"] = exposure_increment_value_numeric
        cleaned["confidence"] = confidence

        cleaned["ci_level"] = infer_ci_level(
            cleaned["ci_level"],
            cleaned["evidence_sentence"],
        )

        cleaned["analysis_method"] = str(item.get("analysis_method", "")).strip()
        if not cleaned["analysis_method"]:
            cleaned["analysis_method"] = infer_analysis_method(
                cleaned["measure_name"],
                cleaned["source_section"],
                cleaned["evidence_sentence"],
            )

        if not cleaned["effect_direction"] or cleaned["effect_direction"] == "unknown":
            cleaned["effect_direction"] = infer_effect_direction(
                effect_value=effect_value_numeric,
                measure_type=cleaned["measure_type"],
                evidence_sentence=cleaned["evidence_sentence"],
            )

        if (
            not cleaned["statistical_significance"]
            or cleaned["statistical_significance"] == "unknown"
        ):
            cleaned["statistical_significance"] = infer_significance_status(
                ci_lower=ci_lower_numeric,
                ci_upper=ci_upper_numeric,
                p_value=cleaned["p_value"],
                measure_type=cleaned["measure_type"],
                evidence_sentence=cleaned["evidence_sentence"],
            )

        if not cleaned["adjustment_status"] or cleaned["adjustment_status"] == "unknown":
            cleaned["adjustment_status"] = infer_adjustment_status(
                cleaned["measure_name"],
                cleaned["evidence_sentence"],
            )

        cleaned["measure_family"] = infer_measure_family(cleaned["measure_type"])

        model_measure_role = str(item.get("measure_role", "")).strip()
        inferred_role = infer_measure_role(cleaned)

        if model_measure_role:
            cleaned["measure_role_model"] = model_measure_role
        else:
            cleaned["measure_role_model"] = ""

        cleaned["measure_role"] = inferred_role

        keep, reason_for_keep = infer_keep_for_association_builder(cleaned)

        cleaned["keep_for_association_builder"] = keep
        cleaned["reason_for_keep"] = reason_for_keep

        cleaned_items.append(cleaned)

    deduped = deduplicate_effect_measures(cleaned_items)
    obj["effect_measures_found"] = deduped

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
You are an effect measure extraction agent specialized in environmental epidemiology.

Your task:
Extract statistical effect measures explicitly reported in the provided scientific text.

Extract broadly:
- odds ratio / OR / adjusted odds ratio
- relative risk / risk ratio / RR
- hazard ratio / HR
- incidence rate ratio / IRR
- beta / β / regression coefficient
- percent change
- confidence interval
- p-value
- exposure increment or unit when explicitly attached to the effect estimate
- model diagnostics only if explicitly numeric, but classify them as diagnostics

Important rules:
- Extract effect measures only.
- Do not extract pollutants alone.
- Do not extract outcomes alone.
- Do not build final pollutant-outcome associations.
- Do not infer missing values.
- Keep non-significant results if a numeric effect estimate is present.
- If a sentence says "similar trend without sufficient significance" but gives no numeric effect, add a warning instead of inventing an effect.
- Evidence must be concise and must include the numeric effect estimate when available.
- Return one item per distinct numeric effect estimate.
- If one sentence contains multiple estimates, return multiple items.
- Keep pollutant_mention and outcome_mention if explicitly visible in the same sentence/passage; otherwise use empty string.
- Do not copy long paragraphs.

Classify measure_role when possible:
- direct_effect_estimate: direct pollutant/exposure -> health outcome estimate, e.g. OR for PM2.5 and ALS.
- incomplete_effect_description: text describes significance or trend but no numeric effect estimate.
- heterogeneity_test: Cochran Q, heterogeneity p-value.
- pleiotropy_test: MR-PRESSO global test, pleiotropy test.
- gene_association: gene/TWAS/GWAS association p-values not directly pollutant -> outcome.
- model_diagnostic: sensitivity/diagnostic statistics not a direct pollutant -> outcome estimate.
- source_marker_effect: road proximity or point source index effect.
- other: unclear.

Classify analysis_method when possible:
- logistic regression
- IVW
- MR-PRESSO
- MR-Egger
- weighted median
- Cox regression
- linear regression
- TWAS
- GWAS
- heterogeneity test
- unknown

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
  "effect_measures_found": [
    {
      "measure_type": "OR | RR | HR | IRR | beta | coefficient | percent_change | other",
      "measure_name": "adjusted odds ratio | odds ratio | IVW OR | MR-PRESSO OR | beta | ...",
      "analysis_method": "logistic regression | IVW | MR-PRESSO | MR-Egger | weighted median | Cox regression | linear regression | TWAS | GWAS | heterogeneity test | unknown",
      "measure_role": "direct_effect_estimate | incomplete_effect_description | heterogeneity_test | pleiotropy_test | gene_association | model_diagnostic | source_marker_effect | other",
      "effect_value": "numeric value as reported, e.g. 1.08",
      "ci_lower": "lower confidence interval bound if reported, else empty string",
      "ci_upper": "upper confidence interval bound if reported, else empty string",
      "ci_level": "95% | 90% | empty string",
      "p_value": "p-value if reported, else empty string",
      "pollutant_mention": "pollutant explicitly linked to this estimate if visible",
      "outcome_mention": "outcome explicitly linked to this estimate if visible",
      "exposure_increment": "full increment phrase, e.g. per 10-µg/m3 increase of NO",
      "exposure_increment_value": "numeric increment value if visible, e.g. 10",
      "exposure_increment_unit": "unit if visible, e.g. µg/m3, ppb, ppm, IQR",
      "effect_direction": "increase | decrease | null | mixed | unknown",
      "statistical_significance": "significant | non_significant | unknown",
      "adjustment_status": "adjusted | unadjusted | unknown",
      "evidence_sentence": "short evidence containing the numeric estimate, max 400 characters",
      "source_section": "PUBMED ABSTRACT | Results | Logistic regression | ...",
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
The Python pipeline will recompute:
- measure_role
- keep_for_association_builder
- reason_for_keep
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
  "effect_measures_found": [],
  "warnings": []
}
- Each effect measure item must contain:
  measure_type,
  measure_name,
  analysis_method,
  measure_role,
  effect_value,
  ci_lower,
  ci_upper,
  ci_level,
  p_value,
  pollutant_mention,
  outcome_mention,
  exposure_increment,
  exposure_increment_value,
  exposure_increment_unit,
  effect_direction,
  statistical_significance,
  adjustment_status,
  evidence_sentence,
  source_section,
  source_type,
  confidence,
  reason_for_inclusion
- evidence_sentence must be short, maximum 400 characters.
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


def summarize_outcomes_for_context(
    outcomes_found: list[dict[str, Any]],
) -> str:
    if not outcomes_found:
        return "No previous outcome extraction available."

    parts = []

    for item in outcomes_found:
        parts.append(
            f"- {item.get('outcome_normalized', '')}, "
            f"core={item.get('outcome_core', '')}, "
            f"role={item.get('outcome_role', '')}, "
            f"keep_final={item.get('keep_for_final_analysis', '')}"
        )

    return "\n".join(parts)


def build_focus_input_for_agent(state: EffectMeasureExtractionState) -> str:
    ctd = state.get("ctd_context", {})
    pubmed = state.get("pubmed", {})
    focus_text = state.get("focus_text", "")

    pollutants_summary = summarize_pollutants_for_context(
        state.get("pollutants_found", [])
    )
    outcomes_summary = summarize_outcomes_for_context(
        state.get("outcomes_found", [])
    )

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

PREVIOUS OUTCOME EXTRACTION CONTEXT:
{outcomes_summary}

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


def call_effect_measure_extractor_raw(
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

def effect_measure_extractor_node(
    state: EffectMeasureExtractionState,
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

        raw_response = call_effect_measure_extractor_raw(
            agent_input=agent_input,
            model=selected_model,
        )

        write_text(raw_response_path, raw_response)

        try:
            parsed = extract_json_object(raw_response)
            result = validate_effect_measure_output(parsed)
            repair_used = False

        except Exception as parse_exc:
            repair_response = call_json_repair(
                raw_response=raw_response,
                model=selected_model,
            )

            write_text(repair_response_path, repair_response)

            parsed = extract_json_object(repair_response)
            result = validate_effect_measure_output(parsed)

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
            "effect_measures_found": result.get("effect_measures_found", []),
            "warnings": state.get("warnings", []) + result.get("warnings", []),
            "metadata": {
                **state.get("metadata", {}),
                "llm_provider": "ilaas",
                "llm_base_url": ILAAS_BASE_URL,
                "effect_measure_extractor_model": selected_model,
                "effect_measure_extractor_ran_at": datetime.now().isoformat(timespec="seconds"),
                "effect_measure_extractor_status": "success",
                "json_repair_used": repair_used,
                "raw_response_path": str(raw_response_path),
                "repair_response_path": str(repair_response_path) if repair_used else "",
            },
        }

    except Exception as exc:
        return {
            "errors": state.get("errors", []) + [
                {
                    "agent": "effect_measure_extractor",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                }
            ],
            "metadata": {
                **state.get("metadata", {}),
                "llm_provider": "ilaas",
                "llm_base_url": ILAAS_BASE_URL,
                "effect_measure_extractor_model": selected_model,
                "effect_measure_extractor_ran_at": datetime.now().isoformat(timespec="seconds"),
                "effect_measure_extractor_status": "failed",
                "raw_response_path": str(raw_response_path),
                "repair_response_path": str(repair_response_path),
            },
        }


# ---------------------------------------------------------------------
# LangGraph
# ---------------------------------------------------------------------

def build_graph():
    graph = StateGraph(EffectMeasureExtractionState)

    graph.add_node("effect_measure_extractor", effect_measure_extractor_node)

    graph.add_edge(START, "effect_measure_extractor")
    graph.add_edge("effect_measure_extractor", END)

    return graph.compile()


# ---------------------------------------------------------------------
# Initial state
# ---------------------------------------------------------------------

def build_initial_state(
    pmid: str,
    selected_model: str,
) -> EffectMeasureExtractionState:
    doc = load_segmented_document(pmid)
    pollutants_found = load_pollutants_if_available(pmid)
    outcomes_found = load_outcomes_if_available(pmid)

    return {
        "pmid": pmid,
        "segmented_doc_path": str(SEGMENTED_DIR / f"{pmid}_segmented.json"),

        "ctd_context": doc.get("ctd_context", {}),
        "pubmed": doc.get("pubmed", {}),

        "focus_text": doc.get("focus_text", ""),
        "focus_chunks": doc.get("focus_chunks", []),
        "focus_sections": doc.get("focus_sections", []),

        "pollutants_found": pollutants_found,
        "outcomes_found": outcomes_found,
        "effect_measures_found": [],

        "warnings": [],
        "errors": [],

        "metadata": {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "agent_pipeline": "effect_measure_extractor_test_v2",
            "selected_model": selected_model,
            "input_focus_text_chars": len(doc.get("focus_text", "")),
            "input_focus_chunks": len(doc.get("focus_chunks", [])),
            "segmented_doc_path": str(SEGMENTED_DIR / f"{pmid}_segmented.json"),
            "previous_pollutants_loaded": len(pollutants_found),
            "previous_outcomes_loaded": len(outcomes_found),
            "extraction_scope": "statistical_effect_measures",
            "non_significant_results_policy": "keep_if_numeric_effect_available",
            "classification_policy": (
                "extract broadly, classify measure_role in Python, "
                "keep only complete direct effect estimates for association builder"
            ),
        },
    }


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run effect_measure_extractor agent on one segmented document using ILAAS."
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
    out_effects_path = OUT_DIR / f"{pmid}_effect_measures.json"

    write_json(out_state_path, final_state)

    effect_payload = {
        "pmid": pmid,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "effect_measures_found": final_state.get("effect_measures_found", []),
        "warnings": final_state.get("warnings", []),
        "errors": final_state.get("errors", []),
        "metadata": final_state.get("metadata", {}),
    }

    write_json(out_effects_path, effect_payload)

    print("=" * 80)
    print("EFFECT MEASURE EXTRACTOR COMPLETE — V2")
    print("=" * 80)
    print(f"PMID: {pmid}")
    print(f"Provider: ILAAS")
    print(f"Base URL: {ILAAS_BASE_URL}")
    print(f"Model: {selected_model}")
    print(f"Effect measures found: {len(final_state.get('effect_measures_found', []))}")
    print(f"Warnings: {len(final_state.get('warnings', []))}")
    print(f"Errors: {len(final_state.get('errors', []))}")
    print(f"JSON repair used: {final_state.get('metadata', {}).get('json_repair_used', False)}")
    print(f"Previous pollutants loaded: {final_state.get('metadata', {}).get('previous_pollutants_loaded', 0)}")
    print(f"Previous outcomes loaded: {final_state.get('metadata', {}).get('previous_outcomes_loaded', 0)}")
    print(f"State output: {out_state_path}")
    print(f"Effect output: {out_effects_path}")
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

    kept = [
        item for item in final_state.get("effect_measures_found", [])
        if item.get("keep_for_association_builder")
    ]

    print(f"KEPT FOR ASSOCIATION BUILDER: {len(kept)}")
    print("=" * 80)

    print("EFFECT MEASURES")
    print("-" * 80)

    for item in final_state.get("effect_measures_found", []):
        print(
            f"- {item.get('measure_type')} {item.get('effect_value')} "
            f"CI={item.get('ci_lower')}-{item.get('ci_upper')} "
            f"p={item.get('p_value')} "
            f"| pollutant={item.get('pollutant_mention')} "
            f"| outcome={item.get('outcome_mention')} "
            f"| method={item.get('analysis_method')} "
            f"| role={item.get('measure_role')} "
            f"| increment={item.get('exposure_increment')} "
            f"| direction={item.get('effect_direction')} "
            f"| sig={item.get('statistical_significance')} "
            f"| keep={item.get('keep_for_association_builder')} "
            f"| confidence={item.get('confidence')}"
        )
        print(f"  section: {item.get('source_section')}")
        print(f"  evidence: {item.get('evidence_sentence')}")
        print(f"  keep_reason: {item.get('reason_for_keep')}")
        print()

    if final_state.get("warnings"):
        print("WARNINGS")
        print("-" * 80)
        for warning in final_state["warnings"]:
            print(f"- {warning.get('warning_type')}: {warning.get('message')}")
        print("=" * 80)


if __name__ == "__main__":
    main()