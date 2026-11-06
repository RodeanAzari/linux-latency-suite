# Progress — Linux Latency Characterization Suite

## Environment
- Main laptop: Windows 11, `C:\Users\rodea\LinuxLatency`. Repo: private `RodeanAzari/linux-latency-suite` (make public once results and README are ready).
- T490: `ssh t490@192.168.40.117`, passwordless sudo, repo at `~/linux-latency-suite` (deploy key via `github-latency` SSH alias). Dedicated: reboots and GRUB edits are free.
- Debian 13 (not 12: minimal and installed; `linux-cpupower` replaces `cpufrequtils`). Stock and RT `6.12.115+deb13.1` installed and `apt-mark hold`. GRUB default is saved-by-name to stock (RT sorts first); RT boots one-shot via `grub-reboot`.
- SSH is over Wi-Fi only (`wlp0s20f3`); no Ethernet available. Keep `enp0s31f6` unplugged for the whole campaign.
- Stock Kconfig: NO_HZ_FULL, RCU_NOCB_CPU, PREEMPT_DYNAMIC (voluntary), HZ=250, no HWLAT_TRACER. BIOS settings: `/sys/class/firmware-attributes/thinklmi/attributes/*/current_value` (root).

## Status
- Phases A-D done. Results and findings: `docs/platform.md` (BIOS, services, SMI floor 2.1 ms, e1000e watchdog, thermal: loaded runs ~99% throttled at 95-98 C), `docs/validation.md` (cyclictest ±1 us to p99.9; memlat vs perf counters; ipc; hwlat; turbo stalls ~14 us package-wide per ratio change).
- **Phase E campaign complete 2026-11-05 16:51: 27/27 runs `ok`**, 1.7 GB on the T490 only (`results/<config>/run{1,2,3}`). Rows 5-7 have 30 bins, not 32: ctxswitch 2-6 skipped and logged (CPU 6 offline under nosmt). Room temperature 22 C.
- **Rows 5-7 rerun complete 2026-11-05 21:14: 9/9 `ok`**, after the turbo fix below; confounded originals in `results/superseded-turbo/` (a limitations-section finding). The nosmt "syscall speedup" was all turbo. Rows 0-4/8 sidecars predate the aperf/mperf fields; syscall_empty is their clock evidence. Rerun kernels carry taint bit 2 (userspace MSR write, expected; harness rejects only module taint).
- **cTDP episodes (explained 2026-11-05, was "cstates/run2 outlier", not SMT):** in 3 of 36 boots (`cstates/run2`, `irqaffinity/run2`, `nomitigations/run3`) firmware switched the package to cTDP level 1 (800 MHz, 10 W) for ~3-3.5 min while `platform_profile` read `performance`; every clock-bound test in the window is exactly 2.0x (L1 memlat 2.59→5.19 ns, APERF/MPERF 798 MHz), at 38-47 C, no throttle events. A ratio-to-median scan of `summary.csv` finds no other affected run. Cause of the firmware switch unknown (limitations finding). Originals in `results/superseded-ctdp/`; harness now logs MSR 0x64B per monitor row, `analysis/clock_guard.py` fails such runs and `collect.sh` retries them. **Rerun of those 3 boots started 2026-11-05 23:23** (user decision).
- Phase F: no separate campaign; RT is matrix row 7. Throughput cost still to measure (§8).
- Phase G started: `analysis/summarize.py` → `results/summary.csv` (846 rows: per config/run/load/test percentiles, thermal, busy_mhz); `analysis/deltas.py` → `results/deltas.csv` (702 step comparisons, 154 conclusive under §3.6 range rule). Both run on the T490; the CSV plots also run on the laptop (Python 3.12 + numpy/pandas/matplotlib, user site-packages). Plot scripts: `plot_knobs.py`, `plot_variance.py` (from deltas.csv), `plot_tails.py` (raw .bin, T490 only). README drafted 2026-11-06 with `TODO(after cTDP rerun)` markers; its figures aren't committed yet.

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
- **`no_turbo=1` does not hold under `nosmt`** (verified 2026-11-05 with turbostat: CPU 2 at 3300 MHz, its HWP_REQUEST max=16). intel_pstate caps only online threads' HWP requests; parked siblings keep requesting turbo. Setting MISC_ENABLE (0x1a0) bit 38 on every online CPU holds 1600 MHz. Campaign rows 5-7 therefore ran with turbo on: confounded.
- **cTDP level (MSR 0x64B, package scope) is the real profile state**: `performance` = 0 (nominal 1.6 GHz), `balanced`/`low-power` = 1 (800 MHz with turbo off). Firmware can change it without the sysfs readback changing. APERF/MPERF of sleep-dominated sched_latency reads ~400 MHz even when correct: don't use it as a clock check.
- `scaling_cur_freq` reads 400 MHz on `nohz_full` CPUs: the monitor's clock column is meaningless from row 3 on. Real clock needs APERF/MPERF.

## Next steps
1. Verify the cTDP rerun (3 runs `ok`, guard passed, p50s back in line), then rerun `summarize.py` and `deltas.py` (summary.csv/deltas.csv still include the superseded runs), render the three plots into `docs/imgs/`, and resolve the README TODOs (headline, results table, rerun outcome). The `deltas.py` docstring still blames cstates/run2 for inconclusive steps; fix it then.
2. Phase G analysis: directory-level summary over `results/<config>/run*/`, syscall costs in ns (analyze.py rounds to 0.1 us), per-knob delta chart, variance vs effect.
3. Open threads: getppid median rises 270→390 ns at `isolate` (nohz_full context tracking?); idle sched_latency APERF/MPERF reads ~400 MHz (clock low during wakeups from idle?). Also: cross-core ~20 us tail (C-states?); UDP slower on SMT; memlat DRAM p99.9; a one-off 3.1→2.8 GHz step-down at ~570 s of load.
4. Phase F throughput cost: written 2026-11-06, not yet run. After step 1, on the T490: `stress-ng --stressors` must list cpu switch pipe getpid vm, and one by-hand `scripts/run-throughput.sh /tmp/tp` must produce YAMLs that `analysis/throughput.py` parses (the YAML key was assumed, not seen). Then `SUITE=throughput scripts/collect.sh init 3 6 7` (6 boots, ~10 min each) and `analysis/throughput.py`. README still lacks a results table generator and `docs/methodology.md` (§11 links it; README points at buildplan §3 for now).
