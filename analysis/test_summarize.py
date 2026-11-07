"""summarize.py: per-run rows, clock from APERF/MPERF, loud gaps. Run: python3 -m pytest"""
import json
import math
import os

import numpy as np
import pandas as pd
import pytest

import summarize
from test_analyze import MS, write_bin, write_monitor


def env(aperf=None, mperf=None):
    e = {"mono_ns": 0, "core_throttle": 0, "pkg_throttle": 0}
    if aperf is not None:
        e.update(aperf=aperf, mperf=mperf)
    return e


def test_busy_mhz_is_tsc_scaled_aperf_over_mperf():
    j = {"env_before": env(1000, 1000), "env_after": env(1000 + 1600, 1000 + 1896)}
    assert summarize.busy_mhz(j) == pytest.approx(summarize.TSC_MHZ * 1600 / 1896)
    assert summarize.busy_mhz(j) == pytest.approx(1600, rel=1e-3)


@pytest.mark.parametrize("before,after", [
    (env(), env()),                       # sidecar predates the fields
    (env(-1, 5), env(10, 20)),            # unreadable
    (env(0, 100), env(50, 100)),          # MPERF did not advance
])
def test_busy_mhz_nan_when_unknown(before, after):
    assert math.isnan(summarize.busy_mhz({"env_before": before, "env_after": after}))


def make_test(d, name, values_us, test=None, params=None, tainted=0, throttle_at=None):
    """A latency test: samples every 1 ms, monitor every 100 ms."""
    os.makedirs(d, exist_ok=True)
    n = len(values_us)
    base = os.path.join(d, name)
    write_bin(base + ".bin", np.arange(n) * MS, (np.array(values_us) * 1000).astype(np.int64))
    span = (n // 100 + 1) * 100
    write_monitor(base + ".monitor.csv",
                  [(t * MS, int(throttle_at is not None and t > throttle_at), 0) for t in range(0, span + 1, 100)])
    json.dump({"test": test or name, "params": params or {}, "tainted": tainted, "smi_delta": 0,
               "env_before": env(0, 0), "env_after": env(1600, 1896)}, open(base + ".json", "w"))


def test_one_latency_row(tmp_path):
    d = str(tmp_path)
    make_test(d, "sched_latency", list(range(1, 1001)), throttle_at=500)
    r = summarize.one(os.path.join(d, "sched_latency.bin"))
    assert r["n"] == 1000 and r["unit"] == "us" and r["max"] == 1000
    assert r["p50"] == pytest.approx(500.5)           # linear interpolation over 1..1000
    assert r["p99.9"] == pytest.approx(999.001)
    # samples at 0..999 ms; the counter rose in the (500, 600] row -> [500, 600) throttled
    assert r["thr_frac"] == pytest.approx(0.1)
    assert r["busy_mhz"] == pytest.approx(1600, rel=1e-3)


def test_thr_frac_counts_uncovered_samples_as_not_throttled(tmp_path):
    d = str(tmp_path)
    make_test(d, "sched_latency", [1.0] * 1000)
    # monitor stopped at 500 ms: the second half is outside coverage, which is
    # "unknown", not "throttled" (§3.5)
    write_monitor(os.path.join(d, "sched_latency.monitor.csv"), [(t * MS, 0, 0) for t in range(0, 501, 100)])
    assert summarize.one(os.path.join(d, "sched_latency.bin"))["thr_frac"] == 0


def test_one_hwgap_row(tmp_path):
    d = str(tmp_path)
    g = np.zeros(3, dtype=summarize.HWGAP)
    g["gap_ns"] = [1_000_000, 1_000_000, 1_000_000]          # three 1 ms gaps
    g.tofile(os.path.join(d, "hwgap_cpu2.bin"))
    write_monitor(os.path.join(d, "hwgap_cpu2.monitor.csv"), [(0, 0, 0)])
    json.dump({"test": "hwgap", "params": {"spin_ns": 2_000_000_000}, "tainted": 0,
               "env_before": env(), "env_after": env()}, open(os.path.join(d, "hwgap_cpu2.json"), "w"))
    r = summarize.one(os.path.join(d, "hwgap_cpu2.bin"))
    assert r["unit"] == "us gap" and r["n"] == 3
    assert r["gaps_per_s"] == pytest.approx(1.5)              # 3 gaps in 2 s
    assert r["lost_pct"] == pytest.approx(0.15)               # 3 ms of 2 s
    assert r["p50"] == pytest.approx(1000)


@pytest.fixture
def campaign(tmp_path, monkeypatch):
    """A results tree with its own configs/matrix.json; cwd set to it."""
    (tmp_path / "configs").mkdir()
    json.dump({"configs": [{"id": 0, "name": "baseline"}, {"id": 1, "name": "governor"}]},
              open(tmp_path / "configs" / "matrix.json", "w"))
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_main_writes_one_row_per_config_run_load_test(campaign, capsys):
    for cfg in ("baseline", "governor"):
        for r in (1, 2, 3):
            for load in ("idle", "loaded"):
                make_test(f"results/{cfg}/run{r}/{load}", "syscall_empty", [0.1] * 200)
    summarize.main("results", "out.csv")
    d = pd.read_csv("out.csv")
    assert len(d) == 12 and set(d.run) == {1, 2, 3} and set(d.load) == {"idle", "loaded"}
    assert list(d.config_id.unique()) == [0, 1]
    assert "WARNING" not in capsys.readouterr().err


def test_main_warns_on_missing_run_and_module_taint(campaign, capsys):
    for r in (1, 2, 3):
        make_test(f"results/baseline/run{r}/idle", "syscall_empty", [0.1] * 200,
                  tainted=(1 << 12) if r == 2 else 4)
    for r in (1, 2):    # memlat absent from run 3: must be reported, not silent
        make_test(f"results/baseline/run{r}/idle", "memlat", [1.0] * 200)
    summarize.main("results", "out.csv")
    o = capsys.readouterr()
    assert "('baseline', 'idle', 'memlat'): only 2 runs" in o.err
    assert "module-tainted kernel in: [['baseline', 2]]" in o.err
    assert "taint bit 2" in o.out          # MSR writes: expected, a note only
