#!/bin/sh
# Working-set sweep for memlat: 4K pages at every size, 2M pages from 2M up,
# interleaved so any drift during the sweep cannot line up with page size.
#
# Clock is fixed at 1.6 GHz: platform_profile=performance (cTDP nominal),
# performance governor, turbo off. All three are restored on exit.
#
# Usage (T490, repo root): scripts/sweep-memlat.sh [outdir]
set -eu
export PATH="$PATH:/usr/sbin:/sbin"
O=${1:-results/validation/memlat-sweep}
CPU=/sys/devices/system/cpu
PROFILE=/sys/firmware/acpi/platform_profile
old_profile=$(cat $PROFILE)
old_gov=$(cat $CPU/cpu0/cpufreq/scaling_governor)
old_turbo=$(cat $CPU/intel_pstate/no_turbo)

restore() {
	echo "$old_profile" | sudo tee $PROFILE >/dev/null
	sudo cpupower -c all frequency-set -g "$old_gov" >/dev/null
	echo "$old_turbo" | sudo tee $CPU/intel_pstate/no_turbo >/dev/null
	sudo sysctl -q vm.nr_hugepages=0
}
trap restore EXIT
echo performance | sudo tee $PROFILE >/dev/null
sudo cpupower -c all frequency-set -g performance >/dev/null
echo 1 | sudo tee $CPU/intel_pstate/no_turbo >/dev/null
sudo sysctl -q vm.nr_hugepages=160
sudo modprobe msr

for s in 4K 8K 16K 24K 32K 40K 48K 64K 96K 128K 192K 256K 384K 512K 768K 1M 1536K \
	 2M 3M 4M 5M 6M 8M 12M 16M 32M 64M 128M 256M; do
	sudo harness/build/memlat -s $s -o "$O"
	case $s in
	2M|4M|6M|8M|12M|16M|32M|64M|128M|256M) sudo harness/build/memlat -H -s $s -o "$O" ;;
	esac
done
