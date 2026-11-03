#!/usr/bin/env python3
"""Figure: a wakeup-latency run with an SMI stall, lined up against the SMI counter.

Usage: plot_smi_stall.py RUN_DIR OUT.png
  RUN_DIR holds sched_latency.bin and sched_latency.monitor.csv.
The SMI window is the monitor interval in which MSR_SMI_COUNT changed.
"""
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

SERIES = "#2a78d6"
INK, INK2, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#fcfcfb"
BAND = "#e1e0d9"


def main(run_dir, out):
    s = np.fromfile(f"{run_dir}/sched_latency.bin", dtype=[("t", "<i8"), ("v", "<i8")])
    mon = pd.read_csv(f"{run_dir}/sched_latency.monitor.csv")
    t0 = s["t"][0]
    t_s = (s["t"] - t0) / 1e9
    us = s["v"] / 1e3

    step = np.flatnonzero(np.diff(mon["smi_count"].to_numpy()) > 0)
    if len(step) == 0:
        sys.exit("no SMI counter change in this run")
    i = step[0]
    w_lo, w_hi = (mon["t_ns"][i] - t0) / 1e9, (mon["t_ns"][i + 1] - t0) / 1e9
    n_smi = int(mon["smi_count"][i + 1] - mon["smi_count"][i])
    med = np.median(us)

    plt.rcParams.update({"font.size": 10, "axes.edgecolor": MUTED, "axes.labelcolor": INK2,
                         "xtick.color": MUTED, "ytick.color": MUTED, "text.color": INK})
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(10, 7), facecolor=SURFACE,
                                 gridspec_kw={"height_ratios": [1, 1.2], "hspace": 0.45})

    for a in (a1, a2):
        a.set_facecolor(SURFACE)
        a.set_yscale("log")
        a.grid(axis="y", color=GRID, linewidth=0.6)
        a.spines[["top", "right"]].set_visible(False)
        a.set_ylabel("wakeup latency (µs)")

    # Whole run
    a1.scatter(t_s, us, s=2, color=SERIES, linewidths=0)
    a1.axvspan(w_lo, w_hi, color=BAND, zorder=0)
    a1.set_xlim(0, t_s[-1])
    a1.set_xlabel("time into run (s)")
    a1.set_title(f"100,000 wakeups at 1 kHz, CPU 2, SCHED_FIFO 90 — median {med:.1f} µs",
                 loc="left", fontsize=11, color=INK)
    big = us.argmax()
    a1.annotate(f"max {us[big]:,.0f} µs", (t_s[big], us[big]), xytext=(8, -2),
                textcoords="offset points", color=INK2, va="center")

    # Zoom on the stall
    c = t_s[big]
    m = (t_s > c - 0.012) & (t_s < c + 0.012)
    zx = (t_s[m] - c) * 1e3
    a2.axvspan((w_lo - c) * 1e3, (w_hi - c) * 1e3, color=BAND, zorder=0)
    a2.plot(zx, us[m], color=SERIES, linewidth=1, zorder=2)
    a2.scatter(zx, us[m], s=22, color=SERIES, edgecolors=SURFACE, linewidths=1.5, zorder=3)
    a2.set_xlim(-12, 12)
    a2.set_xlabel("time relative to worst sample (ms) — one sample per 1 ms deadline")
    a2.set_title(f"Zoom: shaded = the 100 ms monitor interval in which MSR_SMI_COUNT rose by {n_smi}",
                 loc="left", fontsize=11, color=INK)
    for x, y in zip(zx, us[m]):
        if y > 100:
            a2.annotate(f"{y:,.0f}", (x, y), xytext=(0, 7), textcoords="offset points",
                        ha="center", color=INK2, fontsize=9)
    a2.text(0.01, 0.06, f"typical wake: {med:.1f} µs", transform=a2.transAxes, color=INK2)
    a2.text(0.99, 0.06, "each stall is followed by catch-up samples:\n"
            "deadlines are absolute, so a late wake counts against every deadline it missed",
            transform=a2.transAxes, ha="right", color=MUTED, fontsize=8.5)

    fig.savefig(out, dpi=150, bbox_inches="tight", facecolor=SURFACE)
    print(f"wrote {out}: SMI window {w_lo:.3f}-{w_hi:.3f} s, +{n_smi} SMIs, max {us.max():.0f} us")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
