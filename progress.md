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
- [~] Phase B: `common.c` (pinning, mlockall, FIFO, pre-fault, raw samples, JSON sidecar, 100 ms thermal/SMI monitor, QoS target recorded) `sched_latency`, `syscall_bench` (incl. 14 ns timer overhead), `ctxswitch`, `memlat`, `ipc_latency` (udp RTT, eventfd one-way) done. `analysis/analyze.py` prints percentiles (memlat as ns/load). **§2.5 timer jitter deliberately moved to the Phase D gap detector** (busy-spin on the measured core, record every gap: ticks, IRQs, SMIs). Phase B is complete except for that.
- [~] Phase C: sched_latency agrees with cyclictest within ±1 us to p99.9 when the C-state QoS target matches (`docs/validation.md`). 3 repeats agree (p50-p99.9 within 0.4 us run to run). memlat validated against `mem_load_retired.*` / `dtlb_load_misses.*` per load (`scripts/validate-memlat-perf.sh`): every level and the 4K/2M TLB split match the geometry. ipc validated (perf: exactly 4 syscalls, 2 switches, 2 `lo` xmits per UDP round). Phase C complete. Lesson: tracepoint-counted runs inflate latency, so take counts and latencies from separate runs.
- [~] Phase D: `hwgap` gap detector (per-gap SMI attribution) + `analysis/gaps.py`. 20-min idle/loaded runs done (`docs/platform.md`): SMI = 2.1 ms, 0-1/20 min idle, 6/20 min loaded; e1000e watchdog ~0.5 ms every 2 s; load triples softirq gaps on CPU 2; package 100 C under load. Remaining: hwlat cross-check on RT (`scripts/validate-hwgap-hwlat.sh`, `analysis/match_hwlat.py`), integrate thermal partitioning in analysis.
- [ ] Phase E-G: not started

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

- **cTDP-down under `balanced` (found 2026-11-04).** ThinkPad DYTC `balanced` profile sets CONFIG_TDP_CONTROL=1: guaranteed 800 MHz, so turbo-off runs at 800 MHz. `platform_profile=performance` gives nominal 1.6 GHz. Runtime setting; recorded in every sidecar. **Decided (user, 2026-11-04): `platform_profile=performance` is held fixed for every matrix row, including `baseline`.** It's a platform setting like BIOS, not a knob. It's runtime-only, so the campaign's boot script must set it and fail if it can't.
- **HWP drops the clock on memory-bound code** (400 MHz–2.5 GHz during DRAM runs on stock). Memory results are only comparable at a fixed clock; `baseline` memlat must be read with logged frequency.
- **THP is `always`** on this box. memlat forces 4K with `MADV_NOHUGEPAGE`, 2M with `MAP_HUGETLB` (`vm.nr_hugepages`).

- **Never measure latency under tracepoints.** `perf stat` with tracepoints inflated ipc latency up to 57%. Counts and latencies come from separate runs.
- **hwgap threshold 300 ns** (ticks are 0.3-2 us; 1 us missed ~60%).
- **On 6.12, SCHED_FIFO doesn't own its CPU**: the fair-server lets CFS kworkers preempt it.
- **Unplugged e1000e is admin-up** (`allow-hotplug enp0s31f6`, DHCP), so the PHY watchdog runs ~0.5 ms every 2 s. **Open decision for the user:** leave it as a baseline interference source for isolation to remove, or take it down platform-wide like the trimmed services.

## Next steps
1. Finish the hwlat cross-check (RT kernel, CPUs 2/3, loaded): every SMI should appear in both tools.
2. Phase E: `configs/matrix.json`, `set-config.sh`, `run-suite.sh`, `collect.sh` + systemd unit. Must set `platform_profile=performance` at boot and turn Wi-Fi off and back on with a watchdog.
3. Open threads for the matrix: cross-core ~20 us tail (C-states?); UDP slower on SMT; memlat DRAM p99.9.
4. Figures: `smi_stall_2ms.png`, `memlat_working_set.png`, `cpu2_gaps_idle_loaded.png`.
