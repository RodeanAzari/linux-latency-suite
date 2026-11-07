#!/usr/bin/env python3
"""Per-knob marginal contribution with the §3.6 variance test.

Usage: deltas.py [SUMMARY_CSV] [OUT_CSV]
  defaults: results/summary.csv  results/deltas.csv

Rows of configs/matrix.json are cumulative, so knob i's contribution is
config i minus config i-1. A "spot" row adds one knob to baseline and is
compared with config 0. For each (step, load, test, percentile):

  delta = median over runs (config) - median over runs (previous)
  spread = max - min over runs, the larger of the two configs'

and the step is "inconclusive" when |delta| <= spread: the configs have
not been shown to differ (§3.6). The spread is the plain range of 3 runs,
so one outlier run makes its steps inconclusive by design.
"""
import json
import sys

import pandas as pd

METRICS = ["p50", "p99", "p99.9"]


def main(summary, out):
    d = pd.read_csv(summary)
    d = d[d["test"] != "hwgap_cpu2"]  # gap sizes aren't latencies; gaps.py covers them
    cfgs = json.load(open("configs/matrix.json"))["configs"]
    stats = d.groupby(["config", "load", "test"])[METRICS].agg(["median", "min", "max"])
    steps, prev = [], None
    for c in cfgs:
        if c.get("spot"):
            steps.append((cfgs[0]["name"], c["name"]))
        else:
            if prev is not None:
                steps.append((prev, c["name"]))
            prev = c["name"]
    rows = []
    for a, b in steps:
        for (load, test) in sorted({k[1:] for k in stats.index if k[0] == b}):
            if (a, load, test) not in stats.index:
                continue  # e.g. ctxswitch_2_6 has no nosmt counterpart
            sa, sb = stats.loc[(a, load, test)], stats.loc[(b, load, test)]
            for m in METRICS:
                ma, mb = sa[(m, "median")], sb[(m, "median")]
                spread = max(sa[(m, "max")] - sa[(m, "min")], sb[(m, "max")] - sb[(m, "min")])
                delta = mb - ma
                rows.append({"from": a, "to": b, "load": load, "test": test, "metric": m,
                             "before": ma, "after": mb, "delta": delta,
                             "delta_pct": 100 * delta / ma if ma else float("nan"),
                             "spread": spread, "conclusive": abs(delta) > spread})
    df = pd.DataFrame(rows)
    df.to_csv(out, index=False, float_format="%.4g")
    n = len(df)
    print(f"{n} comparisons, {df['conclusive'].sum()} conclusive, "
          f"{n - df['conclusive'].sum()} inconclusive -> {out}")


if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[0] if a else "results/summary.csv", a[1] if len(a) > 1 else "results/deltas.csv")
