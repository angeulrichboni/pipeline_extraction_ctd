from __future__ import annotations

import json
import os
import re
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import pandas as pd


DATA_ROOT = Path(os.getenv("CTD_DATA_ROOT", "data/processed"))

MAIN_PATH = DATA_ROOT / "final_tables" / "01_main_associations_analysis.csv"

# Ces 3 fichiers sont deja filtres sur D052638 (+ etudes humaines pour ixns et
# phenotype) par `src/runners/build_ctd_pm_human_dataset.py`, la premiere
# etape du pipeline. On ne refiltre plus les CSV bruts ici.
CTD_PM_HUMAN_DIR = DATA_ROOT / "ctd_pm_human"
CTD_DISEASES_PATH = CTD_PM_HUMAN_DIR / "diseases_pm.csv"
CTD_IXNS_PATH = CTD_PM_HUMAN_DIR / "ixns_human.csv"
CTD_PHENOTYPE_PATH = CTD_PM_HUMAN_DIR / "phenotype_human.csv"

# Table de reference globale CTD (tous chemicals confondus, pas de filtre
# possible ici) : utilisee uniquement pour recuperer les compteurs
# d'interactions/organismes globaux par gene.
CTD_GENES_PATH = Path("data/raw/CTD_D052638_genes_20260609050446.csv")

OUTPUT_DIR = DATA_ROOT / "enrichment"

TOP_N_GENES = 200
TOP_N_GENES_IN_MAIN_SUMMARY = 30

PM_CTD_CHEMICAL_ID = "D052638"
PM_CTD_CHEMICAL_NAME = "Particulate Matter"


# Generic cleaning / matching helpers


def clean_text(value: Any) -> str:
    if pd.isna(value):
        return ""

    text = str(value).strip()

    if text.lower() in {"nan", "none", "null"}:
        return ""

    return text


def normalize_text(value: Any) -> str:
    text = clean_text(value).lower()
    text = text.replace("₂", "2").replace("₃", "3")
    text = text.replace("ₓ", "x")
    text = text.replace("µ", "u").replace("μ", "u")
    text = text.replace("–", "-").replace("—", "-")
    text = re.sub(r"[^a-z0-9\.]+", " ", text)
    text = " ".join(text.split())
    return text


def compact(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", normalize_text(value))


def token_set(value: Any) -> set[str]:
    return set(normalize_text(value).replace(".", " ").split())


def prepare_match_candidates(df: pd.DataFrame, name_col: str) -> pd.DataFrame:
    out = df.copy()
    out["_match_name"] = out[name_col].apply(clean_text)
    out["_match_norm"] = out["_match_name"].apply(normalize_text)
    out["_match_compact"] = out["_match_name"].apply(compact)
    out["_match_tokens"] = out["_match_name"].apply(token_set)
    return out


def safe_float(value: Any) -> float | None:
    text = clean_text(value)
    if not text:
        return None

    text = text.replace(",", ".")
    text = re.sub(r"[^0-9eE\.\-\+]", "", text)

    if not text:
        return None

    try:
        return float(text)
    except Exception:
        return None


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)

    return pd.read_csv(path, low_memory=False)


def split_pipe_values(value: Any) -> list[str]:
    text = clean_text(value)

    if not text:
        return []

    values: list[str] = []

    for part in re.split(r"[|;,]", text):
        part = clean_text(part)
        if part:
            values.append(part)

    return values


def unique_join(values: list[str], limit: int | None = None) -> str:
    seen = set()
    out = []

    for value in values:
        value = clean_text(value)
        if not value:
            continue

        if value not in seen:
            seen.add(value)
            out.append(value)

    if limit is not None:
        out = out[:limit]

    return ";".join(out)


def has_homo_sapiens(value: Any) -> bool:
    text = normalize_text(value)
    return "homo sapiens" in text or text == "human" or "human" in text


def assert_unique_key(df: pd.DataFrame, key: str, name: str) -> None:
    """Fail fast if a merge key is not unique where many-to-one is expected."""

    if key not in df.columns:
        raise KeyError(f"{name}: missing key column {key!r}")

    duplicated = df[df[key].duplicated(keep=False)].copy()

    if duplicated.empty:
        return

    sample_cols = [
        col
        for col in [
            key,
            "outcome_normalized",
            "outcome_core",
            "outcome_category",
            "ctd_disease_name",
            "ctd_disease_match_confidence",
            "ctd_phenotype_name",
            "ctd_phenotype_match_confidence",
        ]
        if col in duplicated.columns
    ]

    sample = duplicated[sample_cols].head(20).to_dict(orient="records")

    raise ValueError(
        f"{name}: expected unique {key!r}, but found "
        f"{int(duplicated[key].nunique())} duplicated key(s). Sample: {sample}"
    )


# PM detection


def is_pm_like(row: pd.Series) -> bool:
    fields = [
        normalize_text(row.get("pollutant_general")),
        normalize_text(row.get("pollutant_specific")),
        normalize_text(row.get("pollutant_original_mention")),
    ]
    combined = " ".join(x for x in fields if x)
    combined_compact = compact(combined)

    exact_compact_values = {
        "pm",
        "pm25",
        "pm10",
        "pm1",
        "particulatematter",
        "ultrafineparticles",
        "ultrafineparticle",
        "ufp",
    }

    if any(compact(field) in exact_compact_values for field in fields):
        return True

    regex_patterns = [
        r"\bpm\s*2\.?5\b",
        r"\bpm\s*10\b",
        r"\bpm\s*1\b",
        r"\bparticulate\s+matter\b",
        r"\bfine\s+particulate\b",
        r"\bfine\s+particles\b",
        r"\bcoarse\s+particles\b",
        r"\bultrafine\s+particles?\b",
        r"\bufp\b",
    ]

    if any(re.search(pattern, combined) for pattern in regex_patterns):
        return True

    compact_patterns = [
        "particulatematter",
        "fineparticulate",
        "fineparticles",
        "coarseparticles",
        "ultrafineparticles",
        "ultrafineparticle",
    ]

    if any(pattern in combined_compact for pattern in compact_patterns):
        return True

    return False


# Matching logic for diseases / phenotypes


def match_score(query: str, candidate: str) -> tuple[float, str]:
    q_norm = normalize_text(query)
    c_norm = normalize_text(candidate)

    q_compact = compact(query)
    c_compact = compact(candidate)

    if not q_norm or not c_norm:
        return 0.0, "no_match"

    if q_norm == c_norm:
        return 1.0, "exact_normalized"

    if q_compact == c_compact:
        return 0.98, "exact_compact"

    # Phrase containment, useful for:
    # "Alzheimer's disease" vs "Alzheimer Disease"
    # "lung cancer incidence" vs "lung cancer"
    if len(q_norm) >= 5 and q_norm in c_norm:
        return 0.93, "query_contained_in_candidate"

    if len(c_norm) >= 5 and c_norm in q_norm:
        return 0.90, "candidate_contained_in_query"

    q_tokens = token_set(query)
    c_tokens = token_set(candidate)

    if q_tokens and c_tokens:
        inter = len(q_tokens & c_tokens)
        union = len(q_tokens | c_tokens)
        jaccard = inter / union if union else 0.0

        if jaccard >= 0.75:
            return 0.88 + min(0.08, (jaccard - 0.75) * 0.32), "high_token_overlap"

        if jaccard >= 0.55:
            return 0.78 + min(0.08, (jaccard - 0.55) * 0.40), "medium_token_overlap"

    ratio = SequenceMatcher(None, q_norm, c_norm).ratio()

    if ratio >= 0.90:
        return ratio, "high_fuzzy_ratio"

    if ratio >= 0.84:
        return ratio, "medium_fuzzy_ratio"

    return ratio, "low_similarity"


def find_best_match(
    query: str,
    candidates: pd.DataFrame,
    name_col: str,
    min_score: float,
) -> dict[str, Any]:
    best_score = 0.0
    best_type = "no_match"
    best_row: dict[str, Any] | None = None

    query = clean_text(query)

    if not query:
        return {
            "matched": False,
            "match_score": 0.0,
            "match_type": "empty_query",
            "row": None,
        }

    q_norm = normalize_text(query)
    q_compact = compact(query)
    q_tokens = token_set(query)

    if isinstance(candidates, pd.DataFrame):
        candidate_iter = (row for _, row in candidates.iterrows())
    else:
        candidate_iter = iter(candidates)

    for candidate_row in candidate_iter:
        candidate_name = clean_text(
            candidate_row.get("_match_name") or candidate_row.get(name_col)
        )

        if not candidate_name:
            continue

        c_norm = clean_text(candidate_row.get("_match_norm")) or normalize_text(candidate_name)
        c_compact = clean_text(candidate_row.get("_match_compact")) or compact(candidate_name)
        c_tokens = candidate_row.get("_match_tokens")

        if not isinstance(c_tokens, set):
            c_tokens = token_set(candidate_name)

        exact_or_contained = (
            q_norm == c_norm
            or q_compact == c_compact
            or (len(q_norm) >= 5 and q_norm in c_norm)
            or (len(c_norm) >= 5 and c_norm in q_norm)
            or (len(q_compact) >= 5 and q_compact in c_compact)
            or (len(c_compact) >= 5 and c_compact in q_compact)
        )
        token_overlap = bool(q_tokens & c_tokens)

        # Avoid expensive fuzzy scoring against the full CTD table. If there is
        # no lexical anchor at all, the row cannot become a defensible accepted
        # mapping under the QC rules below.
        if not exact_or_contained and not token_overlap:
            continue

        score, score_type = match_score(query, candidate_name)

        if score > best_score:
            best_score = score
            best_type = score_type
            if isinstance(candidate_row, dict):
                best_row = dict(candidate_row)
            else:
                best_row = candidate_row.to_dict()

    if best_row is None or best_score < min_score:
        return {
            "matched": False,
            "match_score": round(float(best_score), 4),
            "match_type": "below_threshold",
            "row": best_row,
        }

    return {
        "matched": True,
        "match_score": round(float(best_score), 4),
        "match_type": best_type,
        "row": best_row,
    }


def keep_best_mapping_per_outcome_key(
    df: pd.DataFrame,
    score_col: str,
    match_col: str,
    name: str,
) -> pd.DataFrame:
    """Keep exactly one mapping row per outcome_key.

    If several rows share one outcome_key, keep the matched row with the highest
    confidence. Unmatched rows are kept only when no match exists for that key.
    """

    if df.empty:
        return df.copy()

    out = df.copy()

    if score_col not in out.columns:
        out[score_col] = 0.0

    if match_col not in out.columns:
        out[match_col] = False

    out["_score_for_sort"] = out[score_col].apply(lambda x: safe_float(x) or 0.0)
    out["_match_for_sort"] = out[match_col].fillna(False).astype(bool).astype(int)

    out = out.sort_values(
        ["outcome_key", "_match_for_sort", "_score_for_sort", "outcome_query"],
        ascending=[True, False, False, True],
    )

    out = (
        out
        .drop_duplicates(subset=["outcome_key"], keep="first")
        .drop(columns=["_score_for_sort", "_match_for_sort"])
        .reset_index(drop=True)
    )

    assert_unique_key(out, "outcome_key", name)

    return out




# Mapping QC helpers

DISEASE_GENERIC_REVIEW_TERMS = {
    "death",
    "mortality",
    "all cause mortality",
    "all-cause mortality",
    "natural mortality",
    "nonaccidental mortality",
    "non accidental mortality",
    "birth weight",
    "blood pressure",
    "systolic blood pressure",
    "diastolic blood pressure",
    "inflammation",
    "airway inflammation",
}

DISEASE_GENERIC_REJECT_TERMS = {
    "cancer",
    "disease",
    "symptoms",
    "risk",
    "incidence",
    "fibrinogen",
    "hypothyroxinemia",
}

DISEASE_BAD_PAIR_PATTERNS = [
    ("cancer", "prostate cancer familial"),
    ("fibrinogen", "dysfibrinogenemia"),
    ("hypothyroxinemia", "hyperthyroxinemia"),
    ("annual deaths avoided", "death"),
    ("accidental deaths", "death"),
]

PHENOTYPE_GENERIC_REVIEW_TERMS = {
    "blood pressure",
    "systolic blood pressure",
    "diastolic blood pressure",
    "telomere length",
}

PHENOTYPE_ACCEPT_CORE_TERMS = {
    "methylation",
    "dna methylation",
    "platelet activation",
    "vasodilation",
    "memory",
    "cognition",
}

PHENOTYPE_BAD_PAIR_PATTERNS = [
    ("death", "cell death"),
    ("mortality", "cell death"),
    ("interleukin 1", "interleukin 10"),
    ("interleukin 1b", "interleukin 10"),
    ("interleukin 1beta", "interleukin 10"),
]


def contains_compact_phrase(text: Any, phrase: str) -> bool:
    return compact(phrase) in compact(text)


def is_generic_review_query(query: str, terms: set[str]) -> bool:
    q_norm = normalize_text(query)
    q_compact = compact(query)

    for term in terms:
        term_norm = normalize_text(term)
        term_compact = compact(term)
        if q_norm == term_norm or q_compact == term_compact:
            return True

    return False


def matches_bad_pair(query: str, candidate: str, patterns: list[tuple[str, str]]) -> bool:
    q_norm = normalize_text(query)
    c_norm = normalize_text(candidate)

    for q_pattern, c_pattern in patterns:
        if normalize_text(q_pattern) in q_norm and normalize_text(c_pattern) in c_norm:
            return True

    return False


def classify_disease_mapping_row(row: pd.Series) -> tuple[str, str]:
    """Classify a candidate disease mapping."""

    candidate_match = bool(row.get("ctd_pm_disease_candidate_match"))
    query = clean_text(row.get("outcome_query"))
    candidate = clean_text(row.get("ctd_disease_name"))
    match_type = clean_text(row.get("ctd_disease_match_type"))
    score = safe_float(row.get("ctd_disease_match_confidence")) or 0.0

    if not candidate_match:
        return "unmapped", "no_candidate_above_threshold"

    if not query or not candidate:
        return "unmapped", "empty_query_or_candidate"

    q_norm = normalize_text(query)
    c_norm = normalize_text(candidate)

    if matches_bad_pair(query, candidate, DISEASE_BAD_PAIR_PATTERNS):
        return "reject", "known_bad_disease_pair"

    if is_generic_review_query(query, DISEASE_GENERIC_REJECT_TERMS):
        return "reject", "generic_or_biomarker_query_not_specific_disease"

    if is_generic_review_query(query, DISEASE_GENERIC_REVIEW_TERMS):
        return "review", "generic_endpoint_or_non_disease_health_measure"

    # Avoid very broad single-token disease mappings when the candidate is much more specific.
    q_tokens = token_set(query)
    c_tokens = token_set(candidate)
    if len(q_tokens) == 1 and len(c_tokens) >= 3 and match_type == "query_contained_in_candidate":
        return "review", "single_generic_token_maps_to_more_specific_disease"

    if match_type in {"exact_normalized", "exact_compact"}:
        return "accept", "exact_disease_match"

    if match_type in {"high_token_overlap", "high_fuzzy_ratio"} and score >= 0.93:
        return "accept", "high_confidence_disease_similarity"

    if match_type == "candidate_contained_in_query":
        # Useful for: asthma incidence -> Asthma, risk of Parkinson disease -> Parkinson Disease,
        # acute myocardial infarction hospitalisations -> Myocardial Infarction.
        if len(c_tokens) >= 1 and not is_generic_review_query(candidate, DISEASE_GENERIC_REVIEW_TERMS | DISEASE_GENERIC_REJECT_TERMS):
            return "accept", "specific_disease_candidate_contained_in_outcome"

    if match_type == "query_contained_in_candidate":
        # This direction is riskier, because a short query may map to a too-specific disease.
        return "review", "query_contained_in_more_specific_disease_candidate"

    return "review", f"uncertain_disease_match_type:{match_type}"


def classify_phenotype_mapping_row(row: pd.Series) -> tuple[str, str]:
    """Classify a candidate phenotype mapping."""

    candidate_match = bool(row.get("ctd_pm_phenotype_candidate_match"))
    query = clean_text(row.get("outcome_query"))
    candidate = clean_text(row.get("ctd_phenotype_name"))
    match_type = clean_text(row.get("ctd_phenotype_match_type"))
    score = safe_float(row.get("ctd_phenotype_match_confidence")) or 0.0

    if not candidate_match:
        return "unmapped", "no_candidate_above_threshold"

    if not query or not candidate:
        return "unmapped", "empty_query_or_candidate"

    q_norm = normalize_text(query)
    c_norm = normalize_text(candidate)

    if matches_bad_pair(query, candidate, PHENOTYPE_BAD_PAIR_PATTERNS):
        return "reject", "known_bad_phenotype_pair"

    if is_generic_review_query(query, PHENOTYPE_GENERIC_REVIEW_TERMS):
        return "review", "generic_physiological_endpoint_maps_to_specific_process"

    if match_type in {"exact_normalized", "exact_compact"}:
        return "accept", "exact_phenotype_match"

    if match_type in {"high_token_overlap", "high_fuzzy_ratio"} and score >= 0.90:
        return "accept", "high_confidence_phenotype_similarity"

    # Accept common biomolecular endpoint variants where the CTD phenotype is a clear core process.
    for core in PHENOTYPE_ACCEPT_CORE_TERMS:
        if normalize_text(core) in c_norm and normalize_text(core) in q_norm:
            return "accept", f"accepted_core_phenotype:{core}"

    if match_type == "candidate_contained_in_query":
        return "review", "candidate_process_contained_in_more_specific_outcome"

    if match_type == "query_contained_in_candidate":
        return "review", "query_contained_in_more_specific_phenotype_candidate"

    return "review", f"uncertain_phenotype_match_type:{match_type}"


def apply_disease_mapping_qc(mapping: pd.DataFrame) -> pd.DataFrame:
    out = mapping.copy()

    decisions = out.apply(classify_disease_mapping_row, axis=1)
    out["ctd_disease_mapping_decision"] = [d for d, _ in decisions]
    out["ctd_disease_mapping_reason"] = [r for _, r in decisions]
    out["ctd_pm_disease_match"] = out["ctd_disease_mapping_decision"].eq("accept")

    return out


def apply_phenotype_mapping_qc(mapping: pd.DataFrame) -> pd.DataFrame:
    out = mapping.copy()

    decisions = out.apply(classify_phenotype_mapping_row, axis=1)
    out["ctd_phenotype_mapping_decision"] = [d for d, _ in decisions]
    out["ctd_phenotype_mapping_reason"] = [r for _, r in decisions]
    out["ctd_pm_phenotype_match"] = out["ctd_phenotype_mapping_decision"].eq("accept")

    return out

# Mapping builders


def build_pollutant_mapping(main_df: pd.DataFrame) -> pd.DataFrame:
    rows = []

    pollutant_cols = [
        "pollutant_general",
        "pollutant_specific",
        "pollutant_original_mention",
    ]

    unique_pollutants = (
        main_df[pollutant_cols + ["is_pm_d052638_candidate"]]
        .drop_duplicates()
        .copy()
    )

    for _, row in unique_pollutants.iterrows():
        is_pm = bool(row["is_pm_d052638_candidate"])

        if is_pm:
            ctd_chemical_id = PM_CTD_CHEMICAL_ID
            ctd_chemical_name = PM_CTD_CHEMICAL_NAME
            ctd_pollutant_match_type = "parent_particulate_matter_mapping"
            ctd_pollutant_match_confidence = 0.95
            mechanistic_enrichment_scope = "pm_d052638_human_ctd_available"
        else:
            ctd_chemical_id = ""
            ctd_chemical_name = ""
            ctd_pollutant_match_type = "not_enriched_non_pm"
            ctd_pollutant_match_confidence = 0.0
            mechanistic_enrichment_scope = "not_enriched_non_pm"

        rows.append(
            {
                "pollutant_general": clean_text(row.get("pollutant_general")),
                "pollutant_specific": clean_text(row.get("pollutant_specific")),
                "pollutant_original_mention": clean_text(row.get("pollutant_original_mention")),
                "is_pm_d052638_candidate": is_pm,
                "ctd_chemical_id": ctd_chemical_id,
                "ctd_chemical_name": ctd_chemical_name,
                "ctd_pollutant_match_type": ctd_pollutant_match_type,
                "ctd_pollutant_match_confidence": ctd_pollutant_match_confidence,
                "mechanistic_enrichment_scope": mechanistic_enrichment_scope,
            }
        )

    mapping = pd.DataFrame(rows)

    return mapping


def build_pm_outcome_base(main_df: pd.DataFrame) -> pd.DataFrame:
    """Build one unique PM outcome row per outcome_key."""

    pm_df = main_df[main_df["is_pm_d052638_candidate"]].copy()

    cols = [
        "outcome_normalized",
        "outcome_core",
        "outcome_category",
    ]

    outcome_df = pm_df[cols].copy()
    outcome_df["outcome_query"] = outcome_df.apply(
        lambda row: clean_text(row.get("outcome_normalized"))
        or clean_text(row.get("outcome_core")),
        axis=1,
    )
    outcome_df["outcome_key"] = outcome_df["outcome_query"].apply(compact)

    outcome_df = outcome_df[outcome_df["outcome_key"].astype(str).str.len() > 0].copy()

    outcome_df["_priority_has_normalized"] = outcome_df["outcome_normalized"].apply(lambda x: 1 if clean_text(x) else 0)
    outcome_df["_priority_has_core"] = outcome_df["outcome_core"].apply(lambda x: 1 if clean_text(x) else 0)
    outcome_df["_priority_has_category"] = outcome_df["outcome_category"].apply(lambda x: 1 if clean_text(x) else 0)

    outcome_df = outcome_df.sort_values(
        [
            "outcome_key",
            "_priority_has_normalized",
            "_priority_has_core",
            "_priority_has_category",
            "outcome_query",
        ],
        ascending=[True, False, False, False, True],
    )

    outcome_df = (
        outcome_df
        .drop_duplicates(subset=["outcome_key"], keep="first")
        .drop(columns=["_priority_has_normalized", "_priority_has_core", "_priority_has_category"])
        .reset_index(drop=True)
    )

    assert_unique_key(outcome_df, "outcome_key", "pm_outcome_base")

    return outcome_df


def build_disease_mapping(
    outcome_df: pd.DataFrame,
    diseases_df: pd.DataFrame,
) -> pd.DataFrame:
    diseases_pm = diseases_df[
        diseases_df["Chemical ID"].fillna("").astype(str).str.strip().eq(PM_CTD_CHEMICAL_ID)
    ].copy()
    diseases_pm = prepare_match_candidates(diseases_pm, "Disease Name")
    disease_records = diseases_pm.to_dict(orient="records")

    rows = []

    for _, outcome_row in outcome_df.iterrows():
        query = clean_text(outcome_row.get("outcome_query"))

        best = find_best_match(
            query=query,
            candidates=disease_records,
            name_col="Disease Name",
            min_score=0.86,
        )

        match_row = best.get("row") or {}

        rows.append(
            {
                "outcome_normalized": clean_text(outcome_row.get("outcome_normalized")),
                "outcome_core": clean_text(outcome_row.get("outcome_core")),
                "outcome_category": clean_text(outcome_row.get("outcome_category")),
                "outcome_query": query,
                "outcome_key": clean_text(outcome_row.get("outcome_key")),
                "ctd_pm_disease_candidate_match": bool(best["matched"]),
                "ctd_disease_name": clean_text(match_row.get("Disease Name")),
                "ctd_disease_id": clean_text(match_row.get("Disease ID")),
                "ctd_disease_direct_evidence": clean_text(match_row.get("Direct Evidence")),
                "ctd_disease_inference_network": clean_text(match_row.get("Inference Network")),
                "ctd_disease_inference_score": clean_text(match_row.get("Inference Score")),
                "ctd_disease_reference_count": clean_text(match_row.get("Reference Count")),
                "ctd_disease_match_type": best["match_type"],
                "ctd_disease_match_confidence": best["match_score"],
                "ctd_disease_species_filter_status": "not_available_in_source",
            }
        )

    mapping = pd.DataFrame(rows)
    mapping = keep_best_mapping_per_outcome_key(
        mapping,
        score_col="ctd_disease_match_confidence",
        match_col="ctd_pm_disease_candidate_match",
        name="ctd_pm_disease_mapping",
    )
    mapping = apply_disease_mapping_qc(mapping)

    return mapping


def build_phenotype_mapping(
    outcome_df: pd.DataFrame,
    phenotype_df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    phenotype_pm = phenotype_df[
        phenotype_df["Chemical ID"].fillna("").astype(str).str.strip().eq(PM_CTD_CHEMICAL_ID)
    ].copy()

    phenotype_pm["is_homo_sapiens"] = phenotype_pm["Organisms"].apply(has_homo_sapiens)
    phenotype_human = phenotype_pm[phenotype_pm["is_homo_sapiens"]].copy()

    phenotype_candidates = (
        phenotype_human
        .sort_values(["Phenotype", "Reference Count"], ascending=[True, False])
        .drop_duplicates(subset=["Phenotype", "Phenotype ID"])
        .copy()
    )
    phenotype_candidates = prepare_match_candidates(phenotype_candidates, "Phenotype")
    phenotype_records = phenotype_candidates.to_dict(orient="records")

    rows = []

    for _, outcome_row in outcome_df.iterrows():
        query = clean_text(outcome_row.get("outcome_query"))

        best = find_best_match(
            query=query,
            candidates=phenotype_records,
            name_col="Phenotype",
            min_score=0.82,
        )

        match_row = best.get("row") or {}

        rows.append(
            {
                "outcome_normalized": clean_text(outcome_row.get("outcome_normalized")),
                "outcome_core": clean_text(outcome_row.get("outcome_core")),
                "outcome_category": clean_text(outcome_row.get("outcome_category")),
                "outcome_query": query,
                "outcome_key": clean_text(outcome_row.get("outcome_key")),
                "ctd_pm_phenotype_candidate_match": bool(best["matched"]),
                "ctd_phenotype_name": clean_text(match_row.get("Phenotype")),
                "ctd_phenotype_id": clean_text(match_row.get("Phenotype ID")),
                "ctd_phenotype_interaction": clean_text(match_row.get("Interaction")),
                "ctd_phenotype_organisms": clean_text(match_row.get("Organisms")),
                "ctd_phenotype_anatomy": clean_text(match_row.get("Anatomy")),
                "ctd_phenotype_inference_network": clean_text(match_row.get("Inference Network")),
                "ctd_phenotype_reference_count": clean_text(match_row.get("Reference Count")),
                "ctd_phenotype_references": clean_text(match_row.get("References")),
                "ctd_phenotype_match_type": best["match_type"],
                "ctd_phenotype_match_confidence": best["match_score"],
                "ctd_phenotype_species_filter_status": "human_only",
            }
        )

    mapping = pd.DataFrame(rows)
    mapping = keep_best_mapping_per_outcome_key(
        mapping,
        score_col="ctd_phenotype_match_confidence",
        match_col="ctd_pm_phenotype_candidate_match",
        name="ctd_pm_phenotype_mapping",
    )
    mapping = apply_phenotype_mapping_qc(mapping)

    return mapping, phenotype_human


# Gene and phenotype long links


def aggregate_human_ixns(ixns_df: pd.DataFrame, genes_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    ixns_pm = ixns_df[
        ixns_df["Chemical ID"].fillna("").astype(str).str.strip().eq(PM_CTD_CHEMICAL_ID)
    ].copy()

    ixns_pm["is_homo_sapiens"] = ixns_pm["Organisms"].apply(has_homo_sapiens)
    ixns_human = ixns_pm[ixns_pm["is_homo_sapiens"]].copy()

    rows = []

    for (gene_symbol, gene_id), group in ixns_human.groupby(["Gene Symbol", "Gene ID"], dropna=False):
        actions = []
        refs = []
        organisms = []

        for _, row in group.iterrows():
            actions.extend(split_pipe_values(row.get("Interaction Actions")))
            refs.extend(split_pipe_values(row.get("References")))
            organisms.extend(split_pipe_values(row.get("Organisms")))

        action_counts = Counter(actions)
        top_actions = [action for action, _ in action_counts.most_common(10)]

        rows.append(
            {
                "gene_symbol": clean_text(gene_symbol),
                "gene_id": clean_text(gene_id),
                "ctd_chemical_id": PM_CTD_CHEMICAL_ID,
                "ctd_chemical_name": PM_CTD_CHEMICAL_NAME,
                "human_ixn_row_count": int(len(group)),
                "interaction_actions_top": unique_join(top_actions, limit=10),
                "reference_count_from_ixns": int(len(set(refs))),
                "references_sample": unique_join(refs, limit=20),
                "organisms": unique_join(organisms, limit=5),
                "species_filter_status": "human_only",
            }
        )

    aggregated = pd.DataFrame(rows)

    genes_norm = genes_df.rename(
        columns={
            "Gene Symbol": "gene_symbol",
            "Gene ID": "gene_id",
            "Interaction Count": "ctd_gene_interaction_count_global",
            "Organism Count": "ctd_gene_organism_count_global",
        }
    ).copy()

    genes_norm["gene_symbol"] = genes_norm["gene_symbol"].apply(clean_text)
    genes_norm["gene_id"] = genes_norm["gene_id"].apply(clean_text)

    aggregated["gene_symbol"] = aggregated["gene_symbol"].apply(clean_text)
    aggregated["gene_id"] = aggregated["gene_id"].apply(clean_text)

    aggregated = aggregated.merge(
        genes_norm[
            [
                "gene_symbol",
                "gene_id",
                "ctd_gene_interaction_count_global",
                "ctd_gene_organism_count_global",
            ]
        ],
        on=["gene_symbol", "gene_id"],
        how="left",
        validate="one_to_one",
    )

    aggregated = aggregated.sort_values(
        ["human_ixn_row_count", "ctd_gene_interaction_count_global", "gene_symbol"],
        ascending=[False, False, True],
    ).reset_index(drop=True)

    top_genes = aggregated.head(TOP_N_GENES).copy()
    top_genes["gene_rank_pm_human_ixns"] = range(1, len(top_genes) + 1)

    return aggregated, top_genes


def build_association_gene_links_top(
    main_df: pd.DataFrame,
    top_genes: pd.DataFrame,
) -> pd.DataFrame:
    pm_assoc = main_df[main_df["is_pm_d052638_candidate"]].copy()

    assoc_cols = [
        "association_id",
        "pmid",
        "pollutant_specific",
        "pollutant_general",
        "outcome_normalized",
        "outcome_core",
        "measure_type",
        "effect_value",
        "effect_direction",
    ]

    pm_assoc = pm_assoc[[col for col in assoc_cols if col in pm_assoc.columns]].copy()

    pm_assoc["_join_key"] = 1
    gene_links = top_genes.copy()
    gene_links["_join_key"] = 1

    out = pm_assoc.merge(gene_links, on="_join_key", how="inner")
    out = out.drop(columns=["_join_key"])

    return out


def build_association_phenotype_links(
    main_df: pd.DataFrame,
    phenotype_mapping: pd.DataFrame,
) -> pd.DataFrame:
    pm_assoc = main_df[main_df["is_pm_d052638_candidate"]].copy()

    pm_assoc["outcome_query"] = pm_assoc.apply(
        lambda row: clean_text(row.get("outcome_normalized"))
        or clean_text(row.get("outcome_core")),
        axis=1,
    )
    pm_assoc["outcome_key"] = pm_assoc["outcome_query"].apply(compact)

    pheno_matches = phenotype_mapping[
        phenotype_mapping["ctd_pm_phenotype_match"].astype(bool)
    ].copy()

    assert_unique_key(pheno_matches, "outcome_key", "phenotype_mapping_for_links")

    out = pm_assoc.merge(
        pheno_matches[
            [
                "outcome_key",
                "ctd_pm_phenotype_match",
                "ctd_phenotype_name",
                "ctd_phenotype_id",
                "ctd_phenotype_interaction",
                "ctd_phenotype_organisms",
                "ctd_phenotype_anatomy",
                "ctd_phenotype_inference_network",
                "ctd_phenotype_reference_count",
                "ctd_phenotype_references",
                "ctd_phenotype_match_type",
                "ctd_phenotype_match_confidence",
                "ctd_phenotype_species_filter_status",
            ]
        ],
        on="outcome_key",
        how="inner",
        validate="many_to_one",
    )

    columns = [
        "association_id",
        "pmid",
        "pollutant_specific",
        "pollutant_general",
        "outcome_normalized",
        "outcome_core",
        "measure_type",
        "effect_value",
        "effect_direction",
        "ctd_phenotype_name",
        "ctd_phenotype_id",
        "ctd_phenotype_interaction",
        "ctd_phenotype_organisms",
        "ctd_phenotype_anatomy",
        "ctd_phenotype_inference_network",
        "ctd_phenotype_reference_count",
        "ctd_phenotype_references",
        "ctd_phenotype_match_type",
        "ctd_phenotype_match_confidence",
        "ctd_phenotype_species_filter_status",
    ]

    return out[[col for col in columns if col in out.columns]].copy()


def build_gene_lookup(all_human_genes: pd.DataFrame) -> pd.DataFrame:
    """One metadata row per PM-human gene symbol."""

    if all_human_genes.empty:
        return all_human_genes.copy()

    gene_lookup = all_human_genes.copy()
    gene_lookup["gene_symbol"] = gene_lookup["gene_symbol"].apply(clean_text)
    gene_lookup = gene_lookup[gene_lookup["gene_symbol"].astype(str).str.len() > 0].copy()
    gene_lookup["_gene_symbol_key"] = gene_lookup["gene_symbol"].apply(compact)
    gene_lookup = gene_lookup[gene_lookup["_gene_symbol_key"].astype(str).str.len() > 0].copy()

    for col in ["human_ixn_row_count", "ctd_gene_interaction_count_global"]:
        if col in gene_lookup.columns:
            gene_lookup[col] = gene_lookup[col].apply(lambda x: safe_float(x) or 0.0)

    gene_lookup = gene_lookup.sort_values(
        ["_gene_symbol_key", "human_ixn_row_count", "ctd_gene_interaction_count_global"],
        ascending=[True, False, False],
    )
    gene_lookup = gene_lookup.drop_duplicates(subset=["_gene_symbol_key"], keep="first")

    return gene_lookup


def build_outcome_specific_gene_links(
    main_df: pd.DataFrame,
    disease_mapping: pd.DataFrame,
    phenotype_mapping: pd.DataFrame,
    all_human_genes: pd.DataFrame,
) -> pd.DataFrame:
    """Link PM associations to genes through matched CTD outcomes.

    A gene is linked only when it is both:
    - present in the CTD disease/phenotype inference network matched to the
      extracted outcome;
    - present in the CTD PM-human interaction-derived gene table.
    """

    gene_lookup = build_gene_lookup(all_human_genes)

    columns = [
        "association_id",
        "pmid",
        "pollutant_specific",
        "pollutant_general",
        "outcome_normalized",
        "outcome_core",
        "measure_type",
        "effect_value",
        "effect_direction",
        "ctd_mapping_type",
        "ctd_mapped_name",
        "ctd_mapped_id",
        "ctd_match_confidence",
        "ctd_reference_count",
        "gene_symbol",
        "gene_id",
        "gene_link_basis",
        "human_ixn_row_count",
        "interaction_actions_top",
        "reference_count_from_ixns",
        "references_sample",
        "ctd_gene_interaction_count_global",
        "ctd_gene_organism_count_global",
    ]

    if main_df.empty or gene_lookup.empty:
        return pd.DataFrame(columns=columns)

    gene_by_key = {
        clean_text(row.get("_gene_symbol_key")): row
        for row in gene_lookup.to_dict(orient="records")
        if clean_text(row.get("_gene_symbol_key"))
    }

    pm_assoc = main_df[main_df["is_pm_d052638_candidate"]].copy()

    if pm_assoc.empty:
        return pd.DataFrame(columns=columns)

    pm_assoc["outcome_query"] = pm_assoc.apply(
        lambda row: clean_text(row.get("outcome_normalized"))
        or clean_text(row.get("outcome_core")),
        axis=1,
    )
    pm_assoc["outcome_key"] = pm_assoc["outcome_query"].apply(compact)

    rows: list[dict[str, Any]] = []

    disease_matches = disease_mapping[
        disease_mapping["ctd_pm_disease_match"].astype(bool)
    ].copy()
    phenotype_matches = phenotype_mapping[
        phenotype_mapping["ctd_pm_phenotype_match"].astype(bool)
    ].copy()

    match_sources = [
        {
            "mapping_type": "disease",
            "df": disease_matches,
            "name_col": "ctd_disease_name",
            "id_col": "ctd_disease_id",
            "network_col": "ctd_disease_inference_network",
            "confidence_col": "ctd_disease_match_confidence",
            "reference_count_col": "ctd_disease_reference_count",
            "basis": "PM-human interaction + CTD disease inference network",
        },
        {
            "mapping_type": "phenotype",
            "df": phenotype_matches,
            "name_col": "ctd_phenotype_name",
            "id_col": "ctd_phenotype_id",
            "network_col": "ctd_phenotype_inference_network",
            "confidence_col": "ctd_phenotype_match_confidence",
            "reference_count_col": "ctd_phenotype_reference_count",
            "basis": "PM-human interaction + CTD phenotype inference network",
        },
    ]

    assoc_cols = [
        "association_id",
        "pmid",
        "pollutant_specific",
        "pollutant_general",
        "outcome_normalized",
        "outcome_core",
        "measure_type",
        "effect_value",
        "effect_direction",
        "outcome_key",
    ]

    pm_assoc_base = pm_assoc[[col for col in assoc_cols if col in pm_assoc.columns]].copy()
    outcome_gene_rows: list[dict[str, Any]] = []

    for source in match_sources:
        mapping = source["df"]

        if mapping.empty:
            continue

        needed = [
            "outcome_key",
            source["name_col"],
            source["id_col"],
            source["network_col"],
            source["confidence_col"],
            source["reference_count_col"],
        ]

        available = [col for col in needed if col in mapping.columns]
        source_mapping = mapping[available].copy()
        source_mapping = source_mapping.rename(
            columns={
                source["name_col"]: "ctd_mapped_name",
                source["id_col"]: "ctd_mapped_id",
                source["network_col"]: "ctd_inference_network",
                source["confidence_col"]: "ctd_match_confidence",
                source["reference_count_col"]: "ctd_reference_count",
            }
        )

        for _, mapping_row in source_mapping.iterrows():
            network_genes = split_pipe_values(mapping_row.get("ctd_inference_network"))

            for network_gene in network_genes:
                gene_key = compact(network_gene)

                if not gene_key:
                    continue

                gene_row = gene_by_key.get(gene_key)

                if gene_row is None:
                    continue

                outcome_gene_rows.append(
                    {
                        "outcome_key": clean_text(mapping_row.get("outcome_key")),
                        "ctd_mapping_type": source["mapping_type"],
                        "ctd_mapped_name": clean_text(mapping_row.get("ctd_mapped_name")),
                        "ctd_mapped_id": clean_text(mapping_row.get("ctd_mapped_id")),
                        "ctd_match_confidence": mapping_row.get("ctd_match_confidence"),
                        "ctd_reference_count": clean_text(mapping_row.get("ctd_reference_count")),
                        "gene_symbol": clean_text(gene_row.get("gene_symbol")),
                        "gene_id": clean_text(gene_row.get("gene_id")),
                        "gene_link_basis": source["basis"],
                        "human_ixn_row_count": gene_row.get("human_ixn_row_count"),
                        "interaction_actions_top": clean_text(gene_row.get("interaction_actions_top")),
                        "reference_count_from_ixns": gene_row.get("reference_count_from_ixns"),
                        "references_sample": clean_text(gene_row.get("references_sample")),
                        "ctd_gene_interaction_count_global": gene_row.get("ctd_gene_interaction_count_global"),
                        "ctd_gene_organism_count_global": gene_row.get("ctd_gene_organism_count_global"),
                    }
                )

    outcome_gene_links = pd.DataFrame(outcome_gene_rows)

    if outcome_gene_links.empty:
        return pd.DataFrame(columns=columns)

    outcome_gene_links = outcome_gene_links.drop_duplicates(
        subset=["outcome_key", "ctd_mapping_type", "ctd_mapped_id", "gene_symbol"],
        keep="first",
    )

    out = pm_assoc_base.merge(
        outcome_gene_links,
        on="outcome_key",
        how="inner",
        validate="many_to_many",
    )

    out = out[[col for col in columns if col in out.columns]].copy()

    out = out.drop_duplicates(
        subset=["association_id", "ctd_mapping_type", "ctd_mapped_id", "gene_symbol"],
        keep="first",
    ).reset_index(drop=True)

    return out


def summarize_outcome_specific_gene_links(
    gene_links: pd.DataFrame,
) -> pd.DataFrame:
    if gene_links.empty:
        return pd.DataFrame(
            columns=[
                "association_id",
                "outcome_specific_gene_link_available",
                "outcome_specific_gene_count",
                "outcome_specific_gene_symbols_top",
                "outcome_specific_gene_mapping_types",
                "outcome_specific_gene_link_basis",
            ]
        )

    rows = []

    for association_id, group in gene_links.groupby("association_id", dropna=False):
        gene_symbols = (
            group[["gene_symbol", "human_ixn_row_count", "ctd_gene_interaction_count_global"]]
            .drop_duplicates(subset=["gene_symbol"])
            .copy()
        )
        gene_symbols["human_ixn_row_count"] = gene_symbols["human_ixn_row_count"].apply(
            lambda x: safe_float(x) or 0.0
        )
        gene_symbols["ctd_gene_interaction_count_global"] = gene_symbols[
            "ctd_gene_interaction_count_global"
        ].apply(lambda x: safe_float(x) or 0.0)
        gene_symbols = gene_symbols.sort_values(
            ["human_ixn_row_count", "ctd_gene_interaction_count_global", "gene_symbol"],
            ascending=[False, False, True],
        )

        rows.append(
            {
                "association_id": clean_text(association_id),
                "outcome_specific_gene_link_available": True,
                "outcome_specific_gene_count": int(gene_symbols["gene_symbol"].nunique()),
                "outcome_specific_gene_symbols_top": unique_join(
                    gene_symbols["gene_symbol"].fillna("").astype(str).tolist(),
                    limit=TOP_N_GENES_IN_MAIN_SUMMARY,
                ),
                "outcome_specific_gene_mapping_types": unique_join(
                    group["ctd_mapping_type"].fillna("").astype(str).tolist()
                ),
                "outcome_specific_gene_link_basis": unique_join(
                    group["gene_link_basis"].fillna("").astype(str).tolist()
                ),
            }
        )

    return pd.DataFrame(rows)


# Main enriched table


def build_main_enriched(
    main_df: pd.DataFrame,
    pollutant_mapping: pd.DataFrame,
    disease_mapping: pd.DataFrame,
    phenotype_mapping: pd.DataFrame,
    all_human_genes: pd.DataFrame,
    top_genes: pd.DataFrame,
    phenotype_human: pd.DataFrame,
    outcome_specific_gene_links: pd.DataFrame,
) -> pd.DataFrame:
    enriched = main_df.copy()

    merge_pollutant_cols = [
        "pollutant_general",
        "pollutant_specific",
        "pollutant_original_mention",
    ]

    enriched = enriched.merge(
        pollutant_mapping,
        on=merge_pollutant_cols + ["is_pm_d052638_candidate"],
        how="left",
        validate="many_to_one",
    )

    if len(enriched) != len(main_df):
        raise RuntimeError(
            "Row count changed after pollutant mapping merge: "
            f"input={len(main_df)}, output={len(enriched)}"
        )

    enriched["outcome_query"] = enriched.apply(
        lambda row: clean_text(row.get("outcome_normalized"))
        or clean_text(row.get("outcome_core")),
        axis=1,
    )
    enriched["outcome_key"] = enriched["outcome_query"].apply(compact)

    disease_cols = [
        "outcome_key",
        "ctd_pm_disease_candidate_match",
        "ctd_pm_disease_match",
        "ctd_disease_mapping_decision",
        "ctd_disease_mapping_reason",
        "ctd_disease_name",
        "ctd_disease_id",
        "ctd_disease_direct_evidence",
        "ctd_disease_inference_network",
        "ctd_disease_inference_score",
        "ctd_disease_reference_count",
        "ctd_disease_match_type",
        "ctd_disease_match_confidence",
        "ctd_disease_species_filter_status",
    ]

    phenotype_cols = [
        "outcome_key",
        "ctd_pm_phenotype_candidate_match",
        "ctd_pm_phenotype_match",
        "ctd_phenotype_mapping_decision",
        "ctd_phenotype_mapping_reason",
        "ctd_phenotype_name",
        "ctd_phenotype_id",
        "ctd_phenotype_interaction",
        "ctd_phenotype_reference_count",
        "ctd_phenotype_match_type",
        "ctd_phenotype_match_confidence",
        "ctd_phenotype_species_filter_status",
    ]

    assert_unique_key(disease_mapping[disease_cols], "outcome_key", "disease_mapping_before_merge")
    assert_unique_key(phenotype_mapping[phenotype_cols], "outcome_key", "phenotype_mapping_before_merge")

    enriched = enriched.merge(
        disease_mapping[disease_cols],
        on="outcome_key",
        how="left",
        validate="many_to_one",
    )

    if len(enriched) != len(main_df):
        raise RuntimeError(
            "Row count changed after disease mapping merge: "
            f"input={len(main_df)}, output={len(enriched)}"
        )

    enriched = enriched.merge(
        phenotype_mapping[phenotype_cols],
        on="outcome_key",
        how="left",
        validate="many_to_one",
    )

    if len(enriched) != len(main_df):
        raise RuntimeError(
            "Row count changed after phenotype mapping merge: "
            f"input={len(main_df)}, output={len(enriched)}"
        )

    gene_summary = summarize_outcome_specific_gene_links(outcome_specific_gene_links)

    if not gene_summary.empty:
        assert_unique_key(
            gene_summary,
            "association_id",
            "outcome_specific_gene_summary_before_merge",
        )

    enriched = enriched.merge(
        gene_summary,
        on="association_id",
        how="left",
        validate="one_to_one",
    )

    if len(enriched) != len(main_df):
        raise RuntimeError(
            "Row count changed after outcome-specific gene summary merge: "
            f"input={len(main_df)}, output={len(enriched)}"
        )

    gene_summary_defaults = {
        "outcome_specific_gene_link_available": False,
        "outcome_specific_gene_count": 0,
        "outcome_specific_gene_symbols_top": "",
        "outcome_specific_gene_mapping_types": "",
        "outcome_specific_gene_link_basis": "",
    }

    for field, default_value in gene_summary_defaults.items():
        if field not in enriched.columns:
            enriched[field] = default_value

        enriched[field] = enriched[field].fillna(default_value)

    human_gene_total = int(all_human_genes["gene_symbol"].nunique()) if len(all_human_genes) else 0
    top_gene_count = int(top_genes["gene_symbol"].nunique()) if len(top_genes) else 0
    top_gene_symbols = unique_join(
        top_genes["gene_symbol"].fillna("").astype(str).tolist(),
        limit=TOP_N_GENES_IN_MAIN_SUMMARY,
    )

    human_phenotype_total = int(phenotype_human["Phenotype"].nunique()) if len(phenotype_human) else 0

    enriched["linked_human_gene_total_available"] = enriched["is_pm_d052638_candidate"].apply(
        lambda x: human_gene_total if bool(x) else 0
    )
    enriched["linked_human_gene_count_top"] = enriched["is_pm_d052638_candidate"].apply(
        lambda x: top_gene_count if bool(x) else 0
    )
    enriched["linked_human_gene_symbols_top"] = enriched["is_pm_d052638_candidate"].apply(
        lambda x: top_gene_symbols if bool(x) else ""
    )
    enriched["linked_human_phenotype_total_available"] = enriched["is_pm_d052638_candidate"].apply(
        lambda x: human_phenotype_total if bool(x) else 0
    )

    enriched["ctd_pm_disease_match"] = enriched["ctd_pm_disease_match"].fillna(False).astype(bool)
    enriched["ctd_pm_phenotype_match"] = enriched["ctd_pm_phenotype_match"].fillna(False).astype(bool)

    def outcome_mapping_type(row: pd.Series) -> str:
        has_disease = bool(row.get("ctd_pm_disease_match"))
        has_phenotype = bool(row.get("ctd_pm_phenotype_match"))

        if has_disease and has_phenotype:
            return "both"

        if has_disease:
            return "disease"

        if has_phenotype:
            return "phenotype"

        if bool(row.get("is_pm_d052638_candidate")):
            return "unmapped_pm_outcome"

        return "not_enriched_non_pm"

    enriched["outcome_mapping_type"] = enriched.apply(outcome_mapping_type, axis=1)

    enriched["outcome_specific_ctd_match_available"] = (
        enriched["ctd_pm_disease_match"] | enriched["ctd_pm_phenotype_match"]
    )

    enriched["pm_ctd_gene_resources_available"] = enriched["is_pm_d052638_candidate"].apply(
        lambda x: bool(x) and human_gene_total > 0
    )

    enriched["pm_ctd_phenotype_resources_available"] = enriched["is_pm_d052638_candidate"].apply(
        lambda x: bool(x) and human_phenotype_total > 0
    )

    enriched["mechanism_available"] = (
        enriched["pm_ctd_gene_resources_available"]
        | enriched["pm_ctd_phenotype_resources_available"]
        | enriched["outcome_specific_ctd_match_available"]
    )

    # For non-PM rows, keep enrichment fields empty/False, not invented.
    non_pm_mask = ~enriched["is_pm_d052638_candidate"].astype(bool)

    fields_to_blank = [
        "ctd_chemical_id",
        "ctd_chemical_name",
        "ctd_disease_name",
        "ctd_disease_id",
        "ctd_disease_direct_evidence",
        "ctd_disease_inference_network",
        "ctd_disease_inference_score",
        "ctd_disease_reference_count",
        "ctd_disease_match_type",
        "ctd_disease_mapping_decision",
        "ctd_disease_mapping_reason",
        "ctd_disease_species_filter_status",
        "ctd_phenotype_name",
        "ctd_phenotype_id",
        "ctd_phenotype_interaction",
        "ctd_phenotype_reference_count",
        "ctd_phenotype_match_type",
        "ctd_phenotype_mapping_decision",
        "ctd_phenotype_mapping_reason",
        "ctd_phenotype_species_filter_status",
    ]

    for field in fields_to_blank:
        if field in enriched.columns:
            enriched.loc[non_pm_mask, field] = ""

    fields_to_zero = [
        "ctd_pollutant_match_confidence",
        "ctd_disease_match_confidence",
        "ctd_phenotype_match_confidence",
    ]

    for field in fields_to_zero:
        if field in enriched.columns:
            enriched.loc[non_pm_mask, field] = 0.0

    fields_to_false = [
        "ctd_pm_disease_candidate_match",
        "ctd_pm_disease_match",
        "ctd_pm_phenotype_candidate_match",
        "ctd_pm_phenotype_match",
        "outcome_specific_ctd_match_available",
        "pm_ctd_gene_resources_available",
        "pm_ctd_phenotype_resources_available",
        "mechanism_available",
        "outcome_specific_gene_link_available",
    ]

    for field in fields_to_false:
        if field in enriched.columns:
            enriched.loc[non_pm_mask, field] = False

    enriched.loc[non_pm_mask, "outcome_mapping_type"] = "not_enriched_non_pm"
    enriched.loc[non_pm_mask, "outcome_specific_ctd_match_available"] = False
    enriched.loc[non_pm_mask, "outcome_specific_gene_count"] = 0
    enriched.loc[non_pm_mask, "outcome_specific_gene_symbols_top"] = ""
    enriched.loc[non_pm_mask, "outcome_specific_gene_mapping_types"] = ""
    enriched.loc[non_pm_mask, "outcome_specific_gene_link_basis"] = ""
    enriched.loc[non_pm_mask, "mechanism_available"] = False

    if len(enriched) != len(main_df):
        duplicated_associations = (
            enriched["association_id"].duplicated().sum()
            if "association_id" in enriched.columns
            else "unknown"
        )
        raise RuntimeError(
            "main_associations_enriched must preserve one row per input association: "
            f"input={len(main_df)}, output={len(enriched)}, "
            f"duplicated_association_rows={duplicated_associations}"
        )

    return enriched


# Audit / main


def write_audit(
    path: Path,
    main_df: pd.DataFrame,
    enriched_df: pd.DataFrame,
    disease_mapping: pd.DataFrame,
    phenotype_mapping: pd.DataFrame,
    all_human_genes: pd.DataFrame,
    top_genes: pd.DataFrame,
    phenotype_human: pd.DataFrame,
    gene_links_top: pd.DataFrame,
    outcome_specific_gene_links: pd.DataFrame,
    phenotype_links: pd.DataFrame,
) -> None:
    audit = {
        "input_main_rows": int(len(main_df)),
        "output_enriched_rows": int(len(enriched_df)),
        "row_count_preserved": bool(len(main_df) == len(enriched_df)),
        "pm_d052638_candidate_rows": int(main_df["is_pm_d052638_candidate"].sum()),
        "non_pm_rows": int((~main_df["is_pm_d052638_candidate"]).sum()),
        "unique_pm_candidate_outcomes": int(
            main_df[main_df["is_pm_d052638_candidate"]]["outcome_normalized"].nunique()
        ),
        "unique_pm_outcome_keys_used_for_mapping": int(disease_mapping["outcome_key"].nunique()),
        "disease_mapping_rows": int(len(disease_mapping)),
        "disease_mapping_candidate_matches_raw": int(disease_mapping["ctd_pm_disease_candidate_match"].sum()),
        "disease_mapping_matches_accepted": int(disease_mapping["ctd_pm_disease_match"].sum()),
        "disease_mapping_decision_distribution": disease_mapping["ctd_disease_mapping_decision"].value_counts(dropna=False).to_dict(),
        "phenotype_mapping_rows": int(len(phenotype_mapping)),
        "phenotype_mapping_candidate_matches_raw": int(phenotype_mapping["ctd_pm_phenotype_candidate_match"].sum()),
        "phenotype_mapping_matches_accepted": int(phenotype_mapping["ctd_pm_phenotype_match"].sum()),
        "phenotype_mapping_decision_distribution": phenotype_mapping["ctd_phenotype_mapping_decision"].value_counts(dropna=False).to_dict(),
        "human_pm_gene_total_available": int(all_human_genes["gene_symbol"].nunique()),
        "top_human_pm_genes_used": int(top_genes["gene_symbol"].nunique()),
        "human_pm_phenotype_total_available": int(phenotype_human["Phenotype"].nunique()),
        "association_pm_gene_links_top_rows": int(len(gene_links_top)),
        "association_pm_gene_links_top_scope": "PM-level context, not outcome-specific",
        "association_pm_gene_links_outcome_specific_rows": int(len(outcome_specific_gene_links)),
        "association_pm_gene_links_outcome_specific_associations": int(
            outcome_specific_gene_links["association_id"].nunique()
        ) if not outcome_specific_gene_links.empty else 0,
        "association_pm_gene_links_outcome_specific_genes": int(
            outcome_specific_gene_links["gene_symbol"].nunique()
        ) if not outcome_specific_gene_links.empty else 0,
        "association_pm_phenotype_links_rows": int(len(phenotype_links)),
        "enriched_pm_rows_with_outcome_specific_ctd_match": int(
            enriched_df["outcome_specific_ctd_match_available"].sum()
        ),
        "enriched_pm_rows_with_outcome_specific_gene_links": int(
            enriched_df["outcome_specific_gene_link_available"].sum()
        ),
        "enriched_rows_with_mechanism_available": int(enriched_df["mechanism_available"].sum()),
        "rules": {
            "mechanistic_scope": "PM / D052638 only",
            "non_pm_handling": "kept in enriched file but not mechanistically enriched",
            "ixns_species_filter": "Organisms contains Homo sapiens",
            "phenotype_species_filter": "Organisms contains Homo sapiens",
            "disease_species_filter": "not available in source",
            "top_gene_selection": f"top {TOP_N_GENES} human PM genes by CTD human ixn row count",
            "outcome_specific_gene_selection": (
                "genes must be in the accepted CTD disease/phenotype inference "
                "network for the extracted outcome and in the PM-human gene table"
            ),
            "no_invented_no_no2_o3_mapping": True,
            "main_enriched_row_policy": "one output row per input association_id",
            "mapping_qc_policy": "only accept decisions are used as automatic disease/phenotype enrichment; review/reject remain in mapping files",
        },
    }

    path.write_text(json.dumps(audit, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    main_df = read_csv(MAIN_PATH)
    main_df["is_pm_d052638_candidate"] = main_df.apply(is_pm_like, axis=1)

    diseases_df = read_csv(CTD_DISEASES_PATH)
    genes_df = read_csv(CTD_GENES_PATH)
    ixns_df = read_csv(CTD_IXNS_PATH)
    phenotype_df = read_csv(CTD_PHENOTYPE_PATH)

    outcome_df = build_pm_outcome_base(main_df)

    pollutant_mapping = build_pollutant_mapping(main_df)
    disease_mapping = build_disease_mapping(outcome_df, diseases_df)
    phenotype_mapping, phenotype_human = build_phenotype_mapping(outcome_df, phenotype_df)

    assert_unique_key(outcome_df, "outcome_key", "outcome_df")
    assert_unique_key(disease_mapping, "outcome_key", "disease_mapping")
    assert_unique_key(phenotype_mapping, "outcome_key", "phenotype_mapping")

    all_human_genes, top_genes = aggregate_human_ixns(ixns_df, genes_df)

    gene_links_top = build_association_gene_links_top(main_df, top_genes)
    outcome_specific_gene_links = build_outcome_specific_gene_links(
        main_df=main_df,
        disease_mapping=disease_mapping,
        phenotype_mapping=phenotype_mapping,
        all_human_genes=all_human_genes,
    )
    phenotype_links = build_association_phenotype_links(main_df, phenotype_mapping)

    enriched = build_main_enriched(
        main_df=main_df,
        pollutant_mapping=pollutant_mapping,
        disease_mapping=disease_mapping,
        phenotype_mapping=phenotype_mapping,
        all_human_genes=all_human_genes,
        top_genes=top_genes,
        phenotype_human=phenotype_human,
        outcome_specific_gene_links=outcome_specific_gene_links,
    )

    outputs = {
        "ctd_pollutant_mapping.csv": pollutant_mapping,
        "ctd_pm_disease_mapping.csv": disease_mapping,
        "ctd_pm_phenotype_mapping.csv": phenotype_mapping,
        "ctd_pm_human_genes_all.csv": all_human_genes,
        "ctd_pm_human_genes_top.csv": top_genes,
        "association_pm_gene_links_top.csv": gene_links_top,
        "association_pm_gene_links_outcome_specific.csv": outcome_specific_gene_links,
        "association_pm_phenotype_links.csv": phenotype_links,
        "main_associations_enriched.csv": enriched,
    }

    for filename, df in outputs.items():
        path = OUTPUT_DIR / filename
        df.to_csv(path, index=False)
        print(f"WROTE {path} | rows={len(df)} | cols={len(df.columns)}")

    write_audit(
        path=OUTPUT_DIR / "ctd_pm_enrichment_audit.json",
        main_df=main_df,
        enriched_df=enriched,
        disease_mapping=disease_mapping,
        phenotype_mapping=phenotype_mapping,
        all_human_genes=all_human_genes,
        top_genes=top_genes,
        phenotype_human=phenotype_human,
        gene_links_top=gene_links_top,
        outcome_specific_gene_links=outcome_specific_gene_links,
        phenotype_links=phenotype_links,
    )

    print("=" * 100)
    print("CTD PM ENRICHMENT COMPLETE")
    print("=" * 100)
    print(f"Input main rows: {len(main_df)}")
    print(f"Output enriched rows: {len(enriched)}")
    print(f"Row count preserved: {len(main_df) == len(enriched)}")
    print(f"PM/D052638 candidate rows: {int(main_df['is_pm_d052638_candidate'].sum())}")
    print(f"Non-PM rows kept without mechanistic enrichment: {int((~main_df['is_pm_d052638_candidate']).sum())}")
    print(f"Unique PM outcome keys used for mapping: {int(disease_mapping['outcome_key'].nunique())}")
    print(f"Disease raw candidates: {int(disease_mapping['ctd_pm_disease_candidate_match'].sum())}/{len(disease_mapping)}")
    print(f"Disease accepted matches: {int(disease_mapping['ctd_pm_disease_match'].sum())}/{len(disease_mapping)}")
    print("Disease mapping decisions:", disease_mapping["ctd_disease_mapping_decision"].value_counts(dropna=False).to_dict())
    print(f"Phenotype raw candidates: {int(phenotype_mapping['ctd_pm_phenotype_candidate_match'].sum())}/{len(phenotype_mapping)}")
    print(f"Phenotype accepted matches: {int(phenotype_mapping['ctd_pm_phenotype_match'].sum())}/{len(phenotype_mapping)}")
    print("Phenotype mapping decisions:", phenotype_mapping["ctd_phenotype_mapping_decision"].value_counts(dropna=False).to_dict())
    print(f"Human PM genes available: {int(all_human_genes['gene_symbol'].nunique())}")
    print(f"Top human PM genes used: {int(top_genes['gene_symbol'].nunique())}")
    print(f"Association-gene top links: {len(gene_links_top)}")
    print(f"Outcome-specific association-gene links: {len(outcome_specific_gene_links)}")
    print(f"Association-phenotype links: {len(phenotype_links)}")
    print(f"Audit: {OUTPUT_DIR / 'ctd_pm_enrichment_audit.json'}")


if __name__ == "__main__":
    main()
