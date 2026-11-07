#!/bin/sh
# Demo (for an asciinema recording): catch an SMI live.
# hwgap spins on CPU 2 in CHUNK-second runs under load on CPUs 0,1,4,5 and
# prints one line per run; it stops at the first run in which the firmware's
# SMI counter moved and shows that gap next to the largest one Linux caused.
# hwgap prints nothing while it measures; each line comes from its finished run.
#
# Usage (T490, repo root): scripts/demo-smi.sh   [CHUNK=30 MAX=40]
# Record:  asciinema rec -i 1 -c scripts/demo-smi.sh smi.cast
set -eu
export PATH="$PATH:/usr/sbin:/sbin"
CHUNK=${CHUNK:-30}
MAX=${MAX:-40}
P=/sys/firmware/acpi/platform_profile
O=$(mktemp -d)
old=$(cat $P)
cleanup() {
	sudo pkill -x stress-ng 2>/dev/null || true
	echo "$old" | sudo tee $P >/dev/null
	sudo rm -rf "$O"
}
trap cleanup EXIT
echo performance | sudo tee $P >/dev/null
sudo modprobe msr

echo "Kernel $(uname -r): spinning on CPU 2, timing every gap > 300 ns, ${CHUNK} s per run."
echo "Load on CPUs 0,1,4,5. Waiting for the firmware to take the CPU away..."
echo
stress-ng --taskset 0,1,4,5 --cpu 4 --io 2 --vm 2 --vm-bytes 1G --timeout $((CHUNK * MAX + 60))s \
	--quiet &
sleep 5

i=0
while [ $i -lt "$MAX" ]; do
	i=$((i + 1))
	mkdir -p "$O/$i"
	sudo harness/build/hwgap -c 2 -m 0 -d "$CHUNK" -o "$O/$i" >/dev/null
	if python3 - "$O/$i" $((i * CHUNK)) <<'EOF'; then exit 0; fi
import sys
sys.path.insert(0, "analysis")
import gaps

d, t = sys.argv[1], int(sys.argv[2])
j, g, smi = gaps.load(d)
us = g["gap_ns"] / 1e3
linux = us[~smi].max() if (~smi).any() else 0.0
print(f"{t:>5} s   {len(g):>6} gaps   largest {linux:7.1f} us   SMIs {int(smi.sum())}", flush=True)
if not smi.any():
    sys.exit(1)
print()
for k in smi.nonzero()[0]:
    print(f"  SMI: CPU 2 was gone for {us[k] / 1000:.2f} ms. The OS saw nothing; only the")
    print(f"       firmware's SMI counter (MSR 0x34) moved, {g['smi'][k] - 1} -> {g['smi'][k]}.")
print(f"  That is {us[smi].max() / linux:.0f}x the largest gap Linux caused in the same run,")
print("  and no kernel setting can prevent it: it is this machine's latency floor.")
EOF
done
echo "no SMI in $((CHUNK * MAX)) s"
exit 1
