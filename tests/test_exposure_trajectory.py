from __future__ import annotations

import csv
from pathlib import Path

from stage_bph.exposure_trajectory import generate_exposure_trajectory


def _write(path: Path, headers: list[str], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)


def test_trajectory_cumulative_never_decreases_and_counter_resets(tmp_path: Path) -> None:
    windows = tmp_path / "exposure_windows.csv"
    thresholds = tmp_path / "exposure_thresholds.csv"
    output = tmp_path / "exposure_trajectory.csv"

    bag = lambda d: f"daily|I1|{d}|PM25"
    days = ["2021-01-01", "2021-01-02", "2021-01-03", "2021-01-04", "2021-01-05"]
    # dépassement MIL : oui, oui, non, oui, oui -> compteur 1,2,0,1,2 ; record 2
    mil = ["1", "1", "0", "1", "1"]
    sums = ["40", "45", "10", "50", "55"]
    excess = ["5", "6", "0", "8", "9"]

    _write(
        windows,
        ["bag_id", "sum_exposure"],
        [[bag(d), s] for d, s in zip(days, sums)],
    )
    _write(
        thresholds,
        [
            "bag_id", "individual_id", "pollutant", "window_type", "window_start",
            "mean_exposure", "excess_burden", "mil_exceedance",
        ],
        [
            [bag(d), "I1", "PM25", "daily", f"{d}T00:00", "20", e, m]
            for d, e, m in zip(days, excess, mil)
        ],
    )

    report = generate_exposure_trajectory(thresholds, windows, output, gzip_output=False)
    assert report["output_rows"] == 5
    assert report["flow_count"] == 1

    with output.open(newline="") as f:
        rows = list(csv.DictReader(f))

    cumulative = [float(r["cumulative_exposure"]) for r in rows]
    assert cumulative == sorted(cumulative), "cumulative_exposure ne doit jamais décroître"

    consecutive = [int(r["consecutive_exceedances"]) for r in rows]
    assert consecutive == [1, 2, 0, 1, 2]

    max_consecutive = [int(r["max_consecutive_exceedances_to_date"]) for r in rows]
    assert max_consecutive == [1, 2, 2, 2, 2], "le record ne doit jamais redescendre"

    assert [int(r["window_index"]) for r in rows] == [0, 1, 2, 3, 4]


def test_trajectory_handles_insufficient_history() -> None:
    from stage_bph.exposure_trajectory import _direction, _slope

    assert _direction([]) == "insuffisant"
    assert _direction([5.0]) == "insuffisant"
    assert _direction([5.0, 5.0]) == "stable"
    assert _direction([5.0, 8.0]) == "hausse"
    assert _direction([8.0, 5.0]) == "baisse"
    assert _slope([5.0]) is None
    assert _slope([5.0, 12.0]) == 7.0
