#!/usr/bin/env python3
"""Do two CPUs' hwgap gaps happen at the same moment?

Usage: match_gaps.py RUN_DIR
  RUN_DIR holds hwgap_cpu2 and hwgap_cpu3 runs taken at the same time
  (scripts/phase-d-turbo-stall.sh pair). Both share CLOCK_MONOTONIC.

Kernel work is per CPU: an interrupt or a kthread on CPU 2 has no reason to
start at the same nanosecond as one on CPU 3. A stall of the whole package
(an SMI, a clock/voltage transition) stops both together. For each duration
class this prints the fraction of one CPU's gaps that overlap a gap on the
other, against chance (the other CPU's gaps shifted by tens of ms), and for
overlapping gaps the offset between their start times.
"""
import sys

import numpy as np

sys.path.insert(0, sys.path[0])
from gaps import load  # noqa: E402

CLASSES_US = [(0.3, 5), (5, 10), (10, 40), (40, float("inf"))]
SHIFTS_NS = (37e6, 113e6, 251e6)


def partner(x, y, shift=0):
    """Index of a y gap overlapping each x gap, or -1."""
    ys = y["t_ns"] + shift
    ye = ys + y["gap_ns"]
    xs, xe = x["t_ns"], x["t_ns"] + x["gap_ns"]
    i = np.searchsorted(ys, xe)  # y gaps start in time order
    out = np.full(len(x), -1)
    for k in (1, 2, 3):
        j = np.clip(i - k, 0, len(ys) - 1)
        hit = (out < 0) & (ys[j] < xe) & (ye[j] > xs)
        out[hit] = j[hit]
    return out


def main(run_dir):
    _, a, _ = load(f"{run_dir}/2")
    _, b, _ = load(f"{run_dir}/3")
    dur = (b["t_ns"][-1] - b["t_ns"][0]) / 1e9
    print(f"{run_dir}: cpu2 {len(a)} gaps, cpu3 {len(b)} gaps, {dur:.1f} s")
    print(f"{'cpu3 class':<14}{'n':>7}{'per s':>8}{'p50 us':>8}{'overlap':>9}"
          f"{'chance':>8}{'start dt p50/p90 ns':>21}{'cpu2 p50 us':>12}")
    for lo, hi in CLASSES_US:
        m = (b["gap_ns"] >= lo * 1e3) & (b["gap_ns"] < hi * 1e3)
        x = b[m]
        if not len(x):
            continue
        p = partner(x, a)
        ok = p >= 0
        chance = np.mean([(partner(x, a, s) >= 0).mean() for s in SHIFTS_NS])
        dt = np.abs(a["t_ns"][p[ok]] - x["t_ns"][ok])
        dts = f"{np.percentile(dt, 50):.0f}/{np.percentile(dt, 90):.0f}" if ok.any() else "-"
        p2 = f"{np.median(a['gap_ns'][p[ok]]) / 1e3:.1f}" if ok.any() else "-"
        print(f"{f'{lo}-{hi} us':<14}{len(x):>7}{len(x) / dur:>8.0f}"
              f"{np.median(x['gap_ns']) / 1e3:>8.1f}{ok.mean():>9.1%}{chance:>8.1%}"
              f"{dts:>21}{p2:>12}")


if __name__ == "__main__":
    main(sys.argv[1])
