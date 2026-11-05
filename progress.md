# Progress — Linux Latency Characterization Suite

## Environment
- Main laptop: Windows 11, `C:\Users\rodea\LinuxLatency`. Repo: private `RodeanAzari/linux-latency-suite` (make public once results and README are ready).
- T490: `ssh t490@192.168.40.117`, passwordless sudo, repo at `~/linux-latency-suite` (deploy key via `github-latency` SSH alias). Dedicated: reboots and GRUB edits are free.
- Debian 13 (not 12: minimal and installed; `linux-cpupower` replaces `cpufrequtils`). Stock and RT `6.12.115+deb13.1` installed and `apt-mark hold`. GRUB default is saved-by-name to stock (RT sorts first); RT boots one-shot via `grub-reboot`.
- SSH is over Wi-Fi only (`wlp0s20f3`); no Ethernet available. Keep `enp0s31f6` unplugged for the whole campaign.
- Stock Kconfig: NO_HZ_FULL, RCU_NOCB_CPU, PREEMPT_DYNAMIC (voluntary), HZ=250, no HWLAT_TRACER. BIOS settings: `/sys/class/firmware-attributes/thinklmi/attributes/*/current_value` (root).

## Status
- Phases A-D done. Results and findings: `docs/platform.md` (BIOS, services, SMI floor 2.1 ms, e1000e watchdog, thermal: loaded runs ~99% throttled at 95-98 C), `docs/validation.md` (cyclictest ±1 us to p99.9; memlat vs perf counters; ipc; hwlat; turbo stalls ~14 us package-wide per ratio change).
- **Phase E: 27-run campaign started 2026-11-05 12:33** (expected done ~17:30). Check: `ssh t490@192.168.40.117 "tail -1 ~/.latency-campaign/log"` → `campaign complete`, then `scripts/collect.sh status` for ok/partial/failed/skipped per run.
- Phase F: no separate campaign; RT is matrix row 7. Throughput cost still to measure (§8).
- Phase G: not started.

## Decisions that override the spec
- **Isolate whole physical cores:** `isolcpus/nohz_full/rcu_nocbs=2,3,6,7`, `irqaffinity=0,1,4,5`; measure on 2,3, load on 0,1,4,5. §4's `isolcpus=2,3` would leave load on siblings 6,7 and credit isolation's benefit to `nosmt`.
- **`platform_profile=performance` held fixed for every row, baseline included (user).** `balanced` = cTDP-down (800 MHz with turbo off). Runtime-only: `collect.sh` sets it and fails the run if the readback differs.
- **e1000e left admin-up (user):** its PHY watchdog (~0.5 ms every 2 s) is a baseline interference source the isolation rows should remove from the measured cores.
- **Phase D uses `hwgap`** (TSC-gap spin + MSR 0x34 SMI count), not stock `hwlatdetect` (no HWLAT_TRACER). The resume bullet must name what was used.
- **Timer jitter (§2.5) lives in hwgap**, not ipc_latency.
- **Busy-loop warmup is ≥200 ms by time**, not only 1000 iterations (powersave ramp).
- **Campaign:** one boot = one (config, round), idle then loaded; rounds round-robin; boot verified against the row before measuring; 3 min settle (abort: `touch ~/STOP-CAMPAIGN`); Wi-Fi off only during the suite; iTCO watchdog; 2 failed boots → run skipped. Details in `scripts/collect.sh` header.
- Reject tainted kernels (out-of-tree modules) in every run.

## Traps
- Non-login SSH PATH lacks `/usr/sbin`; scripts export it.
- `msr` isn't loaded at boot: `modprobe msr` before hwgap.
- SMI rate must be a per-run delta (~4,700 SMIs during boot).
- **RT: never spin at FIFO > 1 for more than a few seconds on a CPU that isn't `nohz_full` + `rcu_nocbs`**: starves `rcuc/ktimers`, stalls RCU system-wide, kills SSH.
- On 6.12, SCHED_FIFO doesn't own its CPU: the fair-server lets CFS kworkers preempt it.
- RT kernel has no THP: `MADV_NOHUGEPAGE` returns EINVAL (memlat accepts it). Stock THP is `always`.
- HWP drops the clock on memory-bound code; read baseline memlat with the logged frequency.
- `nmcli radio wifi off` persists across reboots; the unit turns Wi-Fi on before and after.
- Never `pkill -f <name>` over SSH when the command line contains `<name>` (kills the session).
- Results written as root are root-owned: `sudo rm`.
- hwgap threshold 300 ns (1 us missed ~60% of ticks).

## Next steps
1. After the campaign: `collect.sh status`, triage anything not `ok`, record the room temperature the user reports.
2. Phase G analysis: directory-level summary over `results/<config>/run*/`, syscall costs in ns (analyze.py rounds to 0.1 us), per-knob delta chart, variance vs effect.
3. Open threads to watch in matrix data: cross-core ~20 us tail (C-states?); UDP slower on SMT; memlat DRAM p99.9; a one-off 3.1→2.8 GHz step-down at ~570 s of load.
4. Figures: `smi_stall_2ms.png`, `memlat_working_set.png`, `cpu2_gaps_idle_loaded.png`.
