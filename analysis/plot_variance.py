#!/usr/bin/env python3
"""Figure: effect size vs run-to-run spread for every step (§3.6).

Usage: plot_variance.py [DELTAS_CSV] [OUT.png]
  defaults: results/deltas.csv  docs/imgs/variance_vs_effect.png

One point per (step, load, test, percentile) in deltas.csv, both axes as a
percentage of the "before" median. Points above the diagonal changed by more
than the configs' runs disagree with each other (conclusive); below it, the
step has not been shown to change anything.
"""
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

INK, INK2, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#fcfcfb"
SERIES = {"p50": "#2a78d6", "p99": "#eb6834", "p99.9": "#1baf7a"}
MARKER = {"p50": "o", "p99": "s", "p99.9": "^"}  # identity is never colour alone
FLOOR = 0.1  # %: zero spread (identical medians at csv precision) is drawn here


def main(deltas, out):
    d = pd.read_csv(deltas)
    d = d[d["before"] > 0]
    d = d.assign(eff=(100 * d["delta"].abs() / d["before"]).clip(lower=FLOOR),
                 spr=(100 * d["spread"] / d["before"]).clip(lower=FLOOR))
    plt.rcParams.update({"font.size": 10, "axes.edgecolor": MUTED, "axes.labelcolor": INK2,
                         "xtick.color": MUTED, "ytick.color": MUTED, "text.color": INK})
    fig, ax = plt.subplots(figsize=(8.5, 7), facecolor=SURFACE)
    ax.set_facecolor(SURFACE)
    ax.set_xscale("log")
    ax.set_yscale("log")
    lo, hi = FLOOR * 0.8, max(d["eff"].max(), d["spr"].max()) * 1.5
    ax.fill_between([lo, hi], [lo, hi], [hi, hi], color="#f0efec", zorder=0, linewidth=0)
    ax.plot([lo, hi], [lo, hi], color=MUTED, linewidth=1, linestyle=(0, (3, 3)), zorder=1)
    ax.text(hi / 1.3, hi / 1.6, "conclusive: change > spread", ha="right", va="top", color=INK2, fontsize=9)
    ax.text(hi / 1.3, lo * 1.6, "not shown to differ", ha="right", va="bottom", color=INK2, fontsize=9)
    for m in ("p50", "p99", "p99.9"):
        q = d[d["metric"] == m]
        ax.scatter(q["spr"], q["eff"], s=22, marker=MARKER[m], color=SERIES[m], alpha=0.75,
                   edgecolors=SURFACE, linewidths=0.6, zorder=3,
                   label=f"{m}  ({q['conclusive'].sum()}/{len(q)} conclusive)")
    ax.set_xlim(lo, hi)
    ax.set_ylim(lo, hi)
    ax.grid(which="major", color=GRID, linewidth=0.6)
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_xlabel("run-to-run spread (max - min of 3 runs, % of before)")
    ax.set_ylabel("|change| from the knob (% of before)")
    k = d["conclusive"].sum()
    ax.set_title(f"{k} of {len(d)} knob effects ({100 * k / len(d):.0f}%) exceed reboot-to-reboot spread",
                 loc="left", fontsize=12, color=INK)
    ax.legend(loc="upper left", frameon=False)
    fig.text(0.01, 0.01, f"{len(d)} step comparisons from results/deltas.csv; "
             f"values under {FLOOR}% are drawn at {FLOOR}%.", color=MUTED, fontsize=8)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(out, dpi=150, facecolor=SURFACE)
    print(f"-> {out}")


if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[0] if a else "results/deltas.csv", a[1] if len(a) > 1 else "docs/imgs/variance_vs_effect.png")
