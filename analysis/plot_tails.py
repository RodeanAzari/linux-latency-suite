#!/usr/bin/env python3
"""Figure: latency tail distributions per config (§8 "histograms for each class").

Usage: plot_tails.py RESULTS_DIR LOAD OUT.png TEST [TEST ...]
  e.g. plot_tails.py results loaded docs/imgs/tails_loaded.png sched_latency syscall_getppid

One panel per test, three per row. Each line is one cumulative config (spot rows left out),
the samples of its runs pooled: the fraction of samples slower than x
(1 - CDF, log scale), HDR-histogram style, so p99, p99.9 and p99.99 read
off the y axis at 1e-2, 1e-3 and 1e-4. Pooling shows the shape of the tail;
the run-to-run variance test lives in deltas.py, not here.
"""
import glob
import json
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyze import load_bin  # noqa: E402

INK, INK2, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#fcfcfb"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
QUANTILES = [(1e-2, "p99"), (1e-3, "p99.9"), (1e-4, "p99.99")]


def configs():
    return [c["name"] for c in json.load(open("configs/matrix.json"))["configs"] if not c.get("spot")]


def pooled(results, cfg, load, test):
    """All samples of a test across a config's runs, and its unit; None if absent."""
    vals, unit = [], None
    for b in sorted(glob.glob(f"{results}/{cfg}/run*/{load}/{test}.bin")):
        v, unit, _ = load_bin(b)
        vals.append(v)
    return (np.concatenate(vals), unit, len(vals)) if vals else None


def main(results, load, out, tests):
    cfgs = configs()
    if len(cfgs) > len(SERIES):
        sys.exit(f"{len(cfgs)} configs but {len(SERIES)} series colours")
    plt.rcParams.update({"font.size": 9, "axes.edgecolor": MUTED, "axes.labelcolor": INK2,
                         "xtick.color": MUTED, "ytick.color": MUTED, "text.color": INK})
    ncol = min(3, len(tests))
    nrow = -(-len(tests) // ncol)
    fig, axes = plt.subplots(nrow, ncol, figsize=(5.2 * ncol, 4.2 * nrow + 0.8), facecolor=SURFACE,
                             squeeze=False)
    axes = axes.ravel()
    for ax in axes[len(tests):]:
        ax.set_visible(False)
    missing = []
    for ax, test in zip(axes, tests):
        ax.set_facecolor(SURFACE)
        unit = "?"
        for color, cfg in zip(SERIES, cfgs):  # fixed order: colour follows the config
            p = pooled(results, cfg, load, test)
            if p is None:
                missing.append(f"{cfg}/{load}/{test}")
                continue
            v, unit, nruns = p
            v = np.sort(v)
            exceed = 1.0 - np.arange(1, len(v) + 1) / len(v)
            keep = exceed > 0  # the max has nothing above it on a log axis
            ax.step(v[keep], exceed[keep], where="post", color=color, linewidth=1.6,
                    label=f"{cfg} ({nruns} runs)")
        for q, name in QUANTILES:
            ax.axhline(q, color=GRID, linewidth=0.8, zorder=0)
            ax.text(1.0, q, f" {name}", transform=ax.get_yaxis_transform(), va="center",
                    color=MUTED, fontsize=8)
        ax.set_xscale("log")
        ax.xaxis.set_major_formatter(matplotlib.ticker.LogFormatter())  # plain numbers;
        ax.xaxis.set_minor_formatter(matplotlib.ticker.LogFormatter())  # minors only if < ~1 decade
        ax.set_yscale("log")
        ax.set_ylim(top=1.0)
        ax.spines[["top", "right"]].set_visible(False)
        ax.set_title(test, loc="left", fontsize=10, color=INK)
        ax.set_xlabel(unit)
    for ax in axes[::ncol]:
        ax.set_ylabel("fraction of samples slower than x")
    h, lab = axes[0].get_legend_handles_labels()
    fig.legend(h, lab, loc="lower center", ncol=4, frameon=False, fontsize=8)
    fig.suptitle(f"Latency tails per configuration, {load}", x=0.01, ha="left", fontsize=12, color=INK)
    fig.tight_layout(rect=(0, 0.6 / fig.get_figheight(), 1, 1 - 0.5 / fig.get_figheight()))
    fig.savefig(out, dpi=150, facecolor=SURFACE)
    for m in missing:  # absence must be explained, not silent (nosmt has no ctxswitch_2_6)
        print(f"missing: {m}", file=sys.stderr)
    print(f"-> {out}")


if __name__ == "__main__":
    if len(sys.argv) < 5:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:])
