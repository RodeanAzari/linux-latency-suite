"""deltas.py: per-knob steps and the §3.6 range test. Run: python3 -m pytest"""
import json
import math

import pandas as pd
import pytest

import deltas

CONFIGS = [{"id": 0, "name": "a"}, {"id": 1, "name": "b"},
           {"id": 2, "name": "spot", "spot": True},      # mid-list: must not break the chain
           {"id": 3, "name": "c"}]


def run(tmp_path, monkeypatch, rows, configs=CONFIGS):
    """rows: (config, test, [p50 of run1..run3]); p99/p99.9 copy p50."""
    (tmp_path / "configs").mkdir(parents=True)
    json.dump({"configs": configs}, open(tmp_path / "configs" / "matrix.json", "w"))
    monkeypatch.chdir(tmp_path)
    out = []
    for cfg, test, vals in rows:
        for r, v in enumerate(vals, 1):
            out.append({"config": cfg, "run": r, "load": "idle", "test": test, "p50": v, "p99": v, "p99.9": v})
    pd.DataFrame(out).to_csv("s.csv", index=False)
    deltas.main("s.csv", "d.csv")
    d = pd.read_csv("d.csv")
    return d[d.metric == "p50"].set_index(["from", "to", "test"])


def test_steps_are_cumulative_and_spot_compares_to_baseline(tmp_path, monkeypatch):
    rows = [(c, "t", [1, 1, 1]) for c in ("a", "b", "spot", "c")]
    d = run(tmp_path, monkeypatch, rows)
    assert sorted(i[:2] for i in d.index) == [("a", "b"), ("a", "spot"), ("b", "c")]


def test_delta_is_difference_of_medians(tmp_path, monkeypatch):
    # a's mean is 4, its median 2: an outlier run must not move the delta
    d = run(tmp_path, monkeypatch, [("a", "t", [1, 2, 9]), ("b", "t", [3, 3, 3])])
    r = d.loc[("a", "b", "t")]
    assert (r.before, r.after, r.delta) == (2, 3, 1)
    assert r.delta_pct == pytest.approx(50)


def test_spread_is_the_larger_range_of_either_config(tmp_path, monkeypatch):
    d = run(tmp_path, monkeypatch, [("a", "t", [10, 10, 10]), ("b", "t", [14, 20, 17])])
    r = d.loc[("a", "b", "t")]
    assert r.spread == 6 and r.delta == 7 and r.conclusive          # 7 > 6
    d = run(tmp_path / "x", monkeypatch, [("a", "t", [4, 10, 12]), ("b", "t", [17, 17, 17])])
    r = d.loc[("a", "b", "t")]
    assert r.spread == 8 and r.delta == 7 and not r.conclusive      # range of the *before* config


def test_change_equal_to_spread_is_inconclusive(tmp_path, monkeypatch):
    d = run(tmp_path, monkeypatch, [("a", "t", [9, 10, 11]), ("b", "t", [12, 12, 12])])
    r = d.loc[("a", "b", "t")]
    assert r.delta == r.spread == 2 and not r.conclusive


def test_slower_is_positive_and_conclusive_both_ways(tmp_path, monkeypatch):
    d = run(tmp_path, monkeypatch, [("a", "t", [10, 10, 10]), ("b", "t", [5, 5, 5]),
                                    ("c", "t", [8, 8, 8])])
    assert d.loc[("a", "b", "t")].delta == -5 and d.loc[("a", "b", "t")].conclusive
    assert d.loc[("b", "c", "t")].delta == 3 and d.loc[("b", "c", "t")].conclusive


def test_missing_counterpart_and_hwgap_are_skipped(tmp_path, monkeypatch):
    d = run(tmp_path, monkeypatch, [("a", "t", [1, 1, 1]), ("b", "t", [1, 1, 1]),
                                    ("b", "only_in_b", [1, 1, 1]),
                                    ("a", "hwgap_cpu2", [1, 1, 1]), ("b", "hwgap_cpu2", [5, 5, 5])])
    tests = {i[2] for i in d.index}
    assert tests == {"t"}


def test_zero_before_gives_nan_pct(tmp_path, monkeypatch):
    d = run(tmp_path, monkeypatch, [("a", "t", [0, 0, 0]), ("b", "t", [1, 1, 1])])
    assert math.isnan(d.loc[("a", "b", "t")].delta_pct)


def test_every_metric_is_compared(tmp_path, monkeypatch):
    run(tmp_path, monkeypatch, [("a", "t", [1, 1, 1]), ("b", "t", [2, 2, 2])])
    assert sorted(pd.read_csv("d.csv").metric) == sorted(deltas.METRICS)
