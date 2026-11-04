#!/bin/sh
# Phase D cross-check, RT kernel only (stock Debian lacks HWLAT_TRACER).
#
# The kernel's hwlat tracer spins on CPU 1 with interrupts disabled, so it sees
# only stalls the OS cannot cause: SMIs and hardware. hwgap spins on CPU 2 at
# the same time. SMIs stop every CPU at once, so each SMI should appear in
# both, at the same moment with about the same duration.
#
# hwlat runs width 900 ms per 1 s window, so it covers 90% of the time.
# Usage (T490, repo root, booted into the -rt kernel):
#   scripts/validate-hwgap-hwlat.sh <outdir> [minutes]
set -eu
export PATH="$PATH:/usr/sbin:/sbin"
O=$1
MIN=${2:-20}
T=/sys/kernel/tracing
case $(uname -r) in *-rt-*) ;; *) echo "not an RT kernel: $(uname -r)" >&2; exit 1 ;; esac
mkdir -p "$O"

cleanup() {
	echo 0 | sudo tee $T/tracing_on >/dev/null
	echo nop | sudo tee $T/current_tracer >/dev/null
	echo ff | sudo tee $T/tracing_cpumask >/dev/null
}
trap cleanup EXIT
sudo modprobe msr
echo nop | sudo tee $T/current_tracer >/dev/null
echo 2 | sudo tee $T/tracing_cpumask >/dev/null              # CPU 1 only
echo 10 | sudo tee $T/tracing_thresh >/dev/null              # us
echo 1000000 | sudo tee $T/hwlat_detector/window >/dev/null  # us
echo 900000 | sudo tee $T/hwlat_detector/width >/dev/null    # us
echo none | sudo tee $T/hwlat_detector/mode >/dev/null 2>&1 || true
sudo sh -c "echo > $T/trace"
# Record the offset between the trace clock and CLOCK_MONOTONIC for matching.
sudo sh -c "echo mono > $T/trace_clock"
echo hwlat | sudo tee $T/current_tracer >/dev/null
echo 1 | sudo tee $T/tracing_on >/dev/null

sudo harness/build/hwgap -c 2 -m 0 -d $((MIN * 60)) -o "$O"

echo 0 | sudo tee $T/tracing_on >/dev/null
sudo cat $T/trace > "$O/hwlat_trace.txt"
grep -c "inner/outer" "$O/hwlat_trace.txt" || true
