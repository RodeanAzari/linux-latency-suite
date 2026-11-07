#!/bin/sh
# Demo (for an asciinema recording): the clock guard replayed on the run it
# caught, cTDP episode 4 (irqaffinity round 2, 2026-11-05), next to its rerun.
# Reads saved results only; changes nothing.
#
# Usage (T490, repo root): scripts/demo-clock-guard.sh
# Record:  asciinema rec -i 1 -c scripts/demo-clock-guard.sh guard.cast
set -eu
BAD=results/superseded-ctdp/irqaffinity/run2-20261105T234256
GOOD=results/irqaffinity/run2
[ -d "$BAD" ] && [ -d "$GOOD" ] || { echo "needs $BAD and $GOOD (T490 only)" >&2; exit 1; }

show() { printf '\n$ %s\n' "$*"; sleep 1; }

echo "Run irqaffinity/run2, loaded half. sysfs said platform_profile=performance throughout."
python3 - "$BAD" "$GOOD" <<'EOF'
import sys
import pandas as pd
sys.path.insert(0, "analysis")
import summarize

bad, good = sys.argv[1:]
m = pd.read_csv(f"{bad}/loaded/sched_latency.monitor.csv")
k = m.index[m.tdp_level != m.tdp_level.iloc[0]][0]
r = m.loc[k]
print(f"The monitor log, mid-test: cTDP level {int(m.tdp_level.iloc[0])} -> {int(r.tdp_level)} "
      f"at {r.pkg_temp_mc / 1000:.0f} C, throttle counters unchanged.\n")
print(f"{'test (p50)':<22}{'that run':>12}{'rerun':>12}{'ratio':>8}{'clock then':>13}")
for t, name in (("syscall_getppid", "getppid() (before)"), ("memlat_16K_4K", "L1 load"),
                ("ctxswitch_2_2", "ctx switch")):
    b, g = summarize.one(f"{bad}/loaded/{t}.bin"), summarize.one(f"{good}/loaded/{t}.bin")
    print(f"{name:<22}{b['p50']:>9.3g} {b['unit'].split('/')[0]:<2}{g['p50']:>9.3g} {g['unit'].split('/')[0]:<2}"
          f"{b['p50'] / g['p50']:>7.2f}x{b['busy_mhz']:>9.0f} MHz")
EOF

show python3 analysis/clock_guard.py "$BAD" 0 1600
out=$(python3 analysis/clock_guard.py "$BAD" 0 1600) && rc=0 || rc=$?
echo "$out" | grep -v env_ | head -6
echo "... $(echo "$out" | wc -l) problems, exit $rc: run set aside, retried on the next boot"

show python3 analysis/clock_guard.py "$GOOD" 0 1600
python3 analysis/clock_guard.py "$GOOD" 0 1600 && echo "0 problems, exit 0: the rerun is the one in the results"
