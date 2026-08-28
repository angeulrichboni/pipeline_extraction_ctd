from datetime import date
from pathlib import Path

from stage_bph.config import load_project_config
from stage_bph.presence import build_daily_presence


def test_presence_has_96_slots() -> None:
    root = Path(__file__).resolve().parents[1]
    config = load_project_config(root)
    for individual in config.individuals.values():
        pieces = build_daily_presence(individual, date(2021, 1, 4), config.parameters)
        assert len(pieces) == 96
        assert set(pieces) <= {"sejour", "chambre", "cuisine", "sdb", "absent"}
