#!/bin/sh
# Phase D: what the platform does under sustained §4.2 load.
#
# A 20-min loaded run stepped down at ~9.5 min: 3.1 -> 2.8 GHz, 97 -> 88 C,
# thermal throttling stopped. This logs, every 5 s, everything that could
# explain such a step: temperature, CPU 2's clock, throttle count, package
# power (from the RAPL energy counter) and both RAPL power limits (MSR and
# the MMIO copy that firmware can change at runtime).
# Usage (T490, repo root): scripts/phase-d-sustained-load.sh <out.csv> [minutes]
set -eu
export PATH="$PATH:/usr/sbin:/sbin"
OUT=$1
MIN=${2:-15}
R=/sys/class/powercap/intel-rapl:0
M=/sys/class/powercap/intel-rapl-mmio:0
P=/sys/firmware/acpi/platform_profile
old=$(cat $P)
cleanup() {
	sudo pkill -x stress-ng 2>/dev/null || true
	echo "$old" | sudo tee $P >/dev/null
}
trap cleanup EXIT
echo performance | sudo tee $P >/dev/null
mkdir -p "$(dirname "$OUT")"

rd() { sudo cat "$1"; }
temp() { for z in /sys/class/thermal/thermal_zone*; do
	[ "$(cat $z/type)" = x86_pkg_temp ] && cat $z/temp && return; done; }

stress-ng --taskset 0,1,4,5 --cpu 4 --io 2 --vm 2 --vm-bytes 1G --timeout $((MIN * 60 + 10))s \
	--quiet &
echo "t_s,pkg_temp_mc,cpu2_khz,pkg_throttle,pkg_w,msr_pl1_uw,msr_pl2_uw,mmio_pl1_uw,mmio_pl2_uw" >"$OUT"
e0=$(rd $R/energy_uj)
t0=$(date +%s)
i=0
while [ $i -lt $((MIN * 12)) ]; do
	sleep 5
	e1=$(rd $R/energy_uj)
	echo "$(($(date +%s) - t0)),$(temp),$(cat /sys/devices/system/cpu/cpu2/cpufreq/scaling_cur_freq),$(cat /sys/devices/system/cpu/cpu2/thermal_throttle/package_throttle_count),$(((e1 - e0) / 5000000)),$(rd $R/constraint_0_power_limit_uw),$(rd $R/constraint_1_power_limit_uw),$(rd $M/constraint_0_power_limit_uw),$(rd $M/constraint_1_power_limit_uw)" >>"$OUT"
	e0=$e1
	i=$((i + 1))
done
wait
