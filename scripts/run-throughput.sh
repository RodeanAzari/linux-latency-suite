#!/bin/sh
# PREEMPT_RT's throughput cost (§6, §8 Phase F): fixed-duration stress-ng
# stressors, 2 workers each on the housekeeping CPUs 0,1, into <outdir>.
# Meant for configs nomitigations and rt: same cmdline, only the kernel differs.
# Runtime setup (profile, governor, turbo) is the caller's job (collect.sh).
#
# Per stressor: <stressor>.yaml (stress-ng metrics, bogo-ops/s) and two rows of
# throughput.csv (before/after: cTDP level, CPU 0/1 APERF/MPERF, package
# temperature and throttle count), which analysis/clock_guard.py checks.
# A missing or failing stressor is logged to <outdir>/FAILED; the run carries on.
#
# Usage (T490, repo root): scripts/run-throughput.sh <outdir>
set -eu
export PATH="$PATH:/usr/sbin:/sbin"
O=$1
DUR=${DUR:-60}		# s per stressor
COOL=${COOL:-20}	# s idle before each, so each starts near the same temperature
STRESSORS="cpu switch pipe getpid vm"
CPU=/sys/devices/system/cpu
mkdir -p "$O"

cleanup() { sudo pkill -x stress-ng 2>/dev/null || true; }
trap cleanup EXIT

sudo modprobe msr
zone=
for z in /sys/class/thermal/thermal_zone*; do
	[ "$(cat "$z/type")" = x86_pkg_temp ] && zone=$z
done
[ -n "$zone" ] || { echo "no x86_pkg_temp thermal zone" | tee -a "$O/FAILED"; exit 1; }

snap() {	# snap <stressor> <phase> <rc>: one throughput.csv row
	printf '%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n' "$1" "$2" "$3" \
		$(($(sudo rdmsr -p 0 -c 0x64b) & 3)) \
		"$(sudo rdmsr -p 0 -d 0xe8)" "$(sudo rdmsr -p 0 -d 0xe7)" \
		"$(sudo rdmsr -p 1 -d 0xe8)" "$(sudo rdmsr -p 1 -d 0xe7)" \
		"$(cat "$zone/temp")" "$(cat $CPU/cpu0/thermal_throttle/package_throttle_count)" \
		>> "$O/throughput.csv"
}

stress-ng --version > "$O/stress-ng.version"
avail=$(stress-ng --stressors)
echo "stressor,phase,rc,tdp_level,aperf0,mperf0,aperf1,mperf1,pkg_temp_mc,pkg_throttle" > "$O/throughput.csv"
for s in $STRESSORS; do
	if ! echo "$avail" | tr ' ' '\n' | grep -qx "$s"; then
		echo "stressor $s not in this stress-ng" >> "$O/FAILED"; continue
	fi
	extra=
	[ "$s" = vm ] && extra="--vm-bytes 256M"
	sleep "$COOL"
	echo "[$(date +%T)] $s"
	snap "$s" before ""
	rc=0
	stress-ng --taskset 0,1 --"$s" 2 $extra --timeout "${DUR}s" \
		--metrics-brief --yaml "$O/$s.yaml" > "$O/$s.log" 2>&1 || rc=$?
	snap "$s" after "$rc"
	[ "$rc" = 0 ] || echo "rc=$rc stress-ng --$s" >> "$O/FAILED"
done
echo "[$(date +%T)] throughput done: $O"
