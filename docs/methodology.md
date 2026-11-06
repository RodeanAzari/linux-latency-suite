# Methodology

How every number in this repo was taken, and what was done to make a laptop's numbers
comparable with each other. The original spec is `docs/buildplan.md` §3; where this file
differs, this file describes what was actually done. Evidence for each check is in
`docs/validation.md` and `docs/platform.md`.

## Timing

- `clock_gettime(CLOCK_MONOTONIC)` on the TSC clocksource. The CPU has `constant_tsc` and
  `nonstop_tsc`, so the TSC ticks at a fixed 1896 MHz whatever the core clock does.
- Periodic tests sleep with `clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME)` to absolute
  deadlines, never relative sleeps.
- **Instrumentation overhead** is measured in every run as `syscall_bench -t empty` (one
  timestamp pair, nothing between): 14 ns at 4.1 GHz and 36 ns at 1.6 GHz. Syscall numbers
  are reported next to it, not with it subtracted.

## Process setup (`harness/common.c`, every binary)

- `mlockall(MCL_CURRENT | MCL_FUTURE)`, and every buffer is `mmap(MAP_POPULATE)` and then
  written, so no page fault happens inside the measured loop.
- Pinned with `sched_setaffinity`, then **verified**: `sched_getaffinity` must return exactly
  that one CPU and `sched_getcpu` must agree. Cgroups can narrow affinity silently.
- `SCHED_FIFO` priority 90 by default (`-p`), recorded in the sidecar.
- A kernel tainted by an out-of-tree or unsigned module is refused (taint bits 12 and 13).
- ASLR is left on. Layout-sensitive tests (memlat near L2 capacity) show run-to-run spread
  from physical page placement, which the variance rule below absorbs.

## Warmup and sample count

- 1,000 warmup iterations are discarded (`-w`), and busy-loop tests also warm up for at least
  200 ms by time (`-W`). On this machine the clock takes that long to ramp, so an
  iteration count alone measured the ramp.
- 100,000 measured samples per test. `memlat` times 256 dependent loads per sample and
  reports ns per load.

## Raw samples, offline statistics

Each sample is a pair of little-endian int64s: the timestamp and the measured value in ns
(`hwgap`: timestamp, gap length, SMI count). Samples go to a pre-allocated buffer and are
written to disk after the loop. No statistics are computed during measurement. Percentiles,
the thermal split and comparisons are computed later in Python (`analysis/`).

## What each test measures

| Test | Measured CPU(s) | Value per sample |
|---|---|---|
| `sched_latency` | 2 | actual − intended wake time, 1 ms period |
| `syscall_bench -t getppid / mono / mono_raw / empty` | 2 | one call, timed with a timestamp pair |
| `ctxswitch -a A -b B` | 2-2, 2-6 (SMT sibling), 2-3 | pipe ping-pong round trip between two FIFO threads |
| `memlat -s SIZE [-H]` | 2 | random pointer chase; `-H` uses 2 MiB pages |
| `ipc_latency -t eventfd / udp` | 2-3 | eventfd wakeup; loopback UDP round trip |
| `hwgap` | 2 | every interval > 300 ns in which a FIFO spin loop did not run, 60 s |

## Context recorded with every test

- **Sidecar** (`<test>.json`): kernel release and version, cmdline, clocksource, taint,
  hostname, governor, `no_turbo`, `platform_profile`, the PM QoS target
  (`/dev/cpu_dma_latency`) before and after, parameters, and two snapshots (before and after)
  of SMI count, package temperature, clock, throttle counters, cTDP level and APERF/MPERF.
- **Monitor** (`<test>.monitor.csv`): a thread on housekeeping CPU 0 logs the same sensors
  every 100 ms for the whole run.
- **Run** (`run.json`, from `collect.sh`): the config row, the round, attempt number, start and
  end time, and the outcome (`ok`, `partial` with the failures named, `failed`, `skipped`).
- BIOS settings are **not** recorded per run. They were read once from `thinklmi`
  (`docs/platform.md`) and not changed during the campaign.

The harness never holds `/dev/cpu_dma_latency`. It only records it. `cyclictest` sets it to 0
by default, which changes wakeup latency about 100x on this machine. That was the cause of the
first harness-vs-cyclictest disagreement (`docs/validation.md`).

## Controlling the clock

The clock was the biggest uncontrolled variable on this machine, and it changed from
under the OS three different ways. Each boot (`scripts/collect.sh`):

1. Sets `platform_profile=performance`. Under `balanced` the firmware selects cTDP level 1,
   which with turbo off means 800 MHz.
2. Sets the row's governor and `intel_pstate/no_turbo`, and also MSR 0x1A0 bit 38 (turbo
   disable) on every online CPU. Under `nosmt`, `no_turbo` alone left CPU 2 at 3.3 GHz.
3. Spins CPU 2 for 3 s and reads its busy clock with `turbostat`. On fixed-clock rows it must
   be within 3% of 1600 MHz, or the run is failed.
4. After the suite, `analysis/clock_guard.py` checks that every monitor row and snapshot still
   shows the starting cTDP level, and that each test's APERF/MPERF busy clock is within 3% of
   base. A failing run is moved to `results/superseded-ctdp/` and retried on the next boot.
   `sched_latency` is exempt from the APERF/MPERF check because it sleeps between wakeups and
   reads ~400 MHz even when the clock is correct. The cTDP check still covers it.

`scaling_cur_freq` is not used as clock evidence: it reads 400 MHz on `nohz_full` CPUs.

## Load

The **idle** pass runs with nothing else on the machine. The **loaded** pass runs
`stress-ng --cpu 4 --io 2 --vm 2 --vm-bytes 1G` on the online subset of CPUs 0, 1, 4 and 5,
started 10 s before the first test. Measured CPUs 2 and 3, and their siblings 6 and 7, get no
load in any config.

## Thermal partitioning

Each sample is placed in the 100 ms monitor interval it fell in. An interval is **throttled**
if the measured core's or the package's throttle counter rose during it. Percentiles are
reported for all samples and for each side of the split, and a side with fewer than 10 samples
beyond a percentile has that percentile left out. The whole interval counts, so the split leans
towards "throttled". Idle runs had no throttling. Loaded runs were ~99% throttled at
95–98 °C, so their unthrottled side is mostly empty, and the README says so.

## Run-to-run variance (§3.6)

- 3 runs per config, each in its own boot. Rounds are round-robin (every config once, then
  every config again), so drift over the night does not land on a single config.
- A config's value is the **median** of its runs.
- A step from config A to config B is **conclusive** only if |median(B) − median(A)| is larger
  than the max − min range of either config's runs. Otherwise it is reported as "not shown
  to differ", not as a small effect. With 3 runs the range is a conservative bar, since
  one odd boot makes a step inconclusive. That is intended: it is the variance a reader would
  see if they repeated the experiment.

## Interference controls

- Background services and timers that cause wakeups are disabled (`docs/platform.md`).
- Wi-Fi, the only network link, is off for the whole suite and back on afterwards.
- No tracing during latency runs. `perf stat` with tracepoints inflated IPC latency by up to
  57%, so counter runs and latency runs are always separate.
- Each boot waits 3 minutes before measuring, to let boot-time SMIs and services settle.
  `MSR_SMI_COUNT` is reported as a per-test delta, never since boot.
- A hardware watchdog (iTCO) resets a hung boot. Two failed boots on the same run mark it
  `skipped` and the campaign moves on. The skip is recorded, never silently missing.

## Known limits of the method

- One machine, so absolute values are platform-specific and only the deltas carry over.
- SMIs cannot be disabled or prevented. Any p99.99 or max that contains one measures
  firmware.
- The e1000e PHY watchdog (~0.5 ms every 2 s) was deliberately left running as a baseline
  interference source. The isolation rows show whether it is moved off the measured CPUs.
- 3 runs per config detect large effects only. A smaller real effect will be reported as
  inconclusive.
