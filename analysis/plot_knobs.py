#!/usr/bin/env python3
"""Figure: per-knob marginal contribution (§11), one heatmap per load.

Usage: plot_knobs.py [DELTAS_CSV] [OUT.png] [METRIC]
  defaults: results/deltas.csv  docs/imgs/knob_deltas_p99.9.png  p99.9

Columns are the cumulative steps of configs/matrix.json (plus the spot row),
rows are tests. A cell is coloured by log2(after / before) of the run-median
percentile: blue = the knob made it faster, red = slower, clipped at 2x.
A step that fails the §3.6 range test (|delta| <= run-to-run spread) is
drawn grey with its value in muted text: it has not been shown to differ.
A blank hatched cell has no counterpart (ctxswitch 2-6 doesn't exist under nosmt).
"""
import json
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap, Normalize

INK, INK2, MUTED, GRID, SURFACE, NEUTRAL = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#fcfcfb", "#f0efec"
DIVERGE = LinearSegmentedColormap.from_list(
    "knob", ["#184f95", "#2a78d6", NEUTRAL, "#e34948", "#a32b2a"])  # faster ... slower
CLIP = 1.0  # log2 units: 2x either way saturates

ROWS = [  # (test, label), grouped by §2 class
    ("sched_latency", "wakeup latency"),
    ("syscall_getppid", "getppid()"),
    ("syscall_mono", "clock_gettime MONO"),
    ("syscall_mono_raw", "clock_gettime MONO_RAW"),
    ("syscall_empty", "empty loop (timer cost)"),
    ("ctxswitch_2_6", "ctx switch, SMT sibling"),
    ("ctxswitch_2_2", "ctx switch, same CPU"),
    ("ctxswitch_2_3", "ctx switch, cross-core"),
    ("ipc_eventfd_2_3", "eventfd wakeup"),
    ("ipc_udp_2_3", "UDP loopback RTT"),
    ("memlat_16K_4K", "memory: L1 (16K)"),
    ("memlat_128K_4K", "memory: L2 (128K)"),
    ("memlat_2048K_4K", "memory: L3 (2M)"),
    ("memlat_65536K_4K", "memory: DRAM, 4K pages"),
    ("memlat_65536K_2M", "memory: DRAM, 2M pages"),
]
KNOB = {  # what each step adds, as shown in the column header
    "governor": "governor\nturbo off",
    "cstates": "C-states\nlimited",
    "isolate": "isolcpus\nnohz_full",
    "irqaffinity": "irqaffinity",
    "nosmt": "nosmt",
    "nomitigations": "mitigations\n=off",
    "rt": "PREEMPT_RT",
    "spot-nomitigations": "spot: base\n+ mitig.=off",
}


def steps():
    cfgs = json.load(open("configs/matrix.json"))["configs"]
    return [c["name"] for c in cfgs if c["id"] != 0]


def panel(ax, d, load, cols, metric):
    norm = Normalize(-CLIP, CLIP)
    for r, (test, _) in enumerate(ROWS):
        for c, to in enumerate(cols):
            x = c + (0.25 if to.startswith("spot") else 0)  # set the spot column apart
            q = d[(d["to"] == to) & (d["load"] == load) & (d["test"] == test) & (d["metric"] == metric)]
            if q.empty:
                ax.add_patch(plt.Rectangle((x, r), 1, 1, facecolor=SURFACE, edgecolor=GRID,
                                           hatch="////", linewidth=0))
                continue
            q = q.iloc[0]
            ratio = np.log2(q["after"] / q["before"]) if q["before"] > 0 and q["after"] > 0 else 0.0
            ok = bool(q["conclusive"])
            face = DIVERGE(norm(np.clip(ratio, -CLIP, CLIP))) if ok else NEUTRAL
            ax.add_patch(plt.Rectangle((x, r), 1, 1, facecolor=face, edgecolor=SURFACE, linewidth=2))
            txt = f"{q['delta_pct']:+.0f}%" if abs(q["delta_pct"]) < 999 else f"{q['after'] / q['before']:.0f}x"
            dark = ok and abs(ratio) > 0.55
            ax.text(x + 0.5, r + 0.5, txt, ha="center", va="center", fontsize=7.5,
                    color=SURFACE if dark else (INK if ok else MUTED),
                    fontweight="bold" if ok else "normal")
    ax.set_xlim(0, len(cols) + 0.25)
    ax.set_ylim(len(ROWS), 0)
    ax.set_xticks([c + 0.5 + (0.25 if t.startswith("spot") else 0) for c, t in enumerate(cols)])
    ax.set_xticklabels([KNOB.get(t, t) for t in cols], fontsize=8, color=INK2)
    ax.xaxis.tick_top()
    ax.tick_params(length=0)
    ax.spines[:].set_visible(False)
    ax.set_title(load, loc="left", fontsize=11, color=INK, pad=34)


def main(deltas, out, metric):
    d = pd.read_csv(deltas)
    if metric not in set(d["metric"]):
        sys.exit(f"{metric} not in {deltas} (have {sorted(set(d['metric']))})")
    cols = steps()
    plt.rcParams.update({"font.size": 9, "text.color": INK})
    fig, axes = plt.subplots(1, 2, figsize=(15, 7.8), facecolor=SURFACE, sharey=True)
    for ax, load in zip(axes, ("idle", "loaded")):
        ax.set_facecolor(SURFACE)
        panel(ax, d, load, cols, metric)
    axes[0].set_yticks([r + 0.5 for r in range(len(ROWS))])
    axes[0].set_yticklabels([label for _, label in ROWS], color=INK2)
    n = d[d["metric"] == metric]
    fig.suptitle(f"What each knob changes: {metric} latency, step over step "
                 f"({n['conclusive'].sum()} of {len(n)} steps exceed run-to-run spread)",
                 x=0.01, ha="left", fontsize=12, color=INK)
    cax = fig.add_axes((0.74, 0.075, 0.2, 0.016))
    cb = fig.colorbar(plt.cm.ScalarMappable(Normalize(-CLIP, CLIP), DIVERGE), cax=cax,
                      orientation="horizontal")
    cb.set_ticks([-1, 0, 1], labels=["2x faster", "no change", "2x slower"])
    cb.outline.set_visible(False)
    cax.tick_params(labelsize=8, colors=INK2, length=0)
    fig.text(0.01, 0.02, "Each cell: median of 3 runs (reboot between) of this config vs the previous one. "
             "Grey cells: |delta| <= spread of the 3 runs, not shown to differ (§3.6). "
             "\nHatched: no such test in that config. Absolute numbers are a laptop's; "
             "the deltas are the result. Columns are cumulative except the spot check.",
             color=MUTED, fontsize=8)
    fig.subplots_adjust(left=0.13, right=0.99, top=0.82, bottom=0.12, wspace=0.05)
    fig.savefig(out, dpi=150, facecolor=SURFACE)
    print(f"-> {out}")


if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[0] if a else "results/deltas.csv",
         a[1] if len(a) > 1 else "docs/imgs/knob_deltas_p99.9.png",
         a[2] if len(a) > 2 else "p99.9")
