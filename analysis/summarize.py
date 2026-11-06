#!/usr/bin/env python3
"""Campaign summary: one row per (config, run, load, test), written to CSV.

Usage: summarize.py [RESULTS_DIR] [OUT_CSV]
  defaults: results/  results/summary.csv

Walks RESULTS_DIR/<config>/run<r>/{idle,loaded}/ for every config in
configs/matrix.json. Latency tests get p50..p99.99 and max (us, or ns/load
for memlat) plus the thermal context of the run (§3.5): fraction of samples
in a throttled monitor interval, package temperature and clock. hwgap rows
give gap-size percentiles plus gaps/s and % of time lost, since the gap
count, not a per-sample latency, is what it measures.

A test that is in one run of a config but missing from another is reported
on stderr: absence must be explained (nosmt has no 2-6 ctxswitch), not silent.
"""
import glob
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyze import PCTS, load_bin, throttle_state  # noqa: E402

HWGAP = np.dtype([("t_ns", "<i8"), ("gap_ns", "<i8"), ("smi", "<i8")])


def monitor_context(mon):
    m = pd.read_csv(mon)
    return {"temp_c_mean": m["pkg_temp_mc"].mean() / 1000, "temp_c_max": m["pkg_temp_mc"].max() / 1000,
            "mhz_mean": m["cur_khz"].mean() / 1000, "mhz_min": m["cur_khz"].min() / 1000}


def pcts(v):
    p = np.percentile(v, PCTS)
    return {**{f"p{q}": x for q, x in zip(PCTS, p)}, "max": v.max()}


def one(binpath):
    base = binpath[:-4]
    j = json.load(open(base + ".json"))
    row = {"test": os.path.basename(base), "smi_delta": j.get("smi_delta"),
           "tainted": j.get("tainted"), **monitor_context(base + ".monitor.csv")}
    if j["test"] == "hwgap":
        g = np.fromfile(binpath, dtype=HWGAP)
        secs = j["params"]["spin_ns"] / 1e9
        us = g["gap_ns"] / 1e3
        row.update(n=len(g), unit="us gap", gaps_per_s=len(g) / secs,
                   lost_pct=us.sum() / 1e6 / secs * 100, **pcts(us))
    else:
        v, unit, t = load_bin(binpath)
        st = throttle_state(t, base + ".monitor.csv", base + ".json")
        row.update(n=len(v), unit=unit, thr_frac=(st == 1).mean(), **pcts(v))
    return row


def main(results, out):
    cfgs = json.load(open("configs/matrix.json"))["configs"]
    rows = []
    for c in cfgs:
        for rd in sorted(glob.glob(f"{results}/{c['name']}/run*")):
            for load in ("idle", "loaded"):
                for b in sorted(glob.glob(f"{rd}/{load}/*.bin")):
                    rows.append({"config_id": c["id"], "config": c["name"],
                                 "run": int(rd.rsplit("run", 1)[1]), "load": load, **one(b)})
    df = pd.DataFrame(rows)
    # Every test must appear in every run of its config (§3.6 needs >= 3).
    n = df.groupby(["config", "load", "test"])["run"].nunique()
    for k, v in n[n != n.max()].items():
        print(f"WARNING {k}: only {v} runs", file=sys.stderr)
    if (df["tainted"] != 0).any():
        print("WARNING tainted kernel in:", df[df["tainted"] != 0][["config", "run"]].drop_duplicates().values.tolist(),
              file=sys.stderr)
    df.to_csv(out, index=False, float_format="%.4g")
    print(f"{len(df)} rows, {df['config'].nunique()} configs -> {out}")


if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[0] if a else "results", a[1] if len(a) > 1 else "results/summary.csv")
