from pathlib import Path

from stage_bph.p0 import P0Reference


def test_p0_selector() -> None:
    root = Path(__file__).resolve().parents[1]
    ref = P0Reference.from_csv(root / "config" / "p0_reference.csv")
    child = ref.select(event_id="E01", persona_id="P1", age=8, sex="Homme")
    assert child.rule_id == "R001"
    htn = ref.select(event_id="BASELINE_HTN", persona_id="P4", age=67, sex="Femme")
    assert htn.rule_id == "R015"
