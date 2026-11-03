#!/usr/bin/env python3
"""Percentile table for harness sample files and cyclictest histograms.

Usage: analyze.py FILE [FILE ...]
  *.bin   harness samples: records of (<i8 t_ns, <i8 v_ns)
  other   cyclictest --histfile output (1 us bins)

All statistics happen here, offline, never in the measurement loop (§3.4).
"""
import sys

import numpy as np

PCTS = [50, 90, 99, 99.9, 99.99]
SAMPLE = np.dtype([("t_ns", "<i8"), ("v_ns", "<i8")])


def load_bin(path):
    return np.fromfile(path, dtype=SAMPLE)["v_ns"] / 1000.0, None


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
    print(f"{'source':<44}{'n':>8}" + "".join(f"{'p' + str(p):>9}" for p in PCTS) + f"{'max':>9}  (us)")
    for path in paths:
        if path.endswith(".bin"):
            us, _ = load_bin(path)
            mx = us.max()
        else:
            us, mx = load_cyclictest_hist(path)
        row = np.percentile(us, PCTS)
        print(f"{path[-44:]:<44}{len(us):>8}" + "".join(f"{v:>9.1f}" for v in row) + f"{mx:>9.1f}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1:])
