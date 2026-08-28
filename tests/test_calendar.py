from datetime import datetime

from stage_bph.calendar_utils import annex_day_type


def test_real_calendar_weekend_transition() -> None:
    # 1 Janvier 2021 était un vendredi.
    assert annex_day_type(datetime(2021, 1, 1, 17, 45)) == "semaine"
    assert annex_day_type(datetime(2021, 1, 1, 18, 0)) == "weekend"
    assert annex_day_type(datetime(2021, 1, 3, 17, 45)) == "weekend"
    assert annex_day_type(datetime(2021, 1, 3, 18, 0)) == "semaine"
