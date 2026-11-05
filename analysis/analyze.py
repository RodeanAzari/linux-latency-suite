#!/usr/bin/env python3
"""Percentile table for harness sample files and cyclictest histograms.

Usage: analyze.py FILE [FILE ...]
  *.bin   harness samples: records of (<i8 t_ns, <i8 v_ns)
  other   cyclictest --histfile output (1 us bins)
memlat samples hold K dependent loads each (sidecar "loads_per_sample");
they are reported as ns per load instead of us per sample.

Thermal split (§3.5): when X.monitor.csv sits beside X.bin, each sample is
placed in the 100 ms monitor interval it fell in (both use CLOCK_MONOTONIC).
An interval is throttled if the measured core's or the package's throttle
counter rose during it. The whole interval counts, so the split leans
towards "throttled". Samples outside the monitor's coverage are left out
of both rows.

All statistics happen here, offline, never in the measurement loop (§3.4).
"""
import json
import os
import sys

import numpy as np

PCTS = [50, 90, 99, 99.9, 99.99]
SAMPLE = np.dtype([("t_ns", "<i8"), ("v_ns", "<i8")])
MIN_TAIL = 10


def load_bin(path):
    """Samples in us, or (memlat) ns per load. Returns (values, unit, t_ns)."""
    s = np.fromfile(path, dtype=SAMPLE)
    v = s["v_ns"]
    sidecar = path[:-4] + ".json"
    if os.path.exists(sidecar):
        k = json.load(open(sidecar))["params"].get("loads_per_sample")
        if k:
            return v / k, "ns/load", s["t_ns"]
    return v / 1000.0, "us", s["t_ns"]


def throttle_state(t_ns, monitor_csv, sidecar):
    """Per sample: 1 throttled, 0 not, -1 outside the monitor's coverage.

    The sidecar's env_before/env_after readings bound the run, so a run
    shorter than a few monitor periods is still fully covered.
    """
    m = np.genfromtxt(monitor_csv, delimiter=",", names=True, dtype=np.int64, ndmin=1)
    t, core, pkg = list(m["t_ns"]), list(m["core_throttle"]), list(m["pkg_throttle"])
    if os.path.exists(sidecar):
        j = json.load(open(sidecar))
        for k, at in (("env_before", 0), ("env_after", len(t))):
            e = j[k]
            if min(e["core_throttle"], e["pkg_throttle"]) < 0:  # -1 = unreadable
                continue
            t.insert(at, e["mono_ns"]), core.insert(at, e["core_throttle"]), pkg.insert(at, e["pkg_throttle"])
    t, core, pkg = np.array(t), np.array(core), np.array(pkg)
    moved = (np.diff(core) > 0) | (np.diff(pkg) > 0)
    i = np.searchsorted(t, t_ns, side="right")  # sample is in [t[i-1], t[i])
    inside = (i > 0) & (i < len(t))
    state = np.full(len(t_ns), -1)
    state[inside] = moved[i[inside] - 1]
    return state


def load_cyclictest_hist(path):
    """Expand a cyclictest histogram into per-sample microsecond values.

    Values are integer microseconds (cyclictest truncates). Samples past the
    histogram range are counted as overflows and only their max is known, so
    percentiles that land in them are lower bounds.
    """
    values, counts, max_us, overflows = [], [], None, 0
    with open(path) as f:
        for line in f:
            if line.startswith("# Max Latencies:"):
                max_us = int(line.split(":")[1].split()[0])
            elif line.startswith("# Histogram Overflows:"):
                overflows = int(line.split(":")[1].split()[0])
            elif line.strip() and not line.startswith("#"):
                b, c = line.split()[:2]
                values.append(int(b))
                counts.append(int(c))
    us = np.repeat(np.array(values, dtype=float), counts)
    if overflows:
        us = np.concatenate([us, np.full(overflows, float(max_us))])
    note = f"{overflows} overflows; tail percentiles are lower bounds" if overflows else None
    return us, max_us


def main(paths):
    print(f"{'source':<44}{'n':>8}" + "".join(f"{'p' + str(p):>9}" for p in PCTS) + f"{'max':>9}  unit")
    for path in paths:
        state = None
        if path.endswith(".bin"):
            us, unit, t_ns = load_bin(path)
            mx = us.max()
            mon = path[:-4] + ".monitor.csv"
            if os.path.exists(mon):
                state = throttle_state(t_ns, mon, path[:-4] + ".json")
        else:
            (us, mx), unit = load_cyclictest_hist(path), "us"
        fmt = ">9.2f" if unit == "ns/load" else ">9.1f"

        def row(label, v):
            # A percentile with fewer than MIN_TAIL samples beyond it means nothing (§3.3).
            p = [f"{x:{fmt}}" if len(v) * (1 - q / 100) >= MIN_TAIL else f"{'-':>9}"
                 for q, x in zip(PCTS, np.percentile(v, PCTS))]
            print(f"{label:<44}{len(v):>8}" + "".join(p) + f"{v.max():{fmt}}  {unit}")

        row(path[-44:], us)
        if state is None:
            continue
        thr, cool, out = us[state == 1], us[state == 0], (state < 0).sum()
        if not len(thr):
            print(f"{'  no throttling during the run':<44}" + (f" ({out} samples outside monitor)" if out else ""))
            continue
        for label, v in ((f"  throttled ({len(thr) / len(us):.1%})", thr), ("  unthrottled", cool)):
            if len(v):
                row(label, v)
        if out:
            print(f"  ({out} samples outside the monitor's coverage, in neither row)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1:])
