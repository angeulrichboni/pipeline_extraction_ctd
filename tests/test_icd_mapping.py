from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stage_bph.icd_mapping.engine import apply_mapping
from stage_bph.icd_mapping.reference import load_reference, validate_reference


REFERENCE = ROOT / "config" / "icd_mapping_reference.csv"


class CompleteMappingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.reference, cls.rows = load_reference(REFERENCE)

    def test_reference_has_no_conflict(self) -> None:
        self.assertEqual(validate_reference(REFERENCE), [])

    def test_exact_code_mapping(self) -> None:
        row = {
            "pollutant_specific": "PM2.5",
            "pmid": "1",
            "outcome_normalized": "risk of Parkinson disease",
        }
        result = apply_mapping(row, self.reference)
        self.assertEqual(result["icd_code"], "G20")
        self.assertEqual(result["icd_chapter"], "06")

    def test_chapter_mapping(self) -> None:
        row = {
            "pollutant_specific": "PM10",
            "pmid": "1",
            "outcome_normalized": "cardiovascular disease",
        }
        result = apply_mapping(row, self.reference)
        self.assertEqual(result["mapping_level"], "chapter")
        self.assertEqual(result["icd_chapter"], "09")

    def test_non_icd_mapping(self) -> None:
        row = {
            "pollutant_specific": "PM2.5",
            "pmid": "1",
            "outcome_normalized": "peak expiratory flow",
        }
        result = apply_mapping(row, self.reference)
        self.assertEqual(result["mapping_status"], "VALIDATED_NON_ICD")
        self.assertEqual(result["icd_chapter"], "")

    def test_metabolic_syndrome_wbc_exception(self) -> None:
        row = {
            "pollutant_specific": "PM10",
            "pmid": "18470293",
            "outcome_normalized": "metabolic syndrome",
        }
        result = apply_mapping(row, self.reference)
        self.assertEqual(result["mapping_status"], "VALIDATED_NON_ICD")
        self.assertEqual(result["normalized_health_concept"], "White blood cell count")

    def test_metabolic_syndrome_disease_exception(self) -> None:
        row = {
            "pollutant_specific": "PM2.5",
            "pmid": "36598238",
            "outcome_normalized": "metabolic syndrome",
        }
        result = apply_mapping(row, self.reference)
        self.assertEqual(result["mapping_status"], "VALIDATED_ICD")
        self.assertEqual(result["icd_chapter"], "04")

    def test_out_of_scope_pollutant(self) -> None:
        row = {
            "pollutant_specific": "NO2",
            "pmid": "1",
            "outcome_normalized": "asthma",
        }
        result = apply_mapping(row, self.reference)
        self.assertEqual(result["mapping_status"], "OUT_OF_SCOPE")


if __name__ == "__main__":
    unittest.main()
