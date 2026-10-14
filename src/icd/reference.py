from __future__ import annotations

import csv
from pathlib import Path

from .normalization import canonicalize


REQUIRED_COLUMNS = {
    "rule_id",
    "priority",
    "outcome_normalized",
    "outcome_key",
    "pmid_scope",
    "semantic_type",
    "normalized_health_concept",
    "endpoint_type",
    "eligible_for_icd",
    "icd_release",
    "icd_code",
    "icd_title",
    "icd_chapter",
    "icd_chapter_name",
    "mapping_level",
    "mapping_status",
    "validation_status",
    "mapping_confidence",
    "evidence_basis",
    "mapping_rationale",
    "source_icd_url",
    "source_evidence_url",
    "validation_batch",
}


def validate_reference(
    path: Path,
    expected_release: str = "ICD-10 (OMS, release 2019)",
) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fields = set(reader.fieldnames or [])
        missing = sorted(REQUIRED_COLUMNS - fields)
        if missing:
            return [{
                "error_type": "MISSING_COLUMNS",
                "rule_id": "",
                "message": ", ".join(missing),
            }]
        rows = list(reader)

    seen: set[tuple[str, str]] = set()

    for line_number, row in enumerate(rows, start=2):
        rule_id = row["rule_id"].strip()
        outcome = row["outcome_normalized"].strip()
        key = row["outcome_key"].strip()
        pmid_scope = row["pmid_scope"].strip()
        eligible = row["eligible_for_icd"].strip().lower()
        status = row["mapping_status"].strip()
        release = row["icd_release"].strip()
        chapter = row["icd_chapter"].strip()
        code = row["icd_code"].strip()
        level = row["mapping_level"].strip()

        def add(error_type: str, message: str) -> None:
            errors.append({
                "error_type": error_type,
                "rule_id": rule_id,
                "message": f"Ligne {line_number}: {message}",
            })

        if key != canonicalize(outcome):
            add("KEY_MISMATCH", "outcome_key ne correspond pas à la normalisation.")
        if release != expected_release:
            add("RELEASE_MISMATCH", f"{release!r} != {expected_release!r}.")
        if eligible not in {"true", "false"}:
            add("INVALID_BOOLEAN", f"eligible_for_icd={eligible!r}.")
        if not pmid_scope:
            add("EMPTY_PMID_SCOPE", "Utiliser '*' ou un PMID.")
        if pmid_scope != "*" and not pmid_scope.isdigit():
            add("INVALID_PMID_SCOPE", f"pmid_scope={pmid_scope!r}.")
        pair = (key, pmid_scope)
        if pair in seen:
            add("DUPLICATE_RULE", f"Règle dupliquée pour {pair}.")
        seen.add(pair)

        if status == "VALIDATED_ICD":
            if eligible != "true":
                add("ICD_ELIGIBILITY_CONFLICT", "VALIDATED_ICD exige true.")
            if not chapter:
                add("MISSING_CHAPTER", "Un chapitre ICD est obligatoire.")
            if level not in {"chapter", "multi_chapter"} and not code:
                add("MISSING_CODE", "Un code est requis hors mapping chapitre.")
        else:
            if eligible != "false":
                add("NON_ICD_ELIGIBILITY_CONFLICT", f"{status} exige false.")
            if code or chapter:
                add("NON_ICD_HAS_ICD", "Une règle non-ICD ne doit pas porter de code/chapitre.")

    return errors


def load_reference(
    path: Path,
    expected_release: str = "ICD-10 (OMS, release 2019)",
) -> tuple[dict[tuple[str, str], dict[str, str]], list[dict[str, str]]]:
    errors = validate_reference(path, expected_release)
    if errors:
        preview = "; ".join(error["message"] for error in errors[:5])
        raise ValueError(f"Référence invalide: {preview}")

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    lookup = {
        (row["outcome_key"], row["pmid_scope"]): row
        for row in rows
    }
    return lookup, rows
