"""analyze.py: sample loading and the §3.5 thermal split. Run: python3 -m pytest"""
import json

import numpy as np
import pytest

import analyze

MS = 1_000_000
MON_HDR = "t_ns,smi_count,pkg_temp_mc,cur_khz,core_throttle,pkg_throttle,tdp_level\n"


def write_bin(path, t_ns, v_ns):
    s = np.zeros(len(t_ns), dtype=analyze.SAMPLE)
    s["t_ns"], s["v_ns"] = t_ns, v_ns
    s.tofile(path)


def write_monitor(path, rows):  # rows: (t_ns, core_throttle, pkg_throttle)
    open(path, "w").write(MON_HDR + "".join(f"{t},0,50000,1600000,{c},{p},0\n" for t, c, p in rows))


def write_sidecar(path, before=None, after=None, params=None):
    env = lambda e: dict(zip(("mono_ns", "core_throttle", "pkg_throttle"), e)) if e else \
        {"mono_ns": 0, "core_throttle": -1, "pkg_throttle": -1}
    json.dump({"params": params or {}, "env_before": env(before), "env_after": env(after)}, open(path, "w"))


def test_load_bin_us_and_memlat_ns_per_load(tmp_path):
    p = str(tmp_path / "sched_latency.bin")
    write_bin(p, [1, 2], [1500, 3000])
    v, unit, t = analyze.load_bin(p)            # no sidecar: ns -> us
    assert unit == "us" and list(v) == [1.5, 3.0] and list(t) == [1, 2]

    m = str(tmp_path / "memlat.bin")
    write_bin(m, [1, 2], [6400, 12800])
    write_sidecar(m[:-4] + ".json", params={"loads_per_sample": 64})
    v, unit, _ = analyze.load_bin(m)            # memlat: ns per dependent load
    assert unit == "ns/load" and list(v) == [100.0, 200.0]

    write_sidecar(p[:-4] + ".json", params={"other": 1})   # sidecar without K: still us
    assert analyze.load_bin(p)[1] == "us"


def state(tmp_path, samples, monitor, before=None, after=None):
    mon, side = str(tmp_path / "x.monitor.csv"), str(tmp_path / "x.json")
    write_monitor(mon, monitor)
    write_sidecar(side, before, after)
    return list(analyze.throttle_state(np.array(samples), mon, side))


def test_throttled_interval_is_the_one_where_a_counter_rose(tmp_path):
    mon = [(0, 5, 9), (100 * MS, 5, 9), (200 * MS, 6, 9), (300 * MS, 6, 9)]
    # core counter rose between 100 and 200 ms: only [100, 200) is throttled
    got = state(tmp_path, [50 * MS, 150 * MS, 250 * MS], mon)
    assert got == [0, 1, 0]


def test_package_counter_alone_marks_throttled(tmp_path):
    mon = [(0, 5, 9), (100 * MS, 5, 10)]
    assert state(tmp_path, [10 * MS], mon) == [1]


def test_interval_boundaries_are_half_open(tmp_path):
    mon = [(0, 0, 0), (100 * MS, 1, 0), (200 * MS, 1, 0)]
    # t == 100 ms starts the next interval [100, 200), which did not throttle;
    # t == 100 ms - 1 is the last ns of the throttled one
    assert state(tmp_path, [100 * MS - 1, 100 * MS, 0], mon) == [1, 0, 1]


def test_outside_coverage_is_neither(tmp_path):
    mon = [(100 * MS, 0, 0), (200 * MS, 0, 0)]
    assert state(tmp_path, [50 * MS, 150 * MS, 200 * MS, 250 * MS], mon) == [-1, 0, -1, -1]


def test_sidecar_env_readings_extend_coverage(tmp_path):
    mon = [(100 * MS, 0, 0), (200 * MS, 0, 0)]
    # throttle rose between env_before (50 ms) and the first monitor row, and
    # the run's tail is closed by env_after at 250 ms
    got = state(tmp_path, [60 * MS, 150 * MS, 220 * MS], mon,
                before=(50 * MS, 0, 0), after=(250 * MS, 0, 0))
    rose = [(100 * MS, 0, 1), (200 * MS, 0, 1)]   # pkg counter 0 at env_before, 1 by the first row
    got_thr = state(tmp_path, [60 * MS], rose, before=(50 * MS, 0, 0), after=(250 * MS, 0, 1))
    assert got == [0, 0, 0] and got_thr == [1]


def test_unreadable_env_is_ignored(tmp_path):
    mon = [(100 * MS, 0, 0), (200 * MS, 0, 0)]
    got = state(tmp_path, [60 * MS, 150 * MS], mon, before=(50 * MS, -1, 0))
    assert got == [-1, 0]


def test_monitor_starting_before_env_before_is_sorted(tmp_path):
    # the monitor thread can take its first row before the sidecar's env_before
    mon = [(10 * MS, 0, 0), (100 * MS, 1, 0), (200 * MS, 1, 0)]
    got = state(tmp_path, [20 * MS, 70 * MS, 150 * MS], mon, before=(50 * MS, 0, 0))
    assert got == [0, 1, 0]   # [10,50) clean, [50,100) rose 0->1, [100,200) clean


def test_single_monitor_row(tmp_path):
    got = state(tmp_path, [150 * MS], [(100 * MS, 0, 0)], after=(200 * MS, 3, 0))
    assert got == [1]


def test_cyclictest_hist_expands_bins_and_overflows(tmp_path):
    h = tmp_path / "hist"
    h.write_text("# Histogram\n000001 2\n000003 1\n# Max Latencies: 00250\n# Histogram Overflows: 00002\n")
    us, mx = analyze.load_cyclictest_hist(str(h))
    assert mx == 250 and sorted(us) == [1, 1, 3, 250, 250]


@pytest.mark.parametrize("n", [1, 1000])
def test_main_prints_without_error(tmp_path, capsys, n):
    p = str(tmp_path / "t.bin")
    write_bin(p, np.arange(n) * MS, np.arange(1, n + 1) * 1000)
    analyze.main([p])
    assert "t.bin" in capsys.readouterr().out
