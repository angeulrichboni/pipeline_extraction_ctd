#!/usr/bin/env python3
"""
Segmente les documents du prototype avant extraction LLM.

Version v2:
    - sélection plus stricte des focus_sections;
    - exclusion des gros blocs supplementary / other;
    - reclassification de Logistic regression en quantitative_results;
    - diagnostics sur sections incluses, exclues, tronquées.

Entrée:
    data/prototype/llm_inputs/{pmid}.json

Sorties:
    data/prototype/segmented_documents/{pmid}_segmented.json
    data/prototype/segmented_documents/segmented_documents_manifest_test.csv
    data/prototype/segmented_documents/segmented_documents_audit_test.json

Aucun appel LLM ici.
"""

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------

PROTOTYPE_DIR = Path("data/prototype")
INPUT_DIR = PROTOTYPE_DIR / "llm_inputs"
OUT_DIR = PROTOTYPE_DIR / "segmented_documents"

OUT_MANIFEST = OUT_DIR / "segmented_documents_manifest_test.csv"
OUT_AUDIT = OUT_DIR / "segmented_documents_audit_test.json"

OUT_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------
# Focus policy
# ---------------------------------------------------------------------

ALWAYS_INCLUDE_SECTION_TYPES = {
    "abstract",
    "results",
    "quantitative_results",
    "statistical_analysis",
    "exposure_assessment",
    "outcome_assessment",
    "tables",
}

OPTIONAL_SECTION_TYPES = {
    "methods",
}

LOW_PRIORITY_SECTION_TYPES = {
    "introduction",
    "discussion",
    "conclusion",
    "figures",
    "supplementary",
    "references",
    "other",
}

MAX_OPTIONAL_METHODS_CHARS = 5000
MAX_OTHER_CHARS = 6000
MAX_TABLE_CHARS = 12000
MAX_SUPPLEMENTARY_CHARS = 3000

# Un focus_text trop long est mauvais pour le LLM.
# On conserve cependant les chunks séparés si besoin.
MAX_FOCUS_SECTION_CHARS = 12000


SECTION_PATTERNS = {
    "abstract": [
        r"^abstract$",
        r"^background$",
        r"^objective$",
        r"^objectives$",
    ],
    "introduction": [
        r"^introduction$",
        r"^background and objectives$",
    ],
    "methods": [
        r"^methods$",
        r"^materials and methods$",
        r"^methods and materials$",
        r"^study design$",
        r"^study population$",
        r"^cohort identification$",
        r"^participants$",
        r"^subjects$",
        r"^data sources$",
        r"^selection of instrumental variants$",
        r"^two.*sample mendelian randomization.*$",
        r"^transcriptome.*wide association.*$",
    ],
    "exposure_assessment": [
        r"^exposure$",
        r"^exposure assessment$",
        r"^air pollution exposure$",
        r"^pollution exposure$",
        r"^environmental exposure$",
        r"^exposure measures$",
        r"^exposure metrics$",
    ],
    "outcome_assessment": [
        r"^outcome$",
        r"^outcome measure$",
        r"^outcome measures$",
        r"^health outcomes$",
        r"^case definition$",
        r"^disease ascertainment$",
    ],
    "statistical_analysis": [
        r"^statistical analysis$",
        r"^statistical methods$",
        r"^data analysis$",
        r"^modeling$",
        r"^regression models$",
    ],
    "quantitative_results": [
        r"^logistic regression$",
        r"^linear regression$",
        r"^cox regression$",
        r"^risk estimates$",
        r"^effect estimates$",
        r"^main analysis$",
        r"^main analyses$",
        r"^sensitivity analysis$",
        r"^sensitivity analyses$",
    ],
    "results": [
        r"^results$",
        r"^study results$",
        r"^findings$",
        r"^main results$",
    ],
    "discussion": [
        r"^discussion$",
        r"^interpretation$",
    ],
    "conclusion": [
        r"^conclusion$",
        r"^conclusions$",
    ],
    "tables": [
        r"^table\s+\d+\.?.*$",
        r"^table\s+[a-z0-9]+\.?.*$",
        r"^supplementary table.*$",
        r"^stable\s+\d+.*$",
        r"^s\s*table\s+\d+.*$",
    ],
    "figures": [
        r"^figure\s+\d+\.?.*$",
        r"^fig\.\s+\d+\.?.*$",
        r"^supplementary figure.*$",
        r"^sfigure.*$",
    ],
    "supplementary": [
        r"^supplementary material$",
        r"^supplemental material$",
        r"^supporting information$",
        r"^data s\d*$",
        r"^appendix$",
        r"^supplementary data$",
        r"^- \*\*columns\*\*:.*$",
    ],
    "references": [
        r"^references$",
        r"^bibliography$",
        r"^literature cited$",
    ],
}


POLLUTANT_PATTERNS = [
    r"\bPM\s*2\.?5\b",
    r"\bPM\s*10\b",
    r"\bPM\s*1\b",
    r"\bparticulate matter\b",
    r"\bfine particulate\b",
    r"\bultrafine\b",
    r"\bblack carbon\b",
    r"\bsoot\b",
    r"\bozone\b",
    r"\bO\s*3\b",
    r"\bnitrogen dioxide\b",
    r"\bNO\s*2\b",
    r"\bnitric oxide\b",
    r"\bNO\b",
    r"\bNOx\b",
    r"\bNO\s*x\b",
    r"\bcarbon monoxide\b",
    r"\bCO\b",
    r"\bsulfur dioxide\b",
    r"\bSO\s*2\b",
]

EFFECT_PATTERNS = [
    r"\bodds ratio\b",
    r"\bOR\b",
    r"\brisk ratio\b",
    r"\brelative risk\b",
    r"\bRR\b",
    r"\bhazard ratio\b",
    r"\bHR\b",
    r"\bincidence rate ratio\b",
    r"\bIRR\b",
    r"\bbeta\b",
    r"\bβ\b",
    r"\bcoefficient\b",
    r"\bconfidence interval\b",
    r"\bCI\b",
    r"\b95\s*%\b",
    r"\bp\s*[<=>]\s*0?\.\d+",
    r"\bp\s*=\s*[\d\.eE\-]+",
    r"\bµg/m",
    r"\bug/m",
    r"\bppb\b",
    r"\bppm\b",
    r"\bIQR\b",
]

ASSOCIATION_PATTERNS = [
    r"\bassociated with\b",
    r"\bincreased risk\b",
    r"\bdecreased risk\b",
    r"\belevated risk\b",
    r"\bprotective\b",
    r"\bstatistically significant\b",
    r"\bnot significant\b",
    r"\bper\s+\d+",
    r"\bincrease\b",
]


# ---------------------------------------------------------------------
# Basic utilities
# ---------------------------------------------------------------------

def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, obj: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(obj, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def safe_str(value: Any) -> str:
    if value is None:
        return ""
    value = str(value)
    if value.lower() == "nan":
        return ""
    return value.strip()


def normalize_space(text: str) -> str:
    lines = []
    for line in text.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines).strip()


def normalize_heading(text: str) -> str:
    text = safe_str(text)
    text = re.sub(r"^\d+(\.\d+)*\s+", "", text)
    text = re.sub(r"[:.\-–—]+$", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()


def classify_heading(heading: str) -> str:
    normalized = normalize_heading(heading)

    for section_type, patterns in SECTION_PATTERNS.items():
        for pattern in patterns:
            if re.match(pattern, normalized, flags=re.IGNORECASE):
                return section_type

    return "other"


def is_likely_heading(line: str) -> bool:
    line = safe_str(line)

    if not line:
        return False

    if len(line) > 140:
        return False

    normalized = normalize_heading(line)

    if classify_heading(line) != "other":
        return True

    if re.match(r"^(table|figure|fig\.)\s+[a-z0-9]+", normalized):
        return True

    if len(line.split()) <= 8 and not line.endswith("."):
        alpha_chars = re.sub(r"[^A-Za-z]", "", line)
        if alpha_chars and sum(c.isupper() for c in alpha_chars) >= 1:
            return True

    return False


def find_hits(text: str, patterns: list[str]) -> list[str]:
    hits = []
    for pattern in patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            hits.append(pattern)
    return hits


def find_keyword_hits(text: str) -> dict[str, list[str]]:
    return {
        "pollutant_hits": find_hits(text, POLLUTANT_PATTERNS),
        "effect_hits": find_hits(text, EFFECT_PATTERNS),
        "association_hits": find_hits(text, ASSOCIATION_PATTERNS),
    }


def has_pollutant_signal(text: str) -> bool:
    return bool(find_hits(text, POLLUTANT_PATTERNS))


def has_effect_signal(text: str) -> bool:
    return bool(find_hits(text, EFFECT_PATTERNS))


def has_association_signal(text: str) -> bool:
    return bool(find_hits(text, ASSOCIATION_PATTERNS))


def has_quantitative_signal(text: str) -> bool:
    """
    Signal fort pour extraction statistique:
    on veut au moins une mesure d'effet ou un IC/p-value.
    """
    return has_effect_signal(text)


def has_extraction_signal(text: str) -> bool:
    """
    Signal plus large:
    polluant + effet OU polluant + association.
    """
    return has_pollutant_signal(text) and (
        has_effect_signal(text) or has_association_signal(text)
    )


def looks_like_large_table_or_supplement(text: str) -> bool:
    """
    Détecte des gros blocs tabulaires/supplémentaires issus de Paperclip.

    Signaux typiques:
        - beaucoup de pipes Markdown;
        - beaucoup de <br>;
        - table of contents;
        - nombreux séparateurs.
    """
    if not text:
        return False

    pipe_count = text.count("|")
    br_count = text.lower().count("<br")
    table_of_contents = "table of contents" in text.lower()

    if len(text) > 20000 and (pipe_count > 100 or br_count > 100):
        return True

    if len(text) > 20000 and table_of_contents:
        return True

    return False


def truncate_text(text: str, max_chars: int) -> tuple[str, bool]:
    text = text.strip()

    if len(text) <= max_chars:
        return text, False

    return (
        text[:max_chars].rstrip()
        + "\n\n[TRUNCATED: section exceeded focus size limit]",
        True,
    )


def split_document_markers(document_text: str) -> dict[str, str]:
    markers = {
        "title": "",
        "abstract": "",
        "full_text": "",
    }

    pattern = re.compile(
        r"^###\s+(TITLE|PUBMED ABSTRACT|PAPERCLIP FULL TEXT)\s*$",
        flags=re.MULTILINE,
    )

    matches = list(pattern.finditer(document_text))

    if not matches:
        markers["full_text"] = document_text.strip()
        return markers

    for i, match in enumerate(matches):
        label = match.group(1)
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(document_text)
        content = document_text[start:end].strip()

        if label == "TITLE":
            markers["title"] = content
        elif label == "PUBMED ABSTRACT":
            markers["abstract"] = content
        elif label == "PAPERCLIP FULL TEXT":
            markers["full_text"] = content

    return markers


# ---------------------------------------------------------------------
# Segmentation
# ---------------------------------------------------------------------

def segment_full_text(full_text: str) -> list[dict[str, Any]]:
    full_text = normalize_space(full_text)

    if not full_text:
        return []

    lines = full_text.splitlines()

    sections = []
    current_heading = "full_text_start"
    current_type = "other"
    current_lines = []
    current_start_line = 1

    def flush(end_line: int) -> None:
        nonlocal current_heading, current_type, current_lines, current_start_line

        text = "\n".join(current_lines).strip()

        if text:
            sections.append(
                {
                    "section_id": f"s{len(sections) + 1:03d}",
                    "heading": current_heading,
                    "section_type": current_type,
                    "start_line": current_start_line,
                    "end_line": end_line,
                    "text": text,
                    "chars": len(text),
                    "is_large_table_or_supplement": looks_like_large_table_or_supplement(text),
                }
            )

    for idx, line in enumerate(lines, start=1):
        if is_likely_heading(line):
            flush(idx - 1)
            current_heading = line.strip()
            current_type = classify_heading(line)
            current_lines = []
            current_start_line = idx + 1
        else:
            current_lines.append(line)

    flush(len(lines))

    return sections


def remove_references(sections: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
    cleaned = []
    removed = False

    for section in sections:
        if section["section_type"] == "references":
            removed = True
            break
        cleaned.append(section)

    return cleaned, removed


def should_include_focus_section(section: dict[str, Any]) -> tuple[bool, str, int]:
    """
    Décide si une section doit aller dans focus_sections.

    Retour:
        include, reason, max_chars
    """
    section_type = section.get("section_type", "other")
    heading = section.get("heading", "")
    text = section.get("text", "")
    chars = len(text)

    normalized_heading = normalize_heading(heading)

    if section_type == "references":
        return False, "exclude_references", 0

    if section_type in {"figures"}:
        return False, "exclude_figures", 0

    if section_type in {"introduction"}:
        return False, "exclude_introduction", 0

    if section_type in {"discussion", "conclusion"}:
        # Le résumé interprétatif peut créer des doublons ou du bruit.
        # On ne garde que si très court et avec signal quantitatif fort.
        if chars <= 3000 and has_extraction_signal(text):
            return True, "include_short_discussion_with_signal", 3000
        return False, f"exclude_{section_type}", 0

    if section.get("is_large_table_or_supplement"):
        return False, "exclude_large_table_or_supplement", 0

    if section_type == "supplementary":
        if chars <= MAX_SUPPLEMENTARY_CHARS and has_extraction_signal(text):
            return True, "include_short_supplementary_with_signal", MAX_SUPPLEMENTARY_CHARS
        return False, "exclude_supplementary", 0

    if section_type in ALWAYS_INCLUDE_SECTION_TYPES:
        if section_type == "tables":
            return True, "include_core_table", MAX_TABLE_CHARS
        return True, f"include_core_{section_type}", MAX_FOCUS_SECTION_CHARS

    if section_type in OPTIONAL_SECTION_TYPES:
        if chars <= MAX_OPTIONAL_METHODS_CHARS and has_pollutant_signal(text):
            return True, "include_methods_with_pollutant_signal", MAX_OPTIONAL_METHODS_CHARS
        return False, "exclude_methods_without_needed_signal_or_too_long", 0

    # Cas other : on est strict.
    if section_type == "other":
        if re.search(r"logistic regression|risk estimates|effect estimates", normalized_heading):
            return True, "include_other_quantitative_heading", MAX_FOCUS_SECTION_CHARS

        if chars <= MAX_OTHER_CHARS and has_extraction_signal(text):
            return True, "include_short_other_with_extraction_signal", MAX_OTHER_CHARS

        return False, "exclude_other", 0

    return False, "exclude_default", 0


def build_focus_sections(
    abstract: str,
    sections: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    focus = []
    diagnostics = {
        "included": 0,
        "excluded": 0,
        "truncated": 0,
        "excluded_by_reason": {},
        "included_by_reason": {},
    }

    def bump(bucket: str, reason: str) -> None:
        diagnostics[bucket][reason] = diagnostics[bucket].get(reason, 0) + 1

    if abstract:
        keyword_hits = find_keyword_hits(abstract)
        focus.append(
            {
                "focus_id": "f001",
                "source": "pubmed_abstract",
                "section_type": "abstract",
                "heading": "PUBMED ABSTRACT",
                "text": abstract,
                "chars": len(abstract),
                "original_chars": len(abstract),
                "truncated": False,
                "include_reason": "include_pubmed_abstract",
                "keyword_hits": keyword_hits,
            }
        )
        diagnostics["included"] += 1
        bump("included_by_reason", "include_pubmed_abstract")

    for section in sections:
        include, reason, max_chars = should_include_focus_section(section)

        if not include:
            diagnostics["excluded"] += 1
            bump("excluded_by_reason", reason)
            continue

        text = section["text"]
        original_chars = len(text)
        text, truncated = truncate_text(text, max_chars=max_chars)

        if truncated:
            diagnostics["truncated"] += 1

        keyword_hits = find_keyword_hits(text)

        focus.append(
            {
                "focus_id": f"f{len(focus) + 1:03d}",
                "source": "paperclip_full_text",
                "section_id": section["section_id"],
                "section_type": section["section_type"],
                "heading": section["heading"],
                "text": text,
                "chars": len(text),
                "original_chars": original_chars,
                "truncated": truncated,
                "include_reason": reason,
                "keyword_hits": keyword_hits,
            }
        )

        diagnostics["included"] += 1
        bump("included_by_reason", reason)

    return focus, diagnostics


def chunk_text(text: str, max_chars: int = 8000, overlap_chars: int = 500) -> list[dict[str, Any]]:
    text = text.strip()

    if not text:
        return []

    chunks = []
    start = 0
    n = len(text)

    while start < n:
        end = min(start + max_chars, n)
        chunk = text[start:end].strip()

        if chunk:
            chunks.append(
                {
                    "chunk_id": f"c{len(chunks) + 1:03d}",
                    "start_char": start,
                    "end_char": end,
                    "chars": len(chunk),
                    "text": chunk,
                }
            )

        if end >= n:
            break

        start = max(0, end - overlap_chars)

    return chunks


def build_focus_text(focus_sections: list[dict[str, Any]]) -> str:
    parts = []

    for item in focus_sections:
        heading = item.get("heading", "")
        section_type = item.get("section_type", "")
        reason = item.get("include_reason", "")
        text = item.get("text", "")

        parts.append(
            f"### {section_type.upper()} — {heading}\n"
            f"[include_reason: {reason}]\n"
            f"{text}"
        )

    return "\n\n".join(parts).strip()


def segment_llm_input(payload: dict[str, Any]) -> dict[str, Any]:
    pmid = safe_str(payload.get("pmid"))
    document_text = safe_str(payload.get("document_text"))

    markers = split_document_markers(document_text)

    title = markers["title"] or safe_str(payload.get("pubmed", {}).get("title"))
    abstract = markers["abstract"] or safe_str(payload.get("pubmed", {}).get("abstract"))
    full_text = markers["full_text"]

    sections = segment_full_text(full_text)
    sections_no_refs, references_removed = remove_references(sections)

    focus_sections, focus_diagnostics = build_focus_sections(
        abstract=abstract,
        sections=sections_no_refs,
    )

    focus_text = build_focus_text(focus_sections)

    focus_chunks = chunk_text(
        focus_text,
        max_chars=8000,
        overlap_chars=500,
    )

    full_text_chunks = chunk_text(
        full_text,
        max_chars=12000,
        overlap_chars=800,
    )

    return {
        "pmid": pmid,
        "created_at": datetime.now().isoformat(timespec="seconds"),

        "source_input": {
            "text_source": payload.get("text_source"),
            "has_abstract": bool(abstract),
            "has_full_text": bool(full_text),
        },

        "ctd_context": payload.get("ctd_context", {}),
        "pubmed": payload.get("pubmed", {}),
        "paperclip": payload.get("paperclip", {}),

        "document_parts": {
            "title": title,
            "abstract": abstract,
            "full_text_available": bool(full_text),
            "title_chars": len(title),
            "abstract_chars": len(abstract),
            "full_text_chars": len(full_text),
        },

        "sections": sections_no_refs,

        "focus_sections": focus_sections,
        "focus_text": focus_text,
        "focus_chunks": focus_chunks,

        "full_text_chunks": full_text_chunks,

        "segmentation_stats": {
            "sections_detected_before_reference_removal": len(sections),
            "sections_detected": len(sections_no_refs),
            "references_removed": references_removed,
            "focus_sections": len(focus_sections),
            "focus_chunks": len(focus_chunks),
            "full_text_chunks": len(full_text_chunks),
            "focus_text_chars": len(focus_text),
            "focus_selection_diagnostics": focus_diagnostics,
        },

        "notes": {
            "segmentation_method": "heuristic_heading_detection_v2",
            "native_paperclip_sections_used": False,
            "native_paperclip_tables_used": False,
            "large_supplementary_blocks_policy": "exclude_from_focus",
            "intended_next_step": "LangGraph multi-agent extraction",
        },
    }


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------

def clean_outputs(fresh: bool) -> None:
    if not fresh:
        return

    for path in OUT_DIR.glob("*_segmented.json"):
        path.unlink()

    for path in [OUT_MANIFEST, OUT_AUDIT]:
        if path.exists():
            path.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Segment prototype LLM input documents."
    )

    parser.add_argument(
        "--input-dir",
        default=str(INPUT_DIR),
        help="Directory containing PMID JSON files from step 04.",
    )

    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Delete previous segmentation outputs before running.",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional limit on number of documents to segment.",
    )

    args = parser.parse_args()

    input_dir = Path(args.input_dir)

    if not input_dir.exists():
        raise FileNotFoundError(f"Missing input directory: {input_dir}")

    clean_outputs(args.fresh)

    input_files = sorted(
        path for path in input_dir.glob("*.json")
        if re.match(r"^\d+\.json$", path.name)
    )

    if args.limit is not None:
        input_files = input_files[: args.limit]

    if not input_files:
        raise ValueError(f"No PMID JSON files found in {input_dir}")

    manifest_rows = []
    segmented_payloads = []

    for path in input_files:
        payload = read_json(path)
        segmented = segment_llm_input(payload)

        pmid = segmented["pmid"]
        out_path = OUT_DIR / f"{pmid}_segmented.json"

        write_json(out_path, segmented)
        segmented_payloads.append(segmented)

        diagnostics = segmented["segmentation_stats"]["focus_selection_diagnostics"]

        manifest_rows.append(
            {
                "pmid": pmid,
                "text_source": segmented["source_input"]["text_source"],
                "has_abstract": segmented["source_input"]["has_abstract"],
                "has_full_text": segmented["source_input"]["has_full_text"],

                "source_pollutant": segmented["ctd_context"].get("source_pollutant", ""),
                "stressor_agent_primary": segmented["ctd_context"].get("stressor_agent_primary", ""),
                "outcome_ctd_primary": segmented["ctd_context"].get("outcome_ctd_primary", ""),

                "title_chars": segmented["document_parts"]["title_chars"],
                "abstract_chars": segmented["document_parts"]["abstract_chars"],
                "full_text_chars": segmented["document_parts"]["full_text_chars"],

                "sections_detected": segmented["segmentation_stats"]["sections_detected"],
                "references_removed": segmented["segmentation_stats"]["references_removed"],
                "focus_sections": segmented["segmentation_stats"]["focus_sections"],
                "focus_chunks": segmented["segmentation_stats"]["focus_chunks"],
                "full_text_chunks": segmented["segmentation_stats"]["full_text_chunks"],
                "focus_text_chars": segmented["segmentation_stats"]["focus_text_chars"],

                "focus_included": diagnostics["included"],
                "focus_excluded": diagnostics["excluded"],
                "focus_truncated": diagnostics["truncated"],

                "segmented_path": str(out_path),
            }
        )

    manifest_df = pd.DataFrame(manifest_rows)
    manifest_df.to_csv(OUT_MANIFEST, index=False)

    audit = {
        "run_date": datetime.now().isoformat(timespec="seconds"),
        "input_dir": str(input_dir),
        "n_documents": len(segmented_payloads),

        "with_full_text": int(sum(p["source_input"]["has_full_text"] for p in segmented_payloads)),
        "abstract_only": int(sum(not p["source_input"]["has_full_text"] for p in segmented_payloads)),

        "total_sections_detected": int(sum(p["segmentation_stats"]["sections_detected"] for p in segmented_payloads)),
        "total_focus_sections": int(sum(p["segmentation_stats"]["focus_sections"] for p in segmented_payloads)),
        "total_focus_chunks": int(sum(p["segmentation_stats"]["focus_chunks"] for p in segmented_payloads)),

        "min_focus_text_chars": int(min(p["segmentation_stats"]["focus_text_chars"] for p in segmented_payloads)),
        "max_focus_text_chars": int(max(p["segmentation_stats"]["focus_text_chars"] for p in segmented_payloads)),
        "avg_focus_text_chars": (
            sum(p["segmentation_stats"]["focus_text_chars"] for p in segmented_payloads)
            / max(1, len(segmented_payloads))
        ),

        "total_focus_excluded_sections": int(
            sum(
                p["segmentation_stats"]["focus_selection_diagnostics"]["excluded"]
                for p in segmented_payloads
            )
        ),
        "total_focus_truncated_sections": int(
            sum(
                p["segmentation_stats"]["focus_selection_diagnostics"]["truncated"]
                for p in segmented_payloads
            )
        ),

        "outputs": {
            "segmented_documents_dir": str(OUT_DIR),
            "manifest": str(OUT_MANIFEST),
            "audit": str(OUT_AUDIT),
        },

        "next_step": (
            "Inspect PMID 20123607 and 38970158 again. "
            "Then test pollutant_extractor on 20123607."
        ),
    }

    write_json(OUT_AUDIT, audit)

    print("=" * 80)
    print("DOCUMENT SEGMENTATION COMPLETE — V2")
    print("=" * 80)
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    print("=" * 80)
    print("Per-document summary:")
    print(manifest_df.to_string(index=False))
    print("=" * 80)


if __name__ == "__main__":
    main()