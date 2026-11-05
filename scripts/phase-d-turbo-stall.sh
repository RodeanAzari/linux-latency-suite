#!/bin/sh
# Phase D: the turbo-dependent ~14 us stalls (docs/platform.md).
#
# Short hwgap runs on CPU 3, idle, under one clock setting:
#   turbo    defaults: powersave, turbo on, platform_profile balanced
#   fixed    performance governor + profile, turbo off (1.6 GHz)
#   perfgov  performance governor + profile, turbo on
#   pair     like turbo, but hwgap on CPUs 2 and 3 at once, for
#            analysis/match_gaps.py (a package-wide stall hits both together)
#   cap38    pair, turbo on but max 3.8 GHz, the 3-4 active-core ratio
#            (MSR 0x1AD), so the active-core count never changes the clock
# Each run is 5 s with 10 s rest. On PREEMPT_RT a long FIFO spin on a CPU
# without nohz_full + rcu_nocbs starves rcuc/N and stalls RCU system-wide.
# Restores the defaults on exit.
# Usage (T490, repo root): scripts/phase-d-turbo-stall.sh <outdir> turbo|fixed|perfgov|pair|cap38
set -eu
export PATH="$PATH:/usr/sbin:/sbin"
O=$1
MODE=$2
P=/sys/devices/system/cpu
HG="sudo harness/build/hwgap -m 0 -d 5"

clock() { # governor profile no_turbo [max_khz]
	echo "$3" | sudo tee $P/intel_pstate/no_turbo >/dev/null # first: it bounds the max
	echo "$2" | sudo tee /sys/firmware/acpi/platform_profile >/dev/null
	sudo cpupower frequency-set -g "$1" -u "${4:-$(cat $P/cpu0/cpufreq/cpuinfo_max_freq)}" >/dev/null
}
trap 'clock powersave balanced 0' EXIT
sudo modprobe msr
case $MODE in
turbo | pair) clock powersave balanced 0 ;;
fixed) clock performance performance 1 ;;
perfgov) clock performance performance 0 ;;
cap38) clock powersave balanced 0 3800000 ;;
*) echo "unknown mode: $MODE" >&2; exit 2 ;;
esac
sleep 2
for i in 1 2 3; do
	if [ "$MODE" = pair ] || [ "$MODE" = cap38 ]; then
		$HG -c 2 -o "$O/r$i/2" >/dev/null &
		$HG -c 3 -o "$O/r$i/3" >/dev/null
		wait
	else
		$HG -c 3 -o "$O/r$i" >/dev/null
	fi
	sleep 10
done
