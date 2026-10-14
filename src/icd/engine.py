from __future__ import annotations

from collections.abc import Mapping

from .normalization import canonicalize


OUTPUT_FIELDS = [
    "outcome_mapping_key",
    "mapping_rule_id",
    "mapping_scope_status",
    "mapping_status",
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
    "validation_status",
    "mapping_confidence",
    "mapping_rationale",
    "mapping_source_icd_url",
    "mapping_source_evidence_url",
    "mapping_validation_batch",
]


def apply_mapping(
    row: Mapping[str, str],
    reference: Mapping[tuple[str, str], Mapping[str, str]],
    in_scope_pollutants: tuple[str, ...] = ("PM2.5", "PM10"),
    release: str = "ICD-10 (OMS, release 2019)",
) -> dict[str, str]:
    output = dict(row)
    pollutant = (row.get("pollutant_specific") or "").strip()
    outcome_key = canonicalize(row.get("outcome_normalized"))
    pmid = (row.get("pmid") or "").strip()

    if pollutant not in in_scope_pollutants:
        output.update({
            "outcome_mapping_key": outcome_key,
            "mapping_rule_id": "",
            "mapping_scope_status": "OUT_OF_SCOPE_POLLUTANT",
            "mapping_status": "OUT_OF_SCOPE",
            "semantic_type": "",
            "normalized_health_concept": "",
            "endpoint_type": "",
            "eligible_for_icd": "",
            "icd_release": release,
            "icd_code": "",
            "icd_title": "",
            "icd_chapter": "",
            "icd_chapter_name": "",
            "mapping_level": "",
            "validation_status": "",
            "mapping_confidence": "",
            "mapping_rationale": "Polluant hors du périmètre PM2.5/PM10.",
            "mapping_source_icd_url": "",
            "mapping_source_evidence_url": "",
            "mapping_validation_batch": "",
        })
        return output

    rule = reference.get((outcome_key, pmid))
    if rule is None:
        rule = reference.get((outcome_key, "*"))

    if rule is None:
        output.update({
            "outcome_mapping_key": outcome_key,
            "mapping_rule_id": "",
            "mapping_scope_status": "IN_SCOPE_PM",
            "mapping_status": "UNMAPPED_REVIEW",
            "semantic_type": "",
            "normalized_health_concept": "",
            "endpoint_type": "",
            "eligible_for_icd": "",
            "icd_release": release,
            "icd_code": "",
            "icd_title": "",
            "icd_chapter": "",
            "icd_chapter_name": "",
            "mapping_level": "",
            "validation_status": "SOURCE_REVIEW_REQUIRED",
            "mapping_confidence": "",
            "mapping_rationale": "Aucune règle applicable.",
            "mapping_source_icd_url": "",
            "mapping_source_evidence_url": "",
            "mapping_validation_batch": "",
        })
        return output

    output.update({
        "outcome_mapping_key": outcome_key,
        "mapping_rule_id": rule["rule_id"],
        "mapping_scope_status": "IN_SCOPE_PM",
        "mapping_status": rule["mapping_status"],
        "semantic_type": rule["semantic_type"],
        "normalized_health_concept": rule["normalized_health_concept"],
        "endpoint_type": rule["endpoint_type"],
        "eligible_for_icd": rule["eligible_for_icd"],
        "icd_release": rule["icd_release"],
        "icd_code": rule["icd_code"],
        "icd_title": rule["icd_title"],
        "icd_chapter": rule["icd_chapter"],
        "icd_chapter_name": rule["icd_chapter_name"],
        "mapping_level": rule["mapping_level"],
        "validation_status": rule["validation_status"],
        "mapping_confidence": rule["mapping_confidence"],
        "mapping_rationale": rule["mapping_rationale"],
        "mapping_source_icd_url": rule["source_icd_url"],
        "mapping_source_evidence_url": rule["source_evidence_url"],
        "mapping_validation_batch": rule["validation_batch"],
    })
    return output
