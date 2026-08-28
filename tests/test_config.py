from pathlib import Path

from stage_bph.config import load_project_config


def test_config_is_complete() -> None:
    root = Path(__file__).resolve().parents[1]
    config = load_project_config(root)
    assert len(config.individuals) == 30
    assert len(config.households) == 12
    assert {h.occupant_count for h in config.households.values()} == {2, 5}
