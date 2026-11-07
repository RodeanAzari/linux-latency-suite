#!/bin/sh
# One pass of all five measurement classes plus the gap detector, into <outdir>.
# Measured CPUs 2 and 3; with `loaded`, stress-ng runs on the online subset of
# 0,1,4,5 (§4.2). Runtime setup (profile, governor, turbo) is the caller's job.
#
# A failing test is logged to <outdir>/FAILED and the suite carries on;
# the caller decides what a partial run means.
#
# Usage (T490, repo root): scripts/run-suite.sh <outdir> idle|loaded
set -eu
export PATH="$PATH:/usr/sbin:/sbin"
O=$1
LOAD=$2
B=harness/build
mkdir -p "$O"

online() { [ "$1" = 0 ] || [ "$(cat /sys/devices/system/cpu/cpu$1/online)" = 1 ]; }

t() {	# t <timeout_s> <cmd...>: run one test, record failure, never abort
	lim=$1; shift
	echo "[$(date +%T)] $*"
	sudo timeout -k 10 "$lim" "$@" -o "$O" || echo "rc=$? $*" >> "$O/FAILED"
}

stress_pid=
cleanup() {
	[ -n "$stress_pid" ] && sudo kill "$stress_pid" 2>/dev/null || true
	sudo pkill -x stress-ng 2>/dev/null || true
	sudo sysctl -q vm.nr_hugepages=0
}
trap cleanup EXIT

case $LOAD in
idle) ;;
loaded)
	cpus=$(for c in 0 1 4 5; do if online $c; then printf '%s,' $c; fi; done)
	echo "stress-ng on CPUs ${cpus%,}"
	stress-ng --taskset "${cpus%,}" --cpu 4 --io 2 --vm 2 --vm-bytes 1G --quiet &
	stress_pid=$!
	sleep 10 ;;
*) echo "usage: run-suite.sh <outdir> idle|loaded" >&2; exit 2 ;;
esac

sudo modprobe msr
sudo sysctl -q vm.nr_hugepages=40	# memlat -H 64M needs 32

# §2.2 first: `empty` is the instrumentation overhead for this config
for m in empty getppid mono mono_raw; do t 60 $B/syscall_bench -t $m; done
t 300 $B/sched_latency					# §2.1, 100k x 1 ms
t 60 $B/ctxswitch -a 2 -b 2				# §2.3 same CPU
if online 6; then t 60 $B/ctxswitch -a 2 -b 6		#      SMT siblings
else echo "skip ctxswitch 2-6: CPU 6 offline (nosmt)"; fi
t 60 $B/ctxswitch -a 2 -b 3				#      cross-core, shared L3
for s in 16K 128K 2M 64M; do t 120 $B/memlat -s $s; done	# §2.4 L1 L2 L3 DRAM
t 120 $B/memlat -H -s 64M				#      DRAM, 2M pages
t 60 $B/ipc_latency -t udp				# §2.5
t 60 $B/ipc_latency -t eventfd

# Gap detector (Phase D). On RT, a long FIFO spin on a CPU that is not
# nohz_full starves rcuc/ktimers and stalls RCU system-wide (docs/validation.md).
if uname -r | grep -q -- -rt- && ! grep -qE '(^|[,-])2([,-]|$)' /sys/devices/system/cpu/nohz_full; then
	echo "skip hwgap: RT kernel without nohz_full on CPU 2" | tee -a "$O/FAILED"
else
	t 120 $B/hwgap -d 60
fi
echo "[$(date +%T)] suite done: $O ($LOAD)"
