#!/bin/sh
# Point the next boot at matrix config <id>: write its kernel cmdline to a
# GRUB drop-in and run update-grub. The rt kernel is selected one-shot with
# grub-reboot, so a failed RT boot falls back to stock (collect.sh then sees
# the wrong kernel and fails that run instead of mislabelling it).
#
# Usage (T490, repo root): scripts/set-config.sh <id> | reset
#   reset: remove the drop-in and any pending one-shot entry (stock, `quiet`).
set -eu
export PATH="$PATH:/usr/sbin:/sbin"
M=configs/matrix.json
DROPIN=/etc/default/grub.d/latency.cfg
SUB="Advanced options for Debian GNU/Linux"

if [ "${1:-}" = reset ]; then
	sudo rm -f $DROPIN
	sudo grub-editenv - unset next_entry
	sudo update-grub 2>/dev/null
	echo "reset: stock kernel, cmdline 'quiet'"
	exit 0
fi

# name, kernel release, cmdline tokens (space-separated) for this id
eval "$(python3 - "$M" "${1:?usage: set-config.sh <id> | reset}" <<'EOF'
import json, shlex, sys
m = json.load(open(sys.argv[1]))
c = m["configs"][int(sys.argv[2])]
print(f"NAME={shlex.quote(c['name'])}")
print(f"KREL={shlex.quote(m['kernels'][c['kernel']])}")
print(f"CMDLINE={shlex.quote(' '.join(c['cmdline']))}")
EOF
)"

[ -e /boot/vmlinuz-$KREL ] || { echo "no kernel $KREL" >&2; exit 1; }
sudo mkdir -p /etc/default/grub.d
printf '# written by scripts/set-config.sh: config %s (%s)\nGRUB_CMDLINE_LINUX_DEFAULT="quiet %s"\n' \
	"$1" "$NAME" "$CMDLINE" | sudo tee $DROPIN >/dev/null
sudo update-grub 2>/dev/null

# Saved default stays stock (docs/platform.md); RT is one-shot only.
case $KREL in
*-rt-*) sudo grub-reboot "$SUB>Debian GNU/Linux, with Linux $KREL" ;;
*)      sudo grub-editenv - unset next_entry ;;
esac
echo "next boot: config $1 ($NAME), kernel $KREL, cmdline 'quiet $CMDLINE'"
