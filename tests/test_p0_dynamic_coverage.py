from pathlib import Path

from stage_bph.p0 import P0Reference


def test_asthma_p0_covers_dynamic_ages() -> None:
    root = Path(__file__).resolve().parents[1]
    ref = P0Reference.from_csv(root / "config" / "p0_reference.csv")
    for age in range(6, 16):
        ref.select(event_id="E02", persona_id="P1", age=age, sex="Homme", condition="Asthme préexistant")
        ref.select(event_id="E02", persona_id="P1", age=age, sex="Femme", condition="Asthme préexistant")
    for age in range(25, 55):
        ref.select(event_id="E02", persona_id="P5", age=age, sex="Homme", condition="Asthme préexistant")
        ref.select(event_id="E02", persona_id="P5", age=age, sex="Femme", condition="Asthme préexistant")
