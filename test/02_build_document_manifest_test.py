from pathlib import Path

import pandas as pd


PROTOTYPE_DIR = Path("data/prototype")

CTD_CONTEXT = PROTOTYPE_DIR / "ctd_context_test.csv"
PUBMED_RESULTS = PROTOTYPE_DIR / "pubmed" / "pubmed_test_results.csv"

OUT_MANIFEST = PROTOTYPE_DIR / "documents_manifest_test.csv"
OUT_AUDIT = PROTOTYPE_DIR / "documents_manifest_test_audit.csv"


def normalize_pmid(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip()


def first_value(value: str) -> str:
    value = str(value).strip()

    if not value or value.lower() == "nan":
        return ""

    return value.split("|")[0].strip()


def compute_retrieval_priority(row: pd.Series) -> str:
    """
    Priorité pour Paperclip.

    high:
        PMCID disponible, car l'article a probablement un full text accessible.
    medium:
        DOI disponible mais pas PMCID.
    low:
        ni PMCID ni DOI.
    """
    pmc_id = str(row.get("pmc_id", "")).strip()
    doi = str(row.get("doi", "")).strip()

    if pmc_id and pmc_id.lower() != "nan":
        return "high"

    if doi and doi.lower() != "nan":
        return "medium"

    return "low"


def main() -> None:
    if not CTD_CONTEXT.exists():
        raise FileNotFoundError(f"Missing CTD context file: {CTD_CONTEXT}")

    if not PUBMED_RESULTS.exists():
        raise FileNotFoundError(f"Missing PubMed results file: {PUBMED_RESULTS}")

    ctd = pd.read_csv(CTD_CONTEXT, dtype=str).fillna("")
    pubmed = pd.read_csv(PUBMED_RESULTS, dtype=str).fillna("")

    ctd["pmid"] = normalize_pmid(ctd["pmid"])
    pubmed["pmid"] = normalize_pmid(pubmed["pmid"])

    # On garde une ligne CTD représentative par PMID pour le manifest test.
    # Les détails complets CTD restent disponibles dans ctd_context_test.csv.
    ctd_manifest = (
        ctd.sort_values(["source_pollutant", "pmid"])
        .drop_duplicates(subset=["pmid"])
        .copy()
    )

    keep_ctd_cols = [
        "pmid",
        "source_pollutant",
        "Stressor Agent",
        "Receptors",
        "Outcome",
        "Country",
        "Medium",
        "Exposure Marker",
        "Anatomy",
        "Associated Study Title",
        "Author's Summary",
        "source_file",
    ]

    keep_ctd_cols = [col for col in keep_ctd_cols if col in ctd_manifest.columns]
    ctd_manifest = ctd_manifest[keep_ctd_cols].copy()

    ctd_manifest = ctd_manifest.rename(
        columns={
            "Stressor Agent": "stressor_agent",
            "Receptors": "receptors",
            "Outcome": "outcome_ctd",
            "Country": "country",
            "Medium": "medium",
            "Exposure Marker": "exposure_marker",
            "Anatomy": "anatomy",
            "Associated Study Title": "associated_study_title_ctd",
            "Author's Summary": "author_summary_ctd",
        }
    )

    # Colonnes PubMed utiles
    keep_pubmed_cols = [
        "pmid",
        "pmc_id",
        "doi",
        "title",
        "abstract",
        "journal",
        "year",
        "authors",
        "mesh_terms",
        "keywords",
        "publication_types",
        "has_abstract",
        "pubmed_status",
    ]

    keep_pubmed_cols = [col for col in keep_pubmed_cols if col in pubmed.columns]
    pubmed_manifest = pubmed[keep_pubmed_cols].copy()

    manifest = ctd_manifest.merge(
        pubmed_manifest,
        on="pmid",
        how="left",
        validate="one_to_one",
    )

    # Normalisation légère
    manifest["stressor_agent_primary"] = manifest["stressor_agent"].apply(first_value)
    manifest["outcome_ctd_primary"] = manifest["outcome_ctd"].apply(first_value)
    manifest["receptors_primary"] = manifest["receptors"].apply(first_value)
    manifest["country_primary"] = manifest["country"].apply(first_value)

    manifest["has_pubmed"] = manifest["title"].astype(str).str.strip().ne("")
    manifest["has_abstract"] = manifest["abstract"].astype(str).str.strip().ne("")
    manifest["has_pmc_id"] = manifest["pmc_id"].astype(str).str.strip().ne("")
    manifest["has_doi"] = manifest["doi"].astype(str).str.strip().ne("")

    manifest["paperclip_candidate"] = manifest["has_pmc_id"] | manifest["has_doi"]
    manifest["retrieval_priority"] = manifest.apply(compute_retrieval_priority, axis=1)

    # Ordre final des colonnes
    preferred_order = [
        "pmid",
        "source_pollutant",
        "stressor_agent",
        "stressor_agent_primary",
        "receptors",
        "receptors_primary",
        "outcome_ctd",
        "outcome_ctd_primary",
        "country",
        "country_primary",
        "medium",
        "exposure_marker",
        "anatomy",
        "title",
        "year",
        "journal",
        "doi",
        "pmc_id",
        "has_pubmed",
        "has_abstract",
        "has_pmc_id",
        "has_doi",
        "paperclip_candidate",
        "retrieval_priority",
        "abstract",
        "associated_study_title_ctd",
        "author_summary_ctd",
        "authors",
        "mesh_terms",
        "keywords",
        "publication_types",
        "pubmed_status",
        "source_file",
    ]

    final_cols = [col for col in preferred_order if col in manifest.columns]
    other_cols = [col for col in manifest.columns if col not in final_cols]
    manifest = manifest[final_cols + other_cols]

    manifest.to_csv(OUT_MANIFEST, index=False)

    audit_rows = [
        {"metric": "rows", "value": len(manifest)},
        {"metric": "unique_pmids", "value": manifest["pmid"].nunique()},
        {"metric": "with_pubmed", "value": int(manifest["has_pubmed"].sum())},
        {"metric": "with_abstract", "value": int(manifest["has_abstract"].sum())},
        {"metric": "with_pmc_id", "value": int(manifest["has_pmc_id"].sum())},
        {"metric": "with_doi", "value": int(manifest["has_doi"].sum())},
        {
            "metric": "paperclip_candidates",
            "value": int(manifest["paperclip_candidate"].sum()),
        },
    ]

    audit = pd.DataFrame(audit_rows)
    audit.to_csv(OUT_AUDIT, index=False)

    print("=" * 80)
    print("DOCUMENT MANIFEST TEST COMPLETE")
    print("=" * 80)
    print(audit.to_string(index=False))
    print("=" * 80)
    print(f"Manifest written to: {OUT_MANIFEST}")
    print(f"Audit written to:    {OUT_AUDIT}")
    print("=" * 80)


if __name__ == "__main__":
    main()