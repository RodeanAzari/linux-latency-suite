#!/bin/sh
# Unattended matrix campaign (§5). One boot = one (config, round): verify the
# boot matches the row, apply its runtime setup, run the suite idle then
# loaded with Wi-Fi off, record, point GRUB at the next row, reboot.
#
#   scripts/collect.sh init [rounds]   queue every config x rounds (round-robin),
#                                      install + enable the unit, reboot into the first
#   scripts/collect.sh run             the boot step (run by latency-collect.service)
#   scripts/collect.sh status          queue and per-run outcome
#
# Abort: `touch ~/STOP-CAMPAIGN` during the settle window after a boot (Wi-Fi is
# up then). The unit disables itself and the box stays on the current config;
# `scripts/set-config.sh reset` and a reboot return it to stock.
#
# Results: results/<config>/run<round>/{idle,loaded}/ + run.json.
set -eu
export PATH="$PATH:/usr/sbin:/sbin"
cd "$(dirname "$0")/.."
M=configs/matrix.json
S=$HOME/.latency-campaign		# queue, attempts, log
SETTLE=${SETTLE:-180}			# s after boot: abort window, boot SMIs/services settle
MAX_ATTEMPTS=2				# a run that hangs the box twice is skipped
UNIT=latency-collect.service
CPU=/sys/devices/system/cpu
log() { echo "[$(date '+%F %T')] $*" | tee -a "$S/log"; }

# Fields of config <id>: name kernel_release governor no_turbo cmdline...
row() {
	python3 - "$M" "$1" <<'EOF'
import json, sys
m = json.load(open(sys.argv[1]))
c = m["configs"][int(sys.argv[2])]
print(c["name"], m["kernels"][c["kernel"]], c["governor"], c["no_turbo"], *c["cmdline"])
EOF
}

finish() {	# queue empty: back to stock, disable the unit
	log "campaign complete"
	scripts/set-config.sh reset
	sudo systemctl disable $UNIT
	sudo rm -f /etc/systemd/system.conf.d/latency-watchdog.conf
	sudo reboot
	exit 0
}

next() {	# drop the head of the queue, point GRUB at the new head, reboot
	sed -i 1d "$S/queue"
	echo 0 > "$S/attempts"
	[ -s "$S/queue" ] || finish
	scripts/set-config.sh "$(head -1 "$S/queue" | cut -d' ' -f1)" >> "$S/log"
	sudo reboot
	exit 0
}

record() {	# record <status> <detail>: run.json beside the results
	python3 - "$M" "$id" "$round" "$1" "$2" "$attempts" "$start" > "$R/run.json" <<'EOF'
import json, sys, time
m, i, rnd, status, detail, att, start = sys.argv[1:]
c = json.load(open(m))["configs"][int(i)]
print(json.dumps({"config": c, "round": int(rnd), "status": status, "detail": detail,
		  "attempt": int(att), "start": start,
		  "end": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
		  "cmdline": open("/proc/cmdline").read().strip()}, indent=1))
EOF
	log "config $id ($name) round $round: $1 $2"
}

case ${1:-} in
init)
	rounds=${2:-$(python3 -c "import json;print(json.load(open('$M'))['runs_per_config'])")}
	[ -s "$S/queue" ] && { echo "campaign already queued: $S/queue (rm -r $S to restart)" >&2; exit 1; }
	mkdir -p "$S"
	n=$(python3 -c "import json;print(len(json.load(open('$M'))['configs']))")
	for r in $(seq 1 "$rounds"); do for i in $(seq 0 $((n - 1))); do echo "$i $r"; done; done > "$S/queue"
	echo 0 > "$S/attempts"
	sed "s|@REPO@|$PWD|; s|@USER@|$(id -un)|" scripts/$UNIT | sudo tee /etc/systemd/system/$UNIT >/dev/null
	# Hardware watchdog (iTCO): a hard kernel hang resets the box instead of stalling
	sudo mkdir -p /etc/systemd/system.conf.d
	printf '[Manager]\nRuntimeWatchdogSec=60\n' | sudo tee /etc/systemd/system.conf.d/latency-watchdog.conf >/dev/null
	sudo systemctl daemon-reload
	sudo systemctl enable $UNIT
	log "init: $(wc -l < "$S/queue") runs queued"
	scripts/set-config.sh "$(head -1 "$S/queue" | cut -d' ' -f1)" | tee -a "$S/log"
	echo "reboot to start: sudo reboot"
	;;
status)
	echo "pending: $(wc -l < "$S/queue" 2>/dev/null || echo 0)  next: $(head -1 "$S/queue" 2>/dev/null)  attempts: $(cat "$S/attempts" 2>/dev/null)"
	grep -E ': (ok|partial|failed|skipped)' "$S/log" 2>/dev/null || true
	;;
run)
	[ -s "$S/queue" ] || { log "run: empty queue"; finish; }
	read -r id round < "$S/queue"
	attempts=$(($(cat "$S/attempts") + 1)); echo $attempts > "$S/attempts"
	set -- $(row "$id"); name=$1 krel=$2 gov=$3 noturbo=$4; shift 4
	R=results/$name/run$round
	start=$(date +%Y-%m-%dT%H:%M:%S%z)
	log "boot: config $id ($name) round $round, attempt $attempts, kernel $(uname -r)"

	if [ "$attempts" -gt $MAX_ATTEMPTS ]; then
		mkdir -p "$R"; record skipped "did not finish in $MAX_ATTEMPTS boots"; next
	fi

	# Abort window, with Wi-Fi up
	sleep "$SETTLE"
	if [ -e "$HOME/STOP-CAMPAIGN" ]; then
		rm -f "$HOME/STOP-CAMPAIGN"
		echo $((attempts - 1)) > "$S/attempts"
		log "STOP-CAMPAIGN: unit disabled, queue kept (re-enable: sudo systemctl enable $UNIT)"
		sudo systemctl disable $UNIT
		exit 0
	fi

	sudo rm -rf "$R"; mkdir -p "$R"
	# Verify the boot is the row we think it is: a mislabelled run is worse than none
	bad=
	[ "$(uname -r)" = "$krel" ] || bad="kernel $(uname -r), want $krel"
	for tok in "$@"; do
		grep -qwF -- "$tok" /proc/cmdline || bad="$bad cmdline lacks $tok"
	done
	[ -z "$bad" ] || { record failed "$bad"; next; }

	# Runtime setup; fail the run if any readback differs
	echo performance | sudo tee /sys/firmware/acpi/platform_profile >/dev/null
	sudo cpupower -c all frequency-set -g "$gov" >/dev/null
	echo "$noturbo" | sudo tee $CPU/intel_pstate/no_turbo >/dev/null
	[ "$(cat /sys/firmware/acpi/platform_profile)" = performance ] || bad="platform_profile"
	for g in $CPU/cpu[0-9]*/cpufreq/scaling_governor; do
		[ "$(cat "$g")" = "$gov" ] || bad="$bad $g"
	done
	[ "$(cat $CPU/intel_pstate/no_turbo)" = "$noturbo" ] || bad="$bad no_turbo"
	[ -z "$bad" ] || { record failed "runtime setup: $bad"; next; }

	log "wifi off, suite start"
	sudo nmcli radio wifi off
	scripts/run-suite.sh "$R/idle" idle > "$R/suite.log" 2>&1 || true
	scripts/run-suite.sh "$R/loaded" loaded >> "$R/suite.log" 2>&1 || true
	sudo nmcli radio wifi on

	cat "$R"/idle/FAILED "$R"/loaded/FAILED > "$R/FAILED" 2>/dev/null || true
	if [ -s "$R/FAILED" ]; then
		record partial "$(tr '\n' ';' < "$R/FAILED")"
	else
		rm -f "$R/FAILED"; record ok ""
	fi
	next
	;;
*)
	sed -n '2,16p' "$0"; exit 2 ;;
esac
