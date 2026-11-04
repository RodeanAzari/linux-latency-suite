#!/usr/bin/env python3
"""Match hwgap's SMI gaps against the kernel hwlat tracer, event by event.

Usage: match_hwlat.py RUN_DIR
  RUN_DIR from scripts/validate-hwgap-hwlat.sh: hwgap_cpu2.{bin,json} and
  hwlat_trace.txt (trace_clock=mono, so both tools share CLOCK_MONOTONIC).

hwlat reports an event when its sampling width ends, up to 0.9 s after the
stall, so an hwgap gap at t matches an hwlat event stamped in (t, t + 1 s].
SMIs are minutes apart, so the match is unambiguous.
"""
import re
import sys

import numpy as np

sys.path.insert(0, sys.path[0])
from gaps import load  # noqa: E402

EV = re.compile(r"\s(\d+\.\d+):\s+#\d+\s+inner/outer\(us\):\s*(\d+)/(\d+)")


def main(run_dir):
    j, g, is_smi = load(run_dir)
    hw = []
    for line in open(f"{run_dir}/hwlat_trace.txt"):
        m = EV.search(line)
        if m:
            hw.append((float(m.group(1)), max(int(m.group(2)), int(m.group(3)))))
    t0 = g["t_ns"][0] / 1e9
    gap_t = g["t_ns"] / 1e9
    print(f"hwgap: {is_smi.sum()} SMI gaps (MSR delta {j['smi_delta']}); "
          f"hwlat: {len(hw)} events > 10 us")
    print(f"{'source':<8}{'t (s into run)':>16}{'hwgap us':>11}{'hwlat us':>11}{'SMI?':>6}")
    used = set()
    for i in np.flatnonzero(is_smi | (g["gap_ns"] > 100_000)):
        m = [k for k, (t, _) in enumerate(hw) if gap_t[i] < t <= gap_t[i] + 1.0]
        hl = f"{hw[m[0]][1]:>11}" if m else f"{'—':>11}"
        used.update(m)
        if is_smi[i] or m:
            print(f"{'both' if m else 'hwgap':<8}{gap_t[i] - t0:>16.1f}{g['gap_ns'][i] / 1e3:>11.0f}"
                  f"{hl}{'yes' if is_smi[i] else 'no':>6}")
    for k, (t, us) in enumerate(hw):
        if k not in used:
            print(f"{'hwlat':<8}{t - t0:>16.1f}{'—':>11}{us:>11}{'':>6}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
