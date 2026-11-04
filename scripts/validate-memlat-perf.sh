#!/bin/sh
# Phase C: check memlat's latency plateaus against hardware counters.
#
# For each size, memlat runs at n=100k and n=300k under perf stat. Per-load
# event rates are (count_300k - count_100k) / (loads_300k - loads_100k),
# where loads = (warmup + samples) * 256 from the sidecar; the difference
# cancels setup (chain building, pre-faulting) exactly.
# Events are split into two groups of <=4 so nothing is multiplexed.
#
# Clock is fixed at 1.6 GHz: platform_profile=performance (cTDP nominal),
# performance governor, turbo off. All three are restored on exit.
#
# Usage (T490, repo root): scripts/validate-memlat-perf.sh [outdir]
set -eu
export PATH="$PATH:/usr/sbin:/sbin"
O=${1:-results/validation/memlat-perf}
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

GA=mem_load_retired.l1_miss:u,mem_load_retired.l2_miss:u,mem_load_retired.l3_miss:u
GB=dtlb_load_misses.stlb_hit:u,dtlb_load_misses.miss_causes_a_walk:u

for spec in 16K:4K 128K:4K 2M:4K 4M:4K 4M:2M 64M:4K 64M:2M 256M:4K 256M:2M; do
	size=${spec%:*}; page=${spec#*:}
	h=""; [ "$page" = 2M ] && h=-H
	for n in 100000 300000; do
		for g in A B; do
			[ $g = A ] && ev=$GA || ev=$GB
			d=$O/${size}_${page}_n${n}_$g
			sudo perf stat -x, -e "$ev" -o "$d.perf" -- \
				harness/build/memlat $h -s "$size" -n $n -o "$d" >/dev/null
		done
	done
done

python3 - "$O" <<'EOF'
import csv, glob, json, os, sys
o = sys.argv[1]
def run(prefix):
    side = glob.glob(prefix + "/memlat_*.json")[0]
    j = json.load(open(side))
    loads = (j["warmup_discarded"] + j["samples"]) * j["params"]["loads_per_sample"]
    ev = {}
    for row in csv.reader(open(prefix + ".perf")):
        if len(row) > 2 and row[0] and not row[0].startswith("#"):
            ev[row[2].replace(":u", "").split(".")[-1]] = float(row[0])
    return loads, ev, j
cols = ["l1_miss", "l2_miss", "l3_miss", "stlb_hit", "miss_causes_a_walk"]
print(f"{'size':>6} {'page':>4}  " + "".join(f"{c:>20}" for c in cols) + "   (events per load)")
for spec in ["16K_4K", "128K_4K", "2M_4K", "4M_4K", "4M_2M", "64M_4K", "64M_2M", "256M_4K", "256M_2M"]:
    rates = {}
    for g in "AB":
        l1, e1, _ = run(f"{o}/{spec}_n100000_{g}")
        l3, e3, j = run(f"{o}/{spec}_n300000_{g}")
        for k in e3:
            rates[k] = (e3[k] - e1[k]) / (l3 - l1)
    size, page = spec.split("_")
    print(f"{size:>6} {page:>4}  " + "".join(f"{rates.get(c, float('nan')):>20.3f}" for c in cols))
print("profile", j["platform_profile"], "no_turbo", j["no_turbo"], "khz_after", j["env_after"]["cur_khz"])
EOF
