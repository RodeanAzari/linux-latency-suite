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

## T490 is now dedicated (user, 2026-11-03)
DMA-Engine is finished and pushed; reboots and GRUB edits are free. `~/DMA-Engine`, buildroot and QEMU are still on disk and unused. Booted stock 6.12.115 with taint 0.

## Status
- [x] Phase A: passwordless sudo; repo at `~/linux-latency-suite` (deploy key via `github-latency` SSH alias); packages installed (`rt-tests stress-ng linux-perf trace-cmd linux-cpupower msr-tools lm-sensors python3-numpy python3-matplotlib python3-pandas`, no kernelshark); stock and RT 6.12.115 installed and held; BIOS recorded; services trimmed; idle baseline taken (`docs/platform.md`). Disk image skipped: the machine is reproducible from the docs.
- [~] Phase B: `common.c` (pinning, mlockall, FIFO, pre-fault, raw samples, JSON sidecar, 100 ms thermal/SMI monitor, QoS target recorded) and `sched_latency.c` done. `analysis/analyze.py` prints percentiles. Remaining: syscall, ctxswitch, memlat, ipc, instrumentation-overhead measurement.
- [~] Phase C: sched_latency agrees with cyclictest within ±1 us to p99.9 when the C-state QoS target matches (`docs/validation.md`). 3 repeats agree (p50-p99.9 within 0.4 us run to run). Remaining: perf-stat check for memlat.
- [ ] Phase D–G: not started

## Decisions, and where they differ from CLAUDE.md
- **Repo (user):** private `RodeanAzari/linux-latency-suite`; make public once results and README are ready.
- **No Ethernet available (user).** Measurement runs turn Wi-Fi off, run, then restore it, so the T490 is unreachable during a run. Needs a watchdog/timeout that always restores Wi-Fi; a hang needs a user power-cycle.
- **Debian 13, not 12.** It is what's installed and it's minimal; reinstalling gains nothing. `cpufrequtils` no longer exists, use `linux-cpupower`.
- **Isolate whole physical cores:** `isolcpus/nohz_full/rcu_nocbs=2,3,6,7`, `irqaffinity=0,1,4,5`, measure on 2 and 3, load on 0,1,4,5. §4's `isolcpus=2,3` leaves siblings 6,7 running housekeeping and load on the same cores, which would understate isolation and credit its benefit to `nosmt`.
- **Reject tainted runs:** a run records `/proc/sys/kernel/tainted` and fails if an out-of-tree module is loaded. Needed because the DMA driver shares this machine.
- **Pin the kernel** (`apt-mark hold`) before the campaign; it already moved from .107 to .111.
- **Phase D can't use stock `hwlatdetect`** (no HWLAT_TRACER). Plan: read SMI count from MSR 0x34 around every run, plus a TSC-gap spin on an isolated core. Revisit a tracer-enabled kernel in Phase D. The resume bullet naming `hwlatdetect` must follow what we actually use.
- **Phase F:** PREEMPT_RT is mainline since 6.12, so no patch is needed. Prefer Debian's `linux-image-rt-amd64` for a clean delta. Done: stock and rt 6.12.115 are installed and held. GRUB default is saved-by-name to stock, because the RT kernel sorts first in the menu. Boot RT with `grub-reboot`, one-shot.
- **SMI rate must be a per-run delta.** About 4,700 SMIs happen during boot; idle steady state is about one per 150 s.
- **Non-login SSH PATH lacks `/usr/sbin`** (`rdmsr`, `turbostat`, `hwlatdetect`). Scripts set PATH explicitly.
- **Expect a modest `mitigations=off` result.** This CPU reports Meltdown and MDS "Not affected", so no KPTI, the big syscall cost §2.2 anticipates. Report what we measure.

- **cyclictest holds `/dev/cpu_dma_latency=0` by default** (deep C-states off); `--laptop` doesn't. That alone is 115 us vs 2 us p50 here. The harness never sets it; sidecars record it; C-states belong to the matrix `cstates` row.
- **Busy-loop tests warm up by time (>=200 ms), not just 1000 iterations**: the powersave ramp otherwise makes results track frequency (26 vs 53 ns, same code). Overhead must be re-measured per config.
- Results written as root are root-owned; clean up with `sudo rm`.
- Never `pkill -f <name>` over SSH when the SSH command line contains `<name>`: it kills the session (exit 255).

## Next steps
1. Phase B: `memlat.c` next, then ipc. ctxswitch done and validated (perf: exactly 2 switches/round; RT p50 2.4 us same-CPU, 4.2 us SMT, 5.0 us cross-core). syscall_bench validated: overhead 14 ns, getppid ~91 ns net, vDSO clocks ~14 ns net (turbo, stock).
2. Phase D lead: SMIs on this machine stall ~2 ms each (rep2 in `docs/validation.md`).
3. Then ctxswitch, memlat, ipc.
