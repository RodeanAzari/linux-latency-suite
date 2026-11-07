#!/usr/bin/env python3
"""Fail a run whose CPU clock was not the one the config asked for.

Usage: clock_guard.py RUN_DIR TDP_LEVEL [BASE_MHZ]
  RUN_DIR    results/<config>/run<r>  (checks every */<test>.json in it), or
             results/throughput/<config>/run<r>  (checks throughput.csv: every
             row's cTDP level, and with BASE_MHZ the busy clock of CPUs 0,1
             during the `cpu` stressor; the blocking stressors are exempt
             for the same reason as sched_latency)
  TDP_LEVEL  CONFIG_TDP_CONTROL level read at setup; every monitor row and
             sidecar snapshot must still show it
  BASE_MHZ   fixed-clock rows only (no_turbo=1): each test's APERF/MPERF busy
             clock must be within 3% of it. sched_latency is exempt: it
             sleeps between wakeups and reads ~400 MHz at a correct setting,
             and the tdp_level monitor covers it.

The T490 firmware has switched the package to cTDP level 1 (800 MHz with
turbo off) for ~3 minutes while platform_profile still read "performance",
halving every clock-bound result (README, Limitations). Prints one line per problem
and exits 1 if there are any.
"""
import glob
import json
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from summarize import TSC_MHZ, busy_mhz  # noqa: E402


def throughput_problems(csv, level, base):
    out = []
    t = pd.read_csv(csv)
    if t.empty:
        return [f"{csv}: no rows"]
    for _, r in t[t.tdp_level != level].iterrows():
        out.append(f"throughput {r.stressor} {r.phase}: tdp_level {r.tdp_level}, want {level}")
    cpu = t[t.stressor == "cpu"].set_index("phase")
    if base and len(cpu) == 2:
        for c in (0, 1):
            da = cpu.at["after", f"aperf{c}"] - cpu.at["before", f"aperf{c}"]
            dm = cpu.at["after", f"mperf{c}"] - cpu.at["before", f"mperf{c}"]
            mhz = TSC_MHZ * da / dm if dm > 0 else float("nan")
            if not abs(mhz - base) <= 0.03 * base:  # NaN fails too
                out.append(f"throughput cpu: CPU {c} busy clock {mhz:.0f} MHz, want {base}")
    elif base:
        out.append("throughput: no before/after rows for the cpu stressor, clock unchecked")
    return out


def problems(run_dir, level, base):
    csv = os.path.join(run_dir, "throughput.csv")
    if os.path.exists(csv):
        return throughput_problems(csv, level, base)
    out = []
    sidecars = sorted(glob.glob(os.path.join(run_dir, "*", "*.json")))
    if not sidecars:
        out.append(f"{run_dir}: no sidecars")
    for j in sidecars:
        name = os.path.relpath(j, run_dir)[:-5]
        s = json.load(open(j))
        m = pd.read_csv(j[:-5] + ".monitor.csv")
        if "tdp_level" not in m:
            out.append(f"{name}: monitor has no tdp_level column")
        else:
            bad = m[m.tdp_level != level]
            if len(bad):
                out.append(f"{name}: tdp_level {sorted(int(x) for x in bad.tdp_level.unique())} in "
                           f"{len(bad)}/{len(m)} monitor rows, want {level}")
        for k in ("env_before", "env_after"):
            if s[k].get("tdp_level") != level:
                out.append(f"{name}: {k} tdp_level {s[k].get('tdp_level')}, want {level}")
        if base and not s["test"].startswith("sched_latency"):
            mhz = busy_mhz(s)
            if not abs(mhz - base) <= 0.03 * base:  # NaN fails too
                out.append(f"{name}: busy clock {mhz:.0f} MHz, want {base}")
    return out


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4):
        sys.exit(__doc__)
    p = problems(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]) if len(sys.argv) == 4 else 0)
    if p:
        print("\n".join(p))
    sys.exit(1 if p else 0)
