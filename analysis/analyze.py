#!/usr/bin/env python3
"""Percentile table for harness sample files and cyclictest histograms.

Usage: analyze.py FILE [FILE ...]
  *.bin   harness samples: records of (<i8 t_ns, <i8 v_ns)
  other   cyclictest --histfile output (1 us bins)
memlat samples hold K dependent loads each (sidecar "loads_per_sample");
they are reported as ns per load instead of us per sample.

All statistics happen here, offline, never in the measurement loop (§3.4).
"""
import json
import os
import sys

import numpy as np

PCTS = [50, 90, 99, 99.9, 99.99]
SAMPLE = np.dtype([("t_ns", "<i8"), ("v_ns", "<i8")])


def load_bin(path):
    """Samples in us, or (memlat) ns per load. Returns (values, unit)."""
    v = np.fromfile(path, dtype=SAMPLE)["v_ns"]
    sidecar = path[:-4] + ".json"
    if os.path.exists(sidecar):
        k = json.load(open(sidecar))["params"].get("loads_per_sample")
        if k:
            return v / k, "ns/load"
    return v / 1000.0, "us"


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
        if path.endswith(".bin"):
            us, unit = load_bin(path)
            mx = us.max()
        else:
            (us, mx), unit = load_cyclictest_hist(path), "us"
        row = np.percentile(us, PCTS)
        fmt = ">9.2f" if unit == "ns/load" else ">9.1f"
        print(f"{path[-44:]:<44}{len(us):>8}" + "".join(f"{v:{fmt}}" for v in row) + f"{mx:{fmt}}  {unit}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1:])
