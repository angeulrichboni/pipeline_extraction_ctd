"""Segment canonical document inputs into focused sections and chunks."""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from src.io.csv_io import write_csv_rows
from src.io.json_io import write_json


# Configuration

DEFAULT_CHUNK_SIZE = 8000
DEFAULT_CHUNK_OVERLAP = 500

FOCUS_SECTION_KEYWORDS = [
    # General scientific structure
    "abstract",
    "background",
    "objective",
    "objectives",
    "methods",
    "materials and methods",
    "study population",
    "exposure assessment",
    "outcome assessment",
    "statistical analysis",
    "results",
    "discussion",
    "conclusion",
    "conclusions",

    # Exposure / pollutant
    "exposure",
    "air pollution",
    "air pollutant",
    "ambient air",
    "particulate matter",
    "pm2.5",
    "pm10",
    "pm1",
    "ultrafine",
    "nitric oxide",
    "nitrogen dioxide",
    "nox",
    "ozone",
    "o3",
    "carbon monoxide",
    "sulfur dioxide",
    "sulphur dioxide",
    "black carbon",
    "woodsmoke",
    "traffic",
    "road",
    "h2s",
    "hydrogen sulfide",

    # Outcome / endpoint
    "outcome",
    "endpoint",
    "disease",
    "diagnosis",
    "asthma",
    "amyotrophic lateral sclerosis",
    "als",
    "alzheimer",
    "dementia",
    "acute kidney injury",
    "angina",
    "cancer",
    "adenocarcinoma",
    "spontaneous abortion",
    "pregnancy loss",

    # Effect measures / statistics
    "odds ratio",
    "relative risk",
    "hazard ratio",
    "incidence rate ratio",
    "95% ci",
    "confidence interval",
    "p-value",
    "p value",
    "logistic regression",
    "poisson",
    "cox",
    "mendelian randomization",
    "ivw",
    "mr-presso",
    "mr egger",
    "weighted median",
]

COMMON_SECTION_TITLES = {
    "abstract",
    "introduction",
    "background",
    "objective",
    "objectives",
    "methods",
    "materials and methods",
    "study population",
    "exposure assessment",
    "outcome assessment",
    "statistical analysis",
    "results",
    "discussion",
    "conclusion",
    "conclusions",
    "references",
    "reference",
    "acknowledgments",
    "acknowledgements",
    "supplementary material",
}


# Generic helpers

def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def safe_str(value: Any) -> str:
    if value is None:
        return ""

    text = str(value).strip()

    if text.lower() in {"nan", "none", "null"}:
        return ""

    return text


def safe_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value

    return safe_str(value).lower() in {"true", "1", "yes", "y"}


def value_is_true(value: Any) -> bool:
    if isinstance(value, bool):
        return value

    text = safe_str(value).lower()

    return text in {"true", "1", "yes", "y"}


def normalize_text(value: Any) -> str:
    text = safe_str(value).lower()
    text = text.replace("₂", "2").replace("₃", "3").replace("ₓ", "x")
    text = text.replace("μ", "µ")
    text = text.replace("–", "-").replace("—", "-")
    text = text.replace("_", " ")
    text = " ".join(text.split())
    return text


def strip_paperclip_line_prefix(line: str) -> str:
    """Strip Paperclip L-number prefixes."""
    return re.sub(r"^\s*L\d+\s*:\s*", "", line).strip()


def clean_text(text: str) -> str:
    if not text:
        return ""

    lines = []

    for raw_line in text.splitlines():
        line = strip_paperclip_line_prefix(raw_line)
        line = line.replace("\u00a0", " ")
        line = " ".join(line.split())

        if line:
            lines.append(line)
        else:
            lines.append("")

    cleaned = "\n".join(lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

    return cleaned.strip()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []

    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()

            if not line:
                continue

            rows.append(json.loads(line))

    return rows


def read_text_file_or_empty(path_value: Any) -> str:
    path_text = safe_str(path_value)

    if not path_text:
        return ""

    path = Path(path_text)

    if not path.exists():
        return ""

    return path.read_text(encoding="utf-8", errors="ignore")


def extract_tagged_block(document_text: str, tag: str) -> str:
    """Extract a known tagged block from document_text."""
    if not document_text:
        return ""

    tag_pattern = re.escape(tag).replace(r"\ ", r"\s+")

    patterns = [
        # [TAG]
        (
            r"\[\s*" + tag_pattern + r"\s*\]\s*"
            r"(.*?)(?=\n\s*\[\s*[A-Z0-9 _\-/]+\s*\]\s*|\Z)"
        ),

        # ### TAG
        (
            r"(?:^|\n)\s*#{1,6}\s*" + tag_pattern + r"\s*"
            r"(.*?)(?=\n\s*#{1,6}\s*[A-Z0-9 _\-/]+\s*|\Z)"
        ),

        # TAG:
        (
            r"(?:^|\n)\s*" + tag_pattern + r"\s*:\s*"
            r"(.*?)(?=\n\s*[A-Z0-9 _\-/]{3,80}\s*:\s*|\Z)"
        ),
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            document_text,
            flags=re.IGNORECASE | re.DOTALL,
        )

        if match:
            return match.group(1).strip()

    return ""


def infer_title_abstract_fulltext_from_document_text(
    document_text: str,
) -> dict[str, str]:
    """
    Recover title, abstract and full text when llm_inputs stores everything
    inside document_text instead of separate fields.
    """
    title = (
        extract_tagged_block(document_text, "TITLE")
        or extract_tagged_block(document_text, "ARTICLE TITLE")
        or extract_tagged_block(document_text, "PUBMED TITLE")
    )

    abstract = (
        extract_tagged_block(document_text, "PUBMED ABSTRACT")
        or extract_tagged_block(document_text, "ABSTRACT")
    )

    full_text = (
        extract_tagged_block(document_text, "FULL TEXT")
        or extract_tagged_block(document_text, "PAPERCLIP FULL TEXT")
        or extract_tagged_block(document_text, "FULL_TEXT")
    )

    return {
        "title": title,
        "abstract": abstract,
        "full_text": full_text,
    }


# Input field extraction

def get_nested_raw(row: dict[str, Any], path: str) -> Any:
    """Read a nested value using dot notation."""
    current: Any = row

    for part in path.split("."):
        if not isinstance(current, dict):
            return None

        current = current.get(part)

    return current


def get_nested_value(row: dict[str, Any], path: str) -> str:
    """
    Read nested value using dot notation and return it as a clean string
    only when the value is string-like.
    """
    value = get_nested_raw(row, path)

    if isinstance(value, str) and value.strip():
        return value.strip()

    return ""


def get_first_value(row: dict[str, Any], keys: list[str]) -> str:
    for key in keys:
        if "." in key:
            value = get_nested_value(row, key)
        else:
            raw_value = row.get(key)

            if isinstance(raw_value, str):
                value = raw_value.strip()
            else:
                value = ""

        if value:
            return value

    return ""


def extract_document_fields(row: dict[str, Any]) -> dict[str, Any]:
    pmid = safe_str(row.get("pmid") or row.get("PMID"))

    document_text = get_first_value(
        row,
        [
            "document_text",
            "text",
            "content",
        ],
    )

    text_source = safe_str(row.get("text_source"))

    paperclip_has_full_text = value_is_true(
        get_nested_raw(row, "paperclip.has_full_text")
    )

    title = get_first_value(
        row,
        [
            "title",
            "article_title",
            "document_title",
            "pubmed_title",
            "pubmed.title",
            "pubmed.article_title",
            "metadata.title",
            "metadata.article_title",
        ],
    )

    abstract = get_first_value(
        row,
        [
            "abstract",
            "pubmed_abstract",
            "abstract_text",
            "pubmed_abstract_text",
            "pubmed.abstract",
            "pubmed.abstract_text",
            "metadata.abstract",
            "metadata.pubmed_abstract",
            "metadata.abstract_text",
        ],
    )

    full_text = get_first_value(
        row,
        [
            "full_text",
            "paperclip_full_text",
            "fulltext",
            "full_text_text",
            "document_full_text",
            "paperclip.full_text",
            "paperclip.text",
            "paperclip.content",
            "metadata.full_text",
            "metadata.paperclip_full_text",
        ],
    )

    tagged = infer_title_abstract_fulltext_from_document_text(document_text)

    if not title:
        title = tagged["title"]

    if not abstract:
        abstract = tagged["abstract"]

    if not full_text:
        full_text = tagged["full_text"]

    if not full_text and paperclip_has_full_text:
        full_text = read_text_file_or_empty(
            row.get("full_text_path")
            or row.get("paperclip_full_text_path")
            or row.get("paperclip_path")
            or get_nested_value(row, "paperclip.full_text_path")
        )

    if not text_source:
        if full_text and paperclip_has_full_text:
            text_source = "full_text"
        else:
            text_source = "abstract_only"

    # Hard rule: abstract_only documents must not be promoted to full_text.
    if text_source == "abstract_only":
        full_text = ""

    if text_source == "abstract_only" and not abstract and document_text:
        abstract = tagged["abstract"] or document_text

    if text_source == "full_text" and not full_text and document_text:
        full_text = tagged["full_text"] or document_text

    if not document_text:
        blocks = []

        if title:
            blocks.append(f"### TITLE\n{title}")

        if abstract:
            blocks.append(f"### PUBMED ABSTRACT\n{abstract}")

        if full_text:
            blocks.append(f"### FULL TEXT\n{full_text}")

        document_text = "\n\n".join(blocks).strip()

    canonical_blocks = []

    if title:
        canonical_blocks.append(f"### TITLE\n{title}")

    if abstract:
        canonical_blocks.append(f"### PUBMED ABSTRACT\n{abstract}")

    if full_text:
        canonical_blocks.append(f"### FULL TEXT\n{full_text}")

    if canonical_blocks:
        document_text = "\n\n".join(canonical_blocks).strip()

    return {
        "pmid": pmid,
        "title": clean_text(title),
        "abstract": clean_text(abstract),
        "full_text": clean_text(full_text),
        "document_text": clean_text(document_text),
        "text_source": text_source,
        "source_pollutant": (
            safe_str(row.get("source_pollutant"))
            or get_nested_value(row, "ctd_context.source_pollutant")
        ),
        "stressor_agent_primary": (
            safe_str(row.get("stressor_agent_primary"))
            or get_nested_value(row, "ctd_context.stressor_agent_primary")
            or get_nested_value(row, "ctd_context.stressor_agent")
        ),
        "outcome_ctd_primary": (
            safe_str(row.get("outcome_ctd_primary"))
            or get_nested_value(row, "ctd_context.outcome_ctd_primary")
            or get_nested_value(row, "ctd_context.outcome_ctd")
        ),
        "paperclip_has_full_text": paperclip_has_full_text,
        "raw_input": row,
    }


# Reference removal

def find_references_start(lines: list[str]) -> int | None:
    for idx, line in enumerate(lines):
        normalized = normalize_text(line)

        if normalized in {"references", "reference"}:
            return idx

        if normalized.startswith("references "):
            return idx

    return None


def remove_references_section(text: str) -> tuple[str, bool]:
    lines = text.splitlines()
    start = find_references_start(lines)

    if start is None:
        return text, False

    kept = lines[:start]
    return "\n".join(kept).strip(), True


# Section detection

def is_probable_section_heading(line: str) -> bool:
    line = line.strip()

    if not line:
        return False

    normalized = normalize_text(line)

    if normalized in COMMON_SECTION_TITLES:
        return True

    if len(line) > 120:
        return False

    if line.endswith("."):
        return False

    if re.match(r"^\d+(\.\d+)*\s+[A-Z]", line):
        return True

    if re.match(r"^[A-Z][A-Za-z\s,\-/&]{2,80}$", line):
        words = line.split()

        if len(words) <= 8:
            return True

    return False


def split_into_sections(text: str) -> list[dict[str, Any]]:
    """
    Lightweight section splitter.

    If no headings are found, the whole text becomes one section.
    """
    lines = text.splitlines()

    sections = []
    current_title = "Document"
    current_lines = []

    heading_found = False

    for line in lines:
        if is_probable_section_heading(line):
            heading_found = True

            if current_lines:
                sections.append(
                    {
                        "section_title": current_title,
                        "text": "\n".join(current_lines).strip(),
                    }
                )

            current_title = line.strip()
            current_lines = []
            continue

        current_lines.append(line)

    if current_lines:
        sections.append(
            {
                "section_title": current_title,
                "text": "\n".join(current_lines).strip(),
            }
        )

    sections = [
        section
        for section in sections
        if safe_str(section.get("text"))
    ]

    if not heading_found or not sections:
        return [
            {
                "section_title": "Document",
                "text": text.strip(),
            }
        ]

    return sections


# Focus scoring and chunking

def section_focus_score(section_title: str, section_text: str) -> int:
    title = normalize_text(section_title)
    text = normalize_text(section_text)

    score = 0

    for keyword in FOCUS_SECTION_KEYWORDS:
        key = normalize_text(keyword)

        if key and key in title:
            score += 5

        if key and key in text:
            score += 1

    strong_patterns = [
        r"\bor\s*[:=]?\s*\d+(\.\d+)?",
        r"\brr\s*[:=]?\s*\d+(\.\d+)?",
        r"\bhr\s*[:=]?\s*\d+(\.\d+)?",
        r"\birr\s*[:=]?\s*\d+(\.\d+)?",
        r"\b95%?\s*ci\b",
        r"\bp\s*[<=>]\s*0?\.\d+",
        r"\bp\s*[<=>]\s*\d+(\.\d+)?e-\d+",
    ]

    for pattern in strong_patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            score += 10

    if title in {"references", "reference"}:
        score -= 100

    return score


def split_sentences(text: str) -> list[str]:
    normalized = text.replace("\n", " ")
    normalized = " ".join(normalized.split())

    if not normalized:
        return []

    return [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", normalized)
        if sentence.strip()
    ]


def chunk_text(
    text: str,
    max_chars: int = DEFAULT_CHUNK_SIZE,
    overlap_chars: int = DEFAULT_CHUNK_OVERLAP,
) -> list[str]:
    text = text.strip()

    if not text:
        return []

    if len(text) <= max_chars:
        return [text]

    sentences = split_sentences(text)

    chunks = []
    current = ""

    for sentence in sentences:
        if not current:
            current = sentence
            continue

        if len(current) + 1 + len(sentence) <= max_chars:
            current = f"{current} {sentence}"
            continue

        chunks.append(current.strip())

        if overlap_chars > 0:
            overlap = current[-overlap_chars:]
            current = f"{overlap} {sentence}"
        else:
            current = sentence

    if current.strip():
        chunks.append(current.strip())

    return chunks


def build_focus_sections(
    sections: list[dict[str, Any]],
    min_score: int = 1,
) -> list[dict[str, Any]]:
    focus_sections = []

    for index, section in enumerate(sections, start=1):
        title = safe_str(section.get("section_title")) or "Document"
        text = safe_str(section.get("text"))

        score = section_focus_score(title, text)

        if score >= min_score:
            focus_sections.append(
                {
                    "section_index": index,
                    "section_title": title,
                    "focus_score": score,
                    "text": text,
                    "text_chars": len(text),
                }
            )

    return focus_sections


def build_chunks_from_sections(
    sections: list[dict[str, Any]],
    max_chars: int = DEFAULT_CHUNK_SIZE,
    overlap_chars: int = DEFAULT_CHUNK_OVERLAP,
) -> list[dict[str, Any]]:
    chunks = []

    chunk_index = 0

    for section in sections:
        section_title = safe_str(section.get("section_title")) or "Document"
        section_index = section.get("section_index")
        section_text = safe_str(section.get("text"))

        for chunk_text_value in chunk_text(
            section_text,
            max_chars=max_chars,
            overlap_chars=overlap_chars,
        ):
            chunk_index += 1

            chunks.append(
                {
                    "chunk_index": chunk_index,
                    "section_index": section_index,
                    "section_title": section_title,
                    "chunk_text": chunk_text_value,
                    "text": chunk_text_value,
                    "chunk_chars": len(chunk_text_value),
                    "source_type": "segmented_document",
                }
            )

    return chunks


# Main segmentation

def segment_document(
    row: dict[str, Any],
    output_dir: Path,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    remove_references: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    fields = extract_document_fields(row)

    pmid = fields["pmid"]

    if not pmid:
        raise ValueError("Missing PMID in LLM input row.")

    title = fields["title"]
    abstract = fields["abstract"]
    full_text = fields["full_text"]
    text_source = fields["text_source"]

    has_abstract = bool(abstract)
    has_full_text = bool(full_text) and text_source == "full_text"

    base_text = fields["document_text"]

    references_removed = False

    if remove_references:
        base_text, references_removed = remove_references_section(base_text)
        full_text, _ = remove_references_section(full_text)

    if has_full_text:
        section_source_text = full_text or base_text
        sections = split_into_sections(section_source_text)
    else:
        sections = []

    if has_full_text:
        focus_sections = build_focus_sections(sections)
    else:
        abstract_text = abstract or base_text

        focus_sections = [
            {
                "section_index": 1,
                "section_title": "PUBMED ABSTRACT",
                "focus_score": 999,
                "text": abstract_text,
                "text_chars": len(abstract_text),
            }
        ]

    if not focus_sections and has_full_text:
        focus_sections = [
            {
                "section_index": index,
                "section_title": section.get("section_title", "Document"),
                "focus_score": section_focus_score(
                    section.get("section_title", "Document"),
                    section.get("text", ""),
                ),
                "text": section.get("text", ""),
                "text_chars": len(section.get("text", "")),
            }
            for index, section in enumerate(sections, start=1)
        ]

    full_text_chunks = []

    if has_full_text:
        all_sections_with_index = [
            {
                "section_index": index,
                "section_title": section.get("section_title", "Document"),
                "text": section.get("text", ""),
            }
            for index, section in enumerate(sections, start=1)
        ]

        full_text_chunks = build_chunks_from_sections(
            all_sections_with_index,
            max_chars=chunk_size,
            overlap_chars=chunk_overlap,
        )

    abstract_section = []

    # Add PubMed abstract in addition to full-text focus sections.
    # For abstract-only papers, focus_sections already contains the abstract.
    if has_full_text and has_abstract:
        abstract_section = [
            {
                "section_index": 0,
                "section_title": "PUBMED ABSTRACT",
                "focus_score": 999,
                "text": abstract,
                "text_chars": len(abstract),
            }
        ]

    focus_sections_with_abstract = abstract_section + focus_sections

    focus_chunks = build_chunks_from_sections(
        focus_sections_with_abstract,
        max_chars=chunk_size,
        overlap_chars=chunk_overlap,
    )

    focus_text = "\n\n".join(
        [
            f"[SECTION: {section['section_title']}]\n{section['text']}"
            for section in focus_sections_with_abstract
        ]
    ).strip()

    segmented_payload = {
        "pmid": pmid,
        "created_at": now_iso(),
        "title": title,
        "abstract": abstract,
        "full_text": full_text,
        "document_text": base_text,
        "focus_text": focus_text,
        "text_source": text_source,
        "has_abstract": has_abstract,
        "has_full_text": has_full_text,

        "source_pollutant": fields["source_pollutant"],
        "stressor_agent_primary": fields["stressor_agent_primary"],
        "outcome_ctd_primary": fields["outcome_ctd_primary"],

        "sections": [
            {
                "section_index": index,
                "section_title": section.get("section_title", "Document"),
                "text": section.get("text", ""),
                "text_chars": len(section.get("text", "")),
            }
            for index, section in enumerate(sections, start=1)
        ],
        "focus_sections": focus_sections_with_abstract,
        "focus_chunks": focus_chunks,
        "full_text_chunks": full_text_chunks,

        "metadata": {
            "references_removed": references_removed,
            "chunk_size": chunk_size,
            "chunk_overlap": chunk_overlap,
            "sections_detected": len(sections),
            "focus_sections": len(focus_sections_with_abstract),
            "focus_chunks": len(focus_chunks),
            "full_text_chunks": len(full_text_chunks),
            "title_chars": len(title),
            "abstract_chars": len(abstract),
            "full_text_chars": len(full_text),
            "document_text_chars": len(base_text),
            "focus_text_chars": len(focus_text),
        },
    }

    output_path = output_dir / f"{pmid}_segmented.json"
    write_json(output_path, segmented_payload)

    summary = {
        "pmid": pmid,
        "text_source": text_source,
        "has_abstract": has_abstract,
        "has_full_text": has_full_text,
        "source_pollutant": fields["source_pollutant"],
        "stressor_agent_primary": fields["stressor_agent_primary"],
        "outcome_ctd_primary": fields["outcome_ctd_primary"],
        "title_chars": len(title),
        "abstract_chars": len(abstract),
        "full_text_chars": len(full_text),
        "sections_detected": len(sections),
        "references_removed": references_removed,
        "focus_sections": len(focus_sections_with_abstract),
        "focus_chunks": len(focus_chunks),
        "full_text_chunks": len(full_text_chunks),
        "focus_text_chars": len(focus_text),
        "segmented_path": str(output_path),
    }

    return segmented_payload, summary


def run_document_segmentation(
    input_jsonl: Path,
    output_dir: Path,
    manifest_csv: Path,
    audit_json: Path,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    remove_references: bool = True,
) -> dict[str, Any]:
    rows = read_jsonl(input_jsonl)

    output_dir.mkdir(parents=True, exist_ok=True)

    summaries = []
    errors = []

    for row in rows:
        pmid = safe_str(row.get("pmid") or row.get("PMID"))

        try:
            _, summary = segment_document(
                row=row,
                output_dir=output_dir,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                remove_references=remove_references,
            )
            summaries.append(summary)

        except Exception as exc:
            errors.append(
                {
                    "pmid": pmid,
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                }
            )

    write_csv_rows(manifest_csv, summaries)

    n_documents = len(summaries)
    with_full_text = sum(1 for row in summaries if safe_bool(row["has_full_text"]))
    abstract_only = sum(1 for row in summaries if not safe_bool(row["has_full_text"]))

    total_sections_detected = sum(int(row["sections_detected"]) for row in summaries)
    total_focus_sections = sum(int(row["focus_sections"]) for row in summaries)
    total_focus_chunks = sum(int(row["focus_chunks"]) for row in summaries)

    focus_text_values = [
        int(row["focus_text_chars"])
        for row in summaries
        if int(row["focus_text_chars"]) > 0
    ]

    text_source_distribution = dict(
        Counter(row["text_source"] for row in summaries)
    )

    audit = {
        "run_date": now_iso(),
        "input_jsonl": str(input_jsonl),
        "n_input_rows": len(rows),
        "n_documents": n_documents,
        "with_full_text": with_full_text,
        "abstract_only": abstract_only,
        "text_source_distribution": text_source_distribution,
        "total_sections_detected": total_sections_detected,
        "total_focus_sections": total_focus_sections,
        "total_focus_chunks": total_focus_chunks,
        "min_focus_text_chars": min(focus_text_values) if focus_text_values else 0,
        "max_focus_text_chars": max(focus_text_values) if focus_text_values else 0,
        "avg_focus_text_chars": (
            sum(focus_text_values) / len(focus_text_values)
            if focus_text_values
            else 0
        ),
        "errors": errors,
        "outputs": {
            "segmented_documents_dir": str(output_dir),
            "manifest": str(manifest_csv),
            "audit": str(audit_json),
        },
        "next_step": (
            "Run pollutant, outcome, and effect measure agents on segmented documents."
        ),
    }

    write_json(audit_json, audit)

    return {
        "summaries": summaries,
        "audit": audit,
    }
