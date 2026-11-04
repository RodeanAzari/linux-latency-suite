#!/usr/bin/env python3
"""Summarize hwgap runs: what took the measured CPU away, how often, for how long.

Usage: gaps.py RUN_DIR [RUN_DIR ...] [--plot OUT.png]
  RUN_DIR holds hwgap_cpu<N>.bin + .json (harness/hwgap.c).

A gap is an SMI when MSR_SMI_COUNT (read right after each gap, on the measured
CPU) moved since the previous gap; the first gap compares against the
sidecar's env_before. Other gaps are classed by duration only; the classes'
causes were identified by tracing (docs/platform.md).
"""
import glob
import json
import sys

import numpy as np

REC = np.dtype([("t_ns", "<i8"), ("gap_ns", "<i8"), ("smi", "<i8")])
CLASSES = [  # (name, lo_us, hi_us) for non-SMI gaps
    ("< 5 us (interrupts)", 0, 5),
    ("5-100 us (softirq, short work)", 5, 100),
    (">= 100 us (long work items)", 100, float("inf")),
]


def load(run_dir):
    side = glob.glob(f"{run_dir}/hwgap_cpu*.json")[0]
    j = json.load(open(side))
    g = np.fromfile(side[:-5] + ".bin", dtype=REC)
    prev = np.concatenate([[j["env_before"]["smi_count"]], g["smi"][:-1]])
    is_smi = (g["smi"] - prev) > 0
    if (g["smi"] < 0).any() or j["env_before"]["smi_count"] < 0:
        sys.exit(f"{run_dir}: SMI count unreadable; cannot attribute")
    return j, g, is_smi


def summarize(run_dir):
    j, g, is_smi = load(run_dir)
    p = j["params"]
    secs = p["spin_ns"] / 1e9
    us = g["gap_ns"] / 1e3
    print(f"\n{run_dir}: {secs:.0f} s on CPU {p['cpu']}, threshold {p['gap_threshold_ns']} ns, "
          f"{len(g)} gaps, {us.sum() / 1e6 / secs * 100:.3f}% of time lost; "
          f"SMIs in sidecar {j['smi_delta']}, attributed to gaps {is_smi.sum()}; "
          f"dropped {p['gaps_dropped']}")
    print(f"  {'class':<34}{'count':>8}{'per s':>9}{'p50 us':>9}{'p99 us':>9}{'max us':>10}")
    rows = [("SMI", us[is_smi])]
    rows += [(n, us[~is_smi & (us >= lo) & (us < hi)]) for n, lo, hi in CLASSES]
    for name, x in rows:
        if len(x):
            print(f"  {name:<34}{len(x):>8}{len(x) / secs:>9.2f}{np.median(x):>9.1f}"
                  f"{np.percentile(x, 99):>9.1f}{x.max():>10.1f}")
        else:
            print(f"  {name:<34}{0:>8}")
    if is_smi.any():
        t = (g["t_ns"][is_smi] - g["t_ns"][0]) / 1e9
        print(f"  SMI gaps (s into run: us): "
              + ", ".join(f"{a:.0f}: {b:.0f}" for a, b in zip(t, us[is_smi])))


def plot(run_dirs, out):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    other_c, smi_c = "#2a78d6", "#eb6834"
    INK, INK2, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#fcfcfb"
    plt.rcParams.update({"font.size": 10, "axes.edgecolor": MUTED, "axes.labelcolor": INK2,
                         "xtick.color": MUTED, "ytick.color": MUTED, "text.color": INK})
    fig, axes = plt.subplots(len(run_dirs), 1, figsize=(10, 3.2 * len(run_dirs) + 0.6),
                             facecolor=SURFACE, sharey=True, squeeze=False)
    for ax, d in zip(axes[:, 0], run_dirs):
        j, g, is_smi = load(d)
        t = (g["t_ns"] - g["t_ns"][0]) / 60e9
        us = g["gap_ns"] / 1e3
        ax.set_facecolor(SURFACE)
        ax.set_yscale("log")
        ax.grid(axis="y", color=GRID, linewidth=0.6)
        ax.spines[["top", "right"]].set_visible(False)
        ax.scatter(t[~is_smi], us[~is_smi], s=3, color=other_c, linewidths=0, label="interrupt / kernel work")
        ax.scatter(t[is_smi], us[is_smi], s=36, color=smi_c, edgecolors=SURFACE, linewidths=1.5,
                   label=f"SMI ({is_smi.sum()})", zorder=3)
        ax.set_ylabel("gap (µs)")
        ax.set_xlim(0, t[-1])
        ax.set_title(f"{d.rstrip('/').split('/')[-1]}: {len(g):,} gaps in "
                     f"{j['params']['spin_ns'] / 60e9:.0f} min on CPU {j['params']['cpu']}",
                     loc="left", fontsize=11, color=INK)
        ax.legend(loc="upper right", frameon=False, markerscale=1.5)
    axes[-1, 0].set_xlabel("time into run (min)")
    fig.text(0.01, 0.01, "Every interval > 300 ns in which a pinned SCHED_FIFO spin loop did not run. "
             "SMI = MSR_SMI_COUNT advanced during the gap.", color=MUTED, fontsize=8)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(out, dpi=160, facecolor=SURFACE)


if __name__ == "__main__":
    args = sys.argv[1:]
    out = None
    if "--plot" in args:
        i = args.index("--plot")
        out = args[i + 1]
        del args[i:i + 2]
    if not args:
        sys.exit(__doc__)
    for d in args:
        summarize(d)
    if out:
        plot(args, out)
