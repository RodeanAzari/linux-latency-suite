#!/usr/bin/env python3
"""PREEMPT_RT's throughput cost (§6): stress-ng bogo-ops/s, rt vs nomitigations.

Usage: throughput.py [RESULTS_DIR] [OUT_CSV] [FROM] [TO]
  defaults: results/  results/throughput.csv  nomitigations  rt

Reads RESULTS_DIR/throughput/<config>/run<r>/<stressor>.yaml
(scripts/run-throughput.sh) and writes one row per (config, run, stressor):
bogo-ops/s by wall clock, plus the package temperature and throttle count
delta of that stressor from throughput.csv. Then prints, per stressor,
TO vs FROM with the §3.6 rule used in deltas.py: the change is conclusive
only when |delta of medians| > max-min spread of either config's runs.
Positive delta_pct = TO does more work per second.
"""
import glob
import os
import re
import sys

import pandas as pd

OPS = re.compile(r"^\s*bogo-ops-per-second-real-time:\s*(\S+)\s*$", re.M)


def ops_per_s(yaml_path):
    """The one real-time bogo-ops/s figure of a single-stressor stress-ng YAML."""
    m = OPS.findall(open(yaml_path).read())
    if len(m) != 1:
        raise ValueError(f"{yaml_path}: {len(m)} bogo-ops-per-second-real-time lines, want 1")
    return float(m[0])


def collect(results):
    rows = []
    for rd in sorted(glob.glob(os.path.join(results, "throughput", "*", "run*"))):
        cfg, run = rd.split(os.sep)[-2], int(rd.rsplit("run", 1)[1])
        env = pd.read_csv(os.path.join(rd, "throughput.csv")).set_index(["stressor", "phase"])
        for y in sorted(glob.glob(os.path.join(rd, "*.yaml"))):
            s = os.path.basename(y)[:-5]
            b, a = env.loc[(s, "before")], env.loc[(s, "after")]
            rows.append({"config": cfg, "run": run, "stressor": s, "ops_s": ops_per_s(y),
                         "temp_c_after": a.pkg_temp_mc / 1000,
                         "throttle_delta": a.pkg_throttle - b.pkg_throttle})
        failed = os.path.join(rd, "FAILED")
        if os.path.exists(failed) and os.path.getsize(failed):
            print(f"{rd}: FAILED: {open(failed).read().strip()}", file=sys.stderr)
    return pd.DataFrame(rows)


def compare(d, a, b):
    out = []
    for s in sorted(set(d.stressor)):
        x, y = d[(d.config == a) & (d.stressor == s)].ops_s, d[(d.config == b) & (d.stressor == s)].ops_s
        if x.empty or y.empty:
            print(f"{s}: missing in {a if x.empty else b}", file=sys.stderr)
            continue
        delta = y.median() - x.median()
        spread = max(x.max() - x.min(), y.max() - y.min())
        out.append({"stressor": s, a: x.median(), b: y.median(),
                    "delta_pct": 100 * delta / x.median(), "spread_pct": 100 * spread / x.median(),
                    "runs": f"{len(x)}/{len(y)}", "conclusive": abs(delta) > spread})
    return pd.DataFrame(out)


def main(results, out, a, b):
    d = collect(results)
    if d.empty:
        sys.exit(f"no throughput runs under {results}/throughput")
    d.to_csv(out, index=False, float_format="%.6g")
    print(f"{len(d)} rows -> {out}")
    print(compare(d, a, b).to_string(index=False, float_format=lambda v: f"{v:.4g}"))


if __name__ == "__main__":
    x = sys.argv[1:]
    main(x[0] if x else "results/", x[1] if len(x) > 1 else "results/throughput.csv",
         x[2] if len(x) > 2 else "nomitigations", x[3] if len(x) > 3 else "rt")
