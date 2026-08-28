from pathlib import Path
import json
import re

INPUT_JSONL = Path("data/processed_full/llm_inputs/llm_inputs.jsonl")
OUTPUT_JSONL = Path("data/processed_full/population_location_extraction/population_location_llm_inputs.jsonl")
PROMPT_PATH = Path("data/processed_full/population_location_extraction/population_location_prompt.txt")

OUTPUT_JSONL.parent.mkdir(parents=True, exist_ok=True)

SECTION_KEYWORDS = [
    "abstract",
    "methods",
    "materials and methods",
    "study population",
    "participants",
    "subjects",
    "cohort",
    "study area",
    "study design",
    "data source",
    "baseline",
    "recruitment",
    "population",
    "setting",
    "exposure assessment",
]

MAX_CHARS_PER_DOC = 18000


def read_jsonl(path):
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def normalize_text(text):
    if text is None:
        return ""
    text = str(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def get_first_existing(doc, keys):
    for key in keys:
        if key in doc and doc[key]:
            return doc[key]
    return ""


def extract_sections_from_text(text):
    """
    Découpe approximative par titres de sections.
    Fonction robuste même si le texte n'a pas une structure parfaite.
    """
    text = normalize_text(text)

    patterns = [
        r"\bABSTRACT\b",
        r"\bMETHODS\b",
        r"\bMATERIALS AND METHODS\b",
        r"\bSTUDY POPULATION\b",
        r"\bPARTICIPANTS\b",
        r"\bSUBJECTS\b",
        r"\bCOHORT\b",
        r"\bSTUDY AREA\b",
        r"\bSTUDY DESIGN\b",
        r"\bDATA SOURCE\b",
        r"\bBASELINE\b",
        r"\bRESULTS\b",
        r"\bDISCUSSION\b",
    ]

    combined = "(" + "|".join(patterns) + ")"
    parts = re.split(combined, text, flags=re.IGNORECASE)

    sections = []

    if len(parts) < 3:
        return [{"section_title": "full_text_excerpt", "text": text[:MAX_CHARS_PER_DOC]}]

    current_title = None

    for part in parts:
        part = part.strip()
        if not part:
            continue

        if re.fullmatch(combined, part, flags=re.IGNORECASE):
            current_title = part.lower()
        else:
            if current_title:
                sections.append({
                    "section_title": current_title,
                    "text": part
                })

    return sections


def is_relevant_section(section_title, section_text):
    full = f"{section_title} {section_text}".lower()
    return any(keyword in full for keyword in SECTION_KEYWORDS)


def build_llm_input(doc):
    pmid = str(get_first_existing(doc, ["pmid", "PMID", "pubmed_id"]))
    title = normalize_text(get_first_existing(doc, ["title", "article_title", "Title"]))
    abstract = normalize_text(get_first_existing(doc, ["abstract", "Abstract"]))
    full_text = normalize_text(get_first_existing(doc, ["full_text", "text", "document_text", "content"]))

    sections = []

    if abstract:
        sections.append({
            "section_title": "abstract",
            "text": abstract
        })

    if full_text:
        extracted_sections = extract_sections_from_text(full_text)
        for sec in extracted_sections:
            if is_relevant_section(sec["section_title"], sec["text"]):
                sections.append(sec)

    # fallback si aucune section pertinente trouvée
    if not sections and full_text:
        sections.append({
            "section_title": "full_text_excerpt",
            "text": full_text[:MAX_CHARS_PER_DOC]
        })

    # limiter la taille envoyée au LLM
    compact_sections = []
    total_chars = 0

    for sec in sections:
        sec_text = normalize_text(sec["text"])
        if not sec_text:
            continue

        remaining = MAX_CHARS_PER_DOC - total_chars
        if remaining <= 0:
            break

        compact_sections.append({
            "section_title": sec["section_title"],
            "text": sec_text[:remaining]
        })

        total_chars += len(sec_text[:remaining])

    return {
        "pmid": pmid,
        "title": title,
        "task": "extract_population_age_sex_location",
        "input_sections": compact_sections
    }


PROMPT = """
You are a scientific information extraction agent.

Your task is to extract study population, geographic location, age, and sex information from biomedical article text.

You must follow these rules strictly:

1. Extract only information explicitly stated in the provided text.
2. Do not infer country, city, age, or sex from author affiliations, journal name, PMID, or external knowledge.
3. If the information is absent, return "not_reported".
4. If the information is vague, return "ambiguous".
5. If multiple populations, countries, or age groups are present, return all explicitly stated values and set status to "multiple".
6. Always provide the evidence sentence copied from the provided text.
7. Do not invent values.

Return only valid JSON with this schema:

{
  "pmid": "string",
  "study_country": "string or not_reported",
  "study_city_or_region": "string or not_reported",
  "study_location_detail": "string or not_reported",
  "study_population": "string or not_reported",
  "age_group": "string or not_reported",
  "age_min": "number or null",
  "age_max": "number or null",
  "age_mean": "number or null",
  "sex": "male/female/both/not_reported/ambiguous",
  "population_details": "string or not_reported",
  "evidence_sentence": "string or not_reported",
  "source_section": "string or not_reported",
  "confidence": "high/medium/low",
  "status": "explicit/not_reported/ambiguous/multiple/review"
}
""".strip()


with open(PROMPT_PATH, "w", encoding="utf-8") as f:
    f.write(PROMPT)

count = 0

with open(OUTPUT_JSONL, "w", encoding="utf-8") as out:
    for doc in read_jsonl(INPUT_JSONL):
        item = build_llm_input(doc)

        if not item["pmid"]:
            continue

        out.write(json.dumps(item, ensure_ascii=False) + "\n")
        count += 1

print("LLM input file saved:", OUTPUT_JSONL)
print("Prompt saved:", PROMPT_PATH)
print("Documents prepared:", count)