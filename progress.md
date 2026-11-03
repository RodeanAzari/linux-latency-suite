# Progress — Linux Latency Characterization Suite

## Environment (checked 2026-11-02, read-only)
- Main laptop: Windows 11, `C:\Users\rodea\LinuxLatency`. Not a git repo yet; no GitHub remote.
- T490: `ssh t490@192.168.40.117`, key login works. `sudo` needs a password.
- Debian 13 (trixie), kernel 6.12.111+deb13-amd64 (6.12.107 also installed). cmdline: `quiet` only.
- i5-8365U, 4C/8T. SMT siblings: 0/4, 1/5, 2/6, 3/7. L1d 32K, L2 256K per core; L3 6M shared. 15 GiB RAM, 1 NUMA node.
- BIOS N2IETA6W (1.84). Secure Boot off. On AC, battery full.
- TSC: constant + nonstop, current clocksource `tsc`. intel_pstate/powersave, turbo on. intel_idle down to C10.
- Kconfig: NO_HZ_FULL=y, RCU_NOCB_CPU=y, PREEMPT_DYNAMIC=y (voluntary), HZ=250, **HWLAT_TRACER not set**.
- Network: SSH is over Wi-Fi (`wlp0s20f3`); Ethernet `enp0s31f6` is down.
- Not installed: rt-tests, stress-ng, linux-perf, trace-cmd, linux-cpupower, msr-tools, lm-sensors, numpy/matplotlib/pandas.
- BIOS settings readable as root from `/sys/class/firmware-attributes/thinklmi/attributes/*/current_value`.

## ⚠ The T490 is shared, not dedicated
`~/DMA-Engine` is an active project on this machine (files changed 2026-11-02 20:40). The kernel is tainted (12288 = out-of-tree + unsigned module loaded this boot). The user's tmux sessions are running. Do not wipe, reboot, or edit GRUB without the user's OK.

## Status
- [ ] Phase A: machine prep (survey done; nothing changed on the T490)
- [ ] Phase B–G: not started

## Decisions, and where they differ from CLAUDE.md
- **Share the T490, no wipe (user).** Harness work any time; reboots and GRUB edits only when the user says the machine is free.
- **Repo (user):** private `RodeanAzari/linux-latency-suite`; make public once results and README are ready.
- **No Ethernet available (user).** Measurement runs turn Wi-Fi off, run, then restore it, so the T490 is unreachable during a run. Needs a watchdog/timeout that always restores Wi-Fi; a hang needs a user power-cycle.
- **Debian 13, not 12.** It is what's installed and it's minimal; reinstalling gains nothing. `cpufrequtils` no longer exists, use `linux-cpupower`.
- **Isolate whole physical cores:** `isolcpus/nohz_full/rcu_nocbs=2,3,6,7`, `irqaffinity=0,1,4,5`, measure on 2 and 3, load on 0,1,4,5. §4's `isolcpus=2,3` leaves siblings 6,7 running housekeeping and load on the same cores, which would understate isolation and credit its benefit to `nosmt`.
- **Reject tainted runs:** a run records `/proc/sys/kernel/tainted` and fails if an out-of-tree module is loaded. Needed because the DMA driver shares this machine.
- **Pin the kernel** (`apt-mark hold`) before the campaign; it already moved from .107 to .111.
- **Phase D can't use stock `hwlatdetect`** (no HWLAT_TRACER). Plan: read SMI count from MSR 0x34 around every run, plus a TSC-gap spin on an isolated core. Revisit a tracer-enabled kernel in Phase D. The resume bullet naming `hwlatdetect` must follow what we actually use.
- **Phase F:** PREEMPT_RT is mainline since 6.12, so no patch is needed. Prefer Debian's `linux-image-rt-amd64` (6.12.111, same version as baseline) for a clean delta.
- **Expect a modest `mitigations=off` result.** This CPU reports Meltdown and MDS "Not affected", so no KPTI, the big syscall cost §2.2 anticipates. Report what we measure.

## Next steps
1. User adds passwordless sudo on the T490 (agreed; not yet confirmed done).
2. Finish Phase A: install packages, pin kernel, record BIOS state, trim services.
3. Phase B: `harness/common.c`, then `sched_latency.c`.
