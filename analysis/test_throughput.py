"""Synthetic checks for analysis/throughput.py and the throughput branch of clock_guard.py.

Run: python3 -m pytest
"""
import os, subprocess, sys, shutil
import throughput, clock_guard
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TSC = clock_guard.TSC_MHZ
HDR = "stressor,phase,rc,tdp_level,aperf0,mperf0,aperf1,mperf1,pkg_temp_mc,pkg_throttle\n"

def run_dir(root, cfg, r, ops, tdp=(0, 0), mhz=1600, drop_cpu=False):
    d = os.path.join(root, "throughput", cfg, f"run{r}"); os.makedirs(d)
    m = int(TSC * 1e6 * 60)  # 60 s of MPERF
    rows = HDR
    for s, v in ops.items():
        if drop_cpu and s == "cpu":
            continue
        open(f"{d}/{s}.yaml", "w").write(
            "---\nsystem-info:\n      hostname: t490\nmetrics:\n    - stressor: %s\n"
            "      bogo-ops: 1\n      bogo-ops-per-second-usr-sys-time: 999.0\n"
            "      bogo-ops-per-second-real-time: %f\n" % (s, v))
        rows += f"{s},before,,{tdp[0]},1000,2000,1000,2000,40000,10\n"
        rows += f"{s},after,0,{tdp[1]},{1000 + int(m * mhz / TSC)},{2000 + m},{1000 + int(m * mhz / TSC)},{2000 + m},55000,12\n"
    open(f"{d}/throughput.csv", "w").write(rows)
    return d


def test_throughput_and_clock_guard(tmp_path):
    root = str(tmp_path)
    for r, j in ((1, 0.99), (2, 1.00), (3, 1.01)):
        run_dir(root, "nomitigations", r, {"cpu": 100 * j, "switch": 1000 * j})
        run_dir(root, "rt", r, {"cpu": 100 * j * 1.005, "switch": 800 * j})
    d = throughput.collect(root)
    assert len(d) == 12 and set(d.config) == {"nomitigations", "rt"}, d
    assert (d.throttle_delta == 2).all() and (d.temp_c_after == 55).all()
    c = throughput.compare(d, "nomitigations", "rt").set_index("stressor")
    assert abs(c.at["switch", "delta_pct"] + 20) < 1e-6 and c.at["switch", "conclusive"], c   # rt 20% slower, beyond 2% spread
    assert abs(c.at["cpu", "delta_pct"] - 0.5) < 1e-6 and not c.at["cpu", "conclusive"], c    # +0.5% < spread
    assert c.at["switch", "runs"] == "3/3"

    # usr-sys-time line must not be picked up; a YAML without the real-time line is an error
    bad = os.path.join(root, "bad.yaml"); open(bad, "w").write("bogo-ops-per-second-usr-sys-time: 5\n")
    try: throughput.ops_per_s(bad); raise SystemExit("no error on missing metric")
    except ValueError: pass

    # clock guard: good / cTDP drop / slow clock / missing cpu stressor / no base given
    g = lambda dd, base=1600: clock_guard.problems(dd, 0, base)
    ok = os.path.join(root, "throughput", "rt", "run1")
    assert g(ok) == [], g(ok)
    assert any("tdp_level 1" in p for p in g(run_dir(root, "x", 1, {"cpu": 1, "pipe": 1}, tdp=(0, 1))))
    slow = g(run_dir(root, "x", 2, {"cpu": 1}, mhz=800))
    assert len(slow) == 2 and all("800 MHz" in p for p in slow), slow
    assert any("clock unchecked" in p for p in g(run_dir(root, "x", 3, {"cpu": 1, "pipe": 1}, drop_cpu=True)))
    assert g(run_dir(root, "x", 4, {"cpu": 1}, mhz=800), base=0) == []   # turbo-on rows: tdp only
    assert clock_guard.problems(os.path.join(root, "nothing"), 0, 0)      # latency path: no sidecars -> problem

    # CLI end to end
    r = subprocess.run([sys.executable, os.path.join(ROOT, "analysis/clock_guard.py"), ok, "0", "1600"]); assert r.returncode == 0
    r = subprocess.run([sys.executable, os.path.join(ROOT, "analysis/clock_guard.py"), ok, "1", "1600"], capture_output=True); assert r.returncode == 1
    shutil.rmtree(os.path.join(root, "throughput", "x"))
    r = subprocess.run([sys.executable, os.path.join(ROOT, "analysis/throughput.py"), root, os.path.join(root, "t.csv")], capture_output=True, text=True)
    assert r.returncode == 0 and "switch" in r.stdout, r.stderr
