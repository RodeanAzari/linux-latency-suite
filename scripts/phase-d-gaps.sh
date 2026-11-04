#!/bin/sh
# Phase D: long gap-detector runs on CPU 2, idle and under load, to measure
# SMI frequency and duration and every other interruption of the measured CPU.
# Load (§4.2) runs only on CPUs 0,1,4,5, so CPU 2 and its sibling 6 are clear.
#
# Usage (T490, repo root): scripts/phase-d-gaps.sh <outdir> [minutes]
set -eu
export PATH="$PATH:/usr/sbin:/sbin"
O=$1
MIN=${2:-20}
P=/sys/firmware/acpi/platform_profile
old=$(cat $P)
cleanup() {
	sudo pkill -x stress-ng 2>/dev/null || true
	echo "$old" | sudo tee $P >/dev/null
}
trap cleanup EXIT
echo performance | sudo tee $P >/dev/null
sudo modprobe msr

sudo harness/build/hwgap -d $((MIN * 60)) -o "$O/idle"

stress-ng --taskset 0,1,4,5 --cpu 4 --io 2 --vm 2 --vm-bytes 1G --timeout $((MIN * 60 + 30))s \
	--quiet &
sleep 10
sudo harness/build/hwgap -d $((MIN * 60)) -o "$O/loaded"
wait
