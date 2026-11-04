#!/usr/bin/env python3
"""Figure: dependent-load latency vs working-set size, 4 KiB vs 2 MiB pages.

Usage: plot_memlat.py SWEEP_DIR OUT.png
  SWEEP_DIR holds memlat_<size>K_<page>.bin + .json pairs (scripts/sweep-memlat.sh).
Each point is the median per-load latency of one run (p50 of v_ns / loads_per_sample).
Cache sizes are the i5-8365U's; the clock is read from the sidecars.
"""
import glob
import json
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

SERIES = {"4K": "#2a78d6", "2M": "#eb6834"}
LABEL = {"4K": "4 KiB pages", "2M": "2 MiB pages"}
INK, INK2, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#fcfcfb"
LEVELS = [(32 << 10, "L1d 32K"), (256 << 10, "L2 256K"), (6 << 20, "L3 6M")]
SAMPLE = np.dtype([("t_ns", "<i8"), ("v_ns", "<i8")])


def load(sweep_dir):
    runs = {"4K": [], "2M": []}
    khz = set()
    for side in glob.glob(f"{sweep_dir}/memlat_*.json"):
        j = json.load(open(side))
        p = j["params"]
        v = np.fromfile(side[:-5] + ".bin", dtype=SAMPLE)["v_ns"] / p["loads_per_sample"]
        runs[p["page"]].append((p["size_bytes"], np.median(v)))
        khz.add(round(j["env_after"]["cur_khz"] / 1e5) * 100)  # MHz, to 100
        profile = j.get("platform_profile", "?")
    return {k: sorted(r) for k, r in runs.items()}, khz, profile


def fmt_size(b):
    return f"{b >> 20}M" if b >= 1 << 20 else f"{b >> 10}K"


def main(sweep_dir, out):
    runs, khz, profile = load(sweep_dir)
    if len(khz) != 1:
        sys.exit(f"runs at different clocks {sorted(khz)} MHz: not one sweep")
    mhz = khz.pop()

    plt.rcParams.update({"font.size": 10, "axes.edgecolor": MUTED, "axes.labelcolor": INK2,
                         "xtick.color": MUTED, "ytick.color": MUTED, "text.color": INK})
    fig, ax = plt.subplots(figsize=(10, 5.6), facecolor=SURFACE)
    ax.set_facecolor(SURFACE)
    ax.set_xscale("log", base=2)
    ax.set_yscale("log")
    ax.grid(axis="y", which="major", color=GRID, linewidth=0.6)
    ax.spines[["top", "right"]].set_visible(False)

    for size, name in LEVELS:
        ax.axvline(size, color=MUTED, linewidth=0.8, linestyle=(0, (3, 3)), zorder=0)
        ax.text(size * 1.06, 300, name, color=INK2, fontsize=9, va="top")

    for page in ("4K", "2M"):
        x, y = zip(*runs[page])
        ax.plot(x, y, color=SERIES[page], linewidth=2, marker="o", markersize=5,
                markeredgecolor=SURFACE, markeredgewidth=1.5, label=LABEL[page], zorder=3)
        ax.annotate(LABEL[page], (x[-1], y[-1]), xytext=(8, 0), textcoords="offset points",
                    color=INK, va="center", fontsize=9)

    # Plateau labels in cycles, from the 4K curve
    pts = dict(runs["4K"])
    for size, where in ((16 << 10, "L1"), (128 << 10, "L2")):
        ns = pts[size]
        ax.annotate(f"{ns:.1f} ns · {ns * mhz / 1000:.0f} cycles", (size, ns),
                    xytext=(0, -16), textcoords="offset points", ha="center", color=INK2,
                    fontsize=9)

    # Page-walk gap at the largest size
    big = max(pts)
    y4, y2 = pts[big], dict(runs["2M"])[big]
    ax.annotate("", (big, y2), xytext=(big, y4),
                arrowprops={"arrowstyle": "<->", "color": INK2, "linewidth": 1})
    ax.annotate(f"page walks: +{y4 - y2:.0f} ns (+{100 * (y4 / y2 - 1):.0f}%)",
                (big, y2), xytext=(0, -22), textcoords="offset points",
                ha="right", va="center", color=INK, fontsize=9)

    # Near L2 capacity, 4K page frames land in a 4-way physically indexed L2
    # differently each run, so conflict misses (and latency) vary run to run.
    ax.annotate("near L2 capacity: varies run to run\n(physical page placement, 4-way L2)",
                (192 << 10, pts[192 << 10]), xytext=(-14, 34), textcoords="offset points",
                ha="right", va="bottom", color=INK2, fontsize=8,
                bbox={"facecolor": SURFACE, "edgecolor": "none", "pad": 1},
                arrowprops={"arrowstyle": "-", "color": MUTED, "linewidth": 0.8})

    sizes = [s for s, _ in runs["4K"] if (s & (s - 1)) == 0 and s >= 4096]
    ax.set_xticks(sizes[::2])
    ax.set_xticklabels([fmt_size(s) for s in sizes[::2]])
    ax.minorticks_off()
    ax.set_yticks([1, 3, 10, 30, 100, 300])
    ax.set_yticklabels(["1", "3", "10", "30", "100", "300"])
    ax.set_ylim(1.5, 320)
    ax.set_xlabel("working set (random pointer chase, 64 B lines)")
    ax.set_ylabel("latency per dependent load (ns, p50)")
    ax.set_title(f"Memory hierarchy of the T490 (i5-8365U), clock fixed at {mhz} MHz",
                 loc="left", fontsize=12, color=INK)
    ax.legend(loc="upper left", frameon=False, bbox_to_anchor=(0, 0.93))
    fig.text(0.01, 0.01, f"Each point: median of 100,000 samples × 256 dependent loads, "
             f"CPU 2, SCHED_FIFO 90, turbo off, platform_profile={profile}.",
             color=MUTED, fontsize=8)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(out, dpi=160, facecolor=SURFACE)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(*sys.argv[1:])
