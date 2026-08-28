#!/usr/bin/env python3
"""
Résume le fichier d'inspection Paperclip.

Entrée:
    data/prototype/paperclip/inspect/paperclip_structure_inspection.json

Objectif:
    Voir rapidement quels chemins existent pour chaque PMCID :
    - /papers/{PMC}/
    - content.lines
    - sections/
    - tables/
    - metadata.json
    - paper.json
"""

import json
from pathlib import Path

import pandas as pd


INSPECTION_JSON = Path(
    "data/prototype/paperclip/inspect/paperclip_structure_inspection.json"
)

OUT_CSV = Path(
    "data/prototype/paperclip/inspect/paperclip_structure_summary.csv"
)


def ok(cmd_result: dict) -> bool:
    return cmd_result.get("returncode") == 0


def stdout_len(cmd_result: dict) -> int:
    return len((cmd_result.get("stdout") or "").strip())


def stderr_short(cmd_result: dict, n: int = 120) -> str:
    return (cmd_result.get("stderr") or "").strip()[:n]


def stdout_preview(cmd_result: dict, n: int = 300) -> str:
    text = (cmd_result.get("stdout") or "").strip()
    text = " ".join(text.split())
    return text[:n]


def get_result(mapping: dict, key_endswith: str) -> dict:
    for path, result in mapping.items():
        if path.endswith(key_endswith):
            return result
    return {}


def main() -> None:
    if not INSPECTION_JSON.exists():
        raise FileNotFoundError(f"Missing file: {INSPECTION_JSON}")

    payload = json.loads(INSPECTION_JSON.read_text(encoding="utf-8"))

    rows = []

    for item in payload["results"]:
        pmid = item["pmid"]
        pmc_id = item["pmc_id"]

        ls_map = item.get("ls", {})
        cat_map = item.get("cat_head", {})

        base_ls = get_result(ls_map, f"/papers/{pmc_id}")
        base_ls_slash = get_result(ls_map, f"/papers/{pmc_id}/")
        sections_ls = get_result(ls_map, "/sections/")
        tables_ls = get_result(ls_map, "/tables/")
        figures_ls = get_result(ls_map, "/figures/")
        supp_ls = get_result(ls_map, "/supplementary/")

        content_cat = get_result(cat_map, "/content.lines")
        abstract_cat = get_result(cat_map, "/abstract.lines")
        title_cat = get_result(cat_map, "/title.lines")
        metadata_cat = get_result(cat_map, "/metadata.json")
        paper_cat = get_result(cat_map, "/paper.json")

        rows.append(
            {
                "pmid": pmid,
                "pmc_id": pmc_id,

                "base_ls_ok": ok(base_ls) or ok(base_ls_slash),
                "base_ls_preview": stdout_preview(base_ls) or stdout_preview(base_ls_slash),

                "content_ok": ok(content_cat),
                "content_stdout_chars": stdout_len(content_cat),
                "content_preview": stdout_preview(content_cat),

                "abstract_ok": ok(abstract_cat),
                "title_ok": ok(title_cat),

                "sections_ls_ok": ok(sections_ls),
                "sections_ls_preview": stdout_preview(sections_ls),
                "sections_ls_error": stderr_short(sections_ls),

                "tables_ls_ok": ok(tables_ls),
                "tables_ls_preview": stdout_preview(tables_ls),
                "tables_ls_error": stderr_short(tables_ls),

                "figures_ls_ok": ok(figures_ls),
                "figures_ls_preview": stdout_preview(figures_ls),

                "supplementary_ls_ok": ok(supp_ls),
                "supplementary_ls_preview": stdout_preview(supp_ls),

                "metadata_json_ok": ok(metadata_cat),
                "metadata_preview": stdout_preview(metadata_cat),

                "paper_json_ok": ok(paper_cat),
                "paper_json_preview": stdout_preview(paper_cat),
            }
        )

    df = pd.DataFrame(rows)
    df.to_csv(OUT_CSV, index=False)

    print("=" * 100)
    print("PAPERCLIP STRUCTURE SUMMARY")
    print("=" * 100)

    cols = [
        "pmid",
        "pmc_id",
        "base_ls_ok",
        "content_ok",
        "content_stdout_chars",
        "sections_ls_ok",
        "tables_ls_ok",
        "metadata_json_ok",
        "paper_json_ok",
    ]

    print(df[cols].to_string(index=False))

    print("=" * 100)
    print("BASE LS PREVIEW")
    print("=" * 100)

    for _, row in df.iterrows():
        print(f"\nPMID={row['pmid']} PMC={row['pmc_id']}")
        print(f"base_ls_preview: {row['base_ls_preview']}")
        print(f"sections_preview: {row['sections_ls_preview']}")
        print(f"tables_preview: {row['tables_ls_preview']}")

    print("=" * 100)
    print(f"CSV written to: {OUT_CSV}")
    print("=" * 100)


if __name__ == "__main__":
    main()