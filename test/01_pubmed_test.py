import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from Bio import Entrez
from dotenv import load_dotenv
from tqdm import tqdm


load_dotenv()

NCBI_EMAIL = os.getenv("NCBI_EMAIL", "").strip()
NCBI_API_KEY = os.getenv("NCBI_API_KEY", "").strip()

if not NCBI_EMAIL:
    raise ValueError("NCBI_EMAIL is missing in .env")

Entrez.email = NCBI_EMAIL

if NCBI_API_KEY:
    Entrez.api_key = NCBI_API_KEY


INPUT_PMIDS = Path("data/prototype/pmids_test.txt")
OUT_DIR = Path("data/prototype/pubmed")
RAW_DIR = OUT_DIR / "raw"

OUT_DIR.mkdir(parents=True, exist_ok=True)
RAW_DIR.mkdir(parents=True, exist_ok=True)

RESULTS_CSV = OUT_DIR / "pubmed_test_results.csv"
RESULTS_JSONL = OUT_DIR / "pubmed_test_results.jsonl"
PMC_IDS = OUT_DIR / "pmc_ids_test.txt"
MISSING_PMIDS = OUT_DIR / "pubmed_missing_pmids.txt"
AUDIT_JSON = OUT_DIR / "pubmed_test_audit.json"
LOG_FILE = OUT_DIR / "pubmed_test.log"

BATCH_SIZE = 50
SLEEP_SECONDS = 0.5
MAX_RETRIES = 3


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)

log = logging.getLogger(__name__)


def as_text(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value if value else None


def attrs(obj: Any) -> dict:
    return getattr(obj, "attributes", {}) or {}


def chunked(items: list[str], size: int) -> list[list[str]]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def load_pmids(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"Missing PMIDs file: {path}")

    pmids = []
    seen = set()

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            pmid = line.strip()
            if not pmid:
                continue
            if not pmid.isdigit():
                raise ValueError(f"Invalid PMID: {pmid}")
            if pmid not in seen:
                pmids.append(pmid)
                seen.add(pmid)

    if not pmids:
        raise ValueError(f"No PMIDs found in {path}")

    return pmids


def fetch_pubmed_batch(pmids: list[str]) -> Any:
    joined = ",".join(pmids)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            handle = Entrez.efetch(
                db="pubmed",
                id=joined,
                rettype="xml",
                retmode="xml",
            )
            records = Entrez.read(handle)
            handle.close()
            return records

        except Exception as exc:
            wait = 3 * attempt
            log.warning(
                f"Attempt {attempt}/{MAX_RETRIES} failed for batch "
                f"size={len(pmids)}: {exc}. Waiting {wait}s."
            )
            time.sleep(wait)

    raise RuntimeError(f"All retries failed for batch: {pmids}")


def parse_abstract(article: dict) -> str | None:
    abstract_obj = article.get("Abstract", {})
    abstract_texts = abstract_obj.get("AbstractText", [])

    if not abstract_texts:
        return None

    if isinstance(abstract_texts, str):
        return abstract_texts.strip() or None

    parts = []

    for part in abstract_texts:
        text = str(part).strip()
        if not text:
            continue

        part_attrs = attrs(part)
        label = as_text(part_attrs.get("Label")) or as_text(part_attrs.get("NlmCategory"))

        if label:
            parts.append(f"{label}: {text}")
        else:
            parts.append(text)

    abstract = " ".join(parts).strip()
    return abstract or None


def parse_year(article: dict) -> int | None:
    journal = article.get("Journal", {})
    pub_date = journal.get("JournalIssue", {}).get("PubDate", {})

    for field in ["Year", "MedlineDate"]:
        raw = as_text(pub_date.get(field))
        if raw:
            try:
                return int(raw[:4])
            except ValueError:
                pass

    for article_date in article.get("ArticleDate", []):
        raw_year = as_text(article_date.get("Year"))
        if raw_year:
            try:
                return int(raw_year)
            except ValueError:
                pass

    return None


def parse_authors(article: dict) -> list[str]:
    authors = []

    for auth in article.get("AuthorList", []):
        collective = as_text(auth.get("CollectiveName"))
        if collective:
            authors.append(collective)
            continue

        last = as_text(auth.get("LastName"))
        fore = as_text(auth.get("ForeName"))
        initials = as_text(auth.get("Initials"))

        if last and fore:
            authors.append(f"{last} {fore}")
        elif last and initials:
            authors.append(f"{last} {initials}")
        elif last:
            authors.append(last)

    return authors


def parse_article_ids(record: dict) -> dict[str, str]:
    pubmed_data = record.get("PubmedData", {})
    article_ids = pubmed_data.get("ArticleIdList", [])

    parsed = {}

    for aid in article_ids:
        id_type = attrs(aid).get("IdType")
        value = as_text(aid)

        if not id_type or not value:
            continue

        id_type = str(id_type).lower()

        if id_type not in parsed:
            parsed[id_type] = value

    return parsed


def parse_doi(article: dict, article_ids: dict[str, str]) -> str | None:
    for eid in article.get("ELocationID", []):
        eid_type = attrs(eid).get("EIdType")
        value = as_text(eid)

        if eid_type == "doi" and value:
            return value

    return as_text(article_ids.get("doi"))


def parse_pmc_id(article_ids: dict[str, str]) -> str | None:
    pmc = as_text(article_ids.get("pmc"))

    if not pmc:
        return None

    if pmc.upper().startswith("PMC"):
        return pmc

    return f"PMC{pmc}"


def parse_mesh_terms(medline: dict) -> list[str]:
    terms = []

    for heading in medline.get("MeshHeadingList", []):
        descriptor = heading.get("DescriptorName", "")
        descriptor_text = as_text(descriptor)

        if descriptor_text:
            terms.append(descriptor_text)

    return terms


def parse_keywords(medline: dict) -> list[str]:
    keywords = []

    for keyword_group in medline.get("KeywordList", []):
        for keyword in keyword_group:
            text = as_text(keyword)
            if text:
                keywords.append(text)

    return keywords


def parse_publication_types(article: dict) -> list[str]:
    publication_types = []

    for ptype in article.get("PublicationTypeList", []):
        text = as_text(ptype)
        if text:
            publication_types.append(text)

    return publication_types


def parse_records(records: Any) -> list[dict[str, Any]]:
    parsed_articles = []

    for record in records.get("PubmedArticle", []):
        medline = record.get("MedlineCitation", {})
        article = medline.get("Article", {})
        article_ids = parse_article_ids(record)

        pmid = as_text(medline.get("PMID")) or as_text(article_ids.get("pubmed"))

        if not pmid:
            log.warning("Skipping PubMed record without PMID.")
            continue

        journal = article.get("Journal", {})

        title = as_text(article.get("ArticleTitle"))
        abstract = parse_abstract(article)
        year = parse_year(article)
        authors = parse_authors(article)
        doi = parse_doi(article, article_ids)
        pmc_id = parse_pmc_id(article_ids)

        parsed = {
            "pmid": pmid,
            "pmc_id": pmc_id,
            "doi": doi,
            "title": title,
            "abstract": abstract,
            "journal": as_text(journal.get("Title")),
            "year": year,
            "authors": authors,
            "mesh_terms": parse_mesh_terms(medline),
            "keywords": parse_keywords(medline),
            "publication_types": parse_publication_types(article),
            "has_abstract": bool(abstract),
            "pubmed_status": "found_with_abstract" if abstract else "found_no_abstract",
            "fetched_at": datetime.now().isoformat(timespec="seconds"),
        }

        parsed_articles.append(parsed)

    return parsed_articles


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False))
            f.write("\n")


def write_lines(path: Path, lines: list[str]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        if lines:
            f.write("\n".join(lines))
            f.write("\n")


def main() -> None:
    log.info("=" * 80)
    log.info("PUBMED TEST FETCH")
    log.info(f"NCBI_EMAIL configured: {Entrez.email}")
    log.info(f"NCBI_API_KEY configured: {bool(NCBI_API_KEY)}")
    log.info("=" * 80)

    input_pmids = load_pmids(INPUT_PMIDS)
    all_articles = []
    failed_batches = []

    batches = chunked(input_pmids, BATCH_SIZE)

    for batch_num, batch in enumerate(tqdm(batches, desc="PubMed batches"), start=1):
        log.info(f"Fetching batch {batch_num}/{len(batches)}: {len(batch)} PMIDs")

        try:
            records = fetch_pubmed_batch(batch)
            articles = parse_records(records)
            all_articles.extend(articles)

            raw_path = RAW_DIR / f"batch_{batch_num:04d}.json"
            with open(raw_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "batch_num": batch_num,
                        "requested_pmids": batch,
                        "returned_pmids": [a["pmid"] for a in articles],
                        "articles": articles,
                    },
                    f,
                    ensure_ascii=False,
                    indent=2,
                )

        except Exception as exc:
            log.error(f"Batch {batch_num} failed completely: {exc}")
            failed_batches.append(
                {
                    "batch_num": batch_num,
                    "pmids": batch,
                    "error": str(exc),
                }
            )

        time.sleep(SLEEP_SECONDS)

    returned_pmids = {article["pmid"] for article in all_articles}
    missing_pmids = [pmid for pmid in input_pmids if pmid not in returned_pmids]

    df = pd.DataFrame(all_articles)

    if not df.empty:
        df_for_csv = df.copy()
        for col in ["authors", "mesh_terms", "keywords", "publication_types"]:
            df_for_csv[col] = df_for_csv[col].apply(
                lambda x: json.dumps(x, ensure_ascii=False) if isinstance(x, list) else x
            )
        df_for_csv.to_csv(RESULTS_CSV, index=False)
    else:
        pd.DataFrame().to_csv(RESULTS_CSV, index=False)

    write_jsonl(RESULTS_JSONL, all_articles)

    pmc_lines = [
        f"{article['pmid']}\t{article['pmc_id']}"
        for article in all_articles
        if article.get("pmc_id")
    ]
    write_lines(PMC_IDS, pmc_lines)
    write_lines(MISSING_PMIDS, missing_pmids)

    audit = {
        "run_date": datetime.now().isoformat(timespec="seconds"),
        "input_pmids": len(input_pmids),
        "returned_articles": len(all_articles),
        "missing_pmids": len(missing_pmids),
        "failed_batches": len(failed_batches),
        "with_abstract": int(df["has_abstract"].sum()) if not df.empty else 0,
        "without_abstract": int((~df["has_abstract"]).sum()) if not df.empty else 0,
        "with_pmc_id": int(df["pmc_id"].notna().sum()) if not df.empty else 0,
        "with_doi": int(df["doi"].notna().sum()) if not df.empty else 0,
        "min_year": int(df["year"].min()) if not df.empty and df["year"].notna().any() else None,
        "max_year": int(df["year"].max()) if not df.empty and df["year"].notna().any() else None,
        "outputs": {
            "csv": str(RESULTS_CSV),
            "jsonl": str(RESULTS_JSONL),
            "pmc_ids": str(PMC_IDS),
            "missing_pmids": str(MISSING_PMIDS),
            "raw_batches": str(RAW_DIR),
        },
        "failed_batch_details": failed_batches,
    }

    with open(AUDIT_JSON, "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)

    log.info("=" * 80)
    log.info("PUBMED TEST FETCH COMPLETE")
    log.info(json.dumps(audit, indent=2, ensure_ascii=False))
    log.info("=" * 80)


if __name__ == "__main__":
    main()