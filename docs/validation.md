# Validation: `sched_latency` vs `cyclictest`

§3.7: the scheduler-wakeup harness must agree with `cyclictest` on the same
configuration before any of its numbers are trusted.

## Setup

Same for every run on 2026-11-03: kernel `6.12.115+deb13.1-amd64` (stock,
`PREEMPT_DYNAMIC`, cmdline `quiet`), taint 0, governor `powersave`, turbo on,
nothing isolated. Every run measured CPU 2 with `SCHED_FIFO` priority 90,
a 1000 µs interval, 100,000 samples and `mlockall`.

```
harness:     sudo harness/build/sched_latency -c 2 -p 90 -i 1000 -n 100000 -w 1000 -o <dir>
cyclictest:  sudo cyclictest -m -p 90 -a 2 -t 1 -i 1000 -l 100000 -q -h 2000 [--laptop] --histfile=<f>
```

Raw data is in `results/validation/val{1..4}/`. The table comes from `analysis/analyze.py`.

## The variable that matters: `/dev/cpu_dma_latency`

By default `cyclictest` opens `/dev/cpu_dma_latency` and writes 0. This sets a
PM QoS request that keeps every core out of deep C-states for as long as the
file is open. With `--laptop` it skips that step. The harness does not touch it.
The first comparison (val1) therefore compared two different machine states:

| run | tool | QoS target | p50 | p90 | p99 | p99.9 | p99.99 | max (µs) |
|---|---|---|---:|---:|---:|---:|---:|---:|
| val1 | harness | none | 114.9 | 120.8 | 127.4 | 132.9 | 356.6 | 376.8 |
| val1 | cyclictest `--laptop` | none | 109 | 125 | 258 | 267 | 273 | 286 |
| val1 | cyclictest default | **0 µs** | **1** | 2 | 2 | 3 | 214 | 220 |
| val2 | cyclictest `--laptop` | none | 108 | 119 | 252 | 262 | 270 | 295 |
| val2 | harness | none | 122.4 | 227.6 | 244.8 | 254.1 | 264.5 | 282.6 |
| val2 | cyclictest `--laptop` | none | 117 | 256 | 266 | 270 | 284 | 442 |
| val3 | harness | none ¹ | 120.2 | 261.8 | 277.1 | 286.2 | 295.0 | 320.1 |
| val3 | cyclictest default | **0 µs** | 1 | 2 | 2 | 3 | 3 | 2045 |
| val4 | harness | **0 µs** ² | **1.8** | 2.0 | 2.1 | 2.3 | 7.7 | 15.4 |
| val4 | cyclictest `--laptop` | **0 µs** ² | **1** | 2 | 2 | 3 | 3 | 4 |

¹ An external QoS holder was meant to run here, but it failed to start (a shell quoting error), so this run is unheld.
² Both tools ran while a separate process (`/tmp/hold_dma.py`) held the target at 0.

## Result

**Matched state, held at 0 µs (val4):** the two tools agree within 1 µs from
p50 to p99.9. `cyclictest` truncates to whole microseconds, which accounts for
the harness reading ~0.8 µs higher at p50 (1.8 vs 1). The harness tail is a bit
heavier (p99.99 7.7 vs 3, max 15.4 vs 4). That is a single run each, and
§3.6 run-to-run variance has not been measured yet, so the gap is noted, not
explained.

**Matched state, unconstrained:** both tools produce the same two modes, near
~110 µs and ~250 µs. Within a single tool, the share of samples in the upper
mode changes from run to run: the harness p90 was 120.8 in val1 and 227.6 in
val2, and `cyclictest` p90 was 119 and 256 in the val2 pair. The difference
between runs is larger than the difference between tools. At this setting,
then, the tools are consistent: neither is systematically higher.

**Tolerance adopted:** the harness agrees with `cyclictest` within **±1 µs
through p99.9** when the C-state QoS target matches. That is the resolution
`cyclictest` reports at.

## Consequences for the harness

- The QoS target changes p50 by about 60× on this machine. Every sidecar now
  records `cpu_dma_latency_us` (before and after the run), and a run is not
  comparable to another unless they match. The harness itself never sets it.
  C-state policy belongs to the configuration matrix (`cstates` row), not to
  the tool.
- Any comparison with `cyclictest` must say which mode was used. Its default
  numbers describe a machine with deep C-states disabled, not a stock laptop.

## Side observations (for Phase D)

- Holding the target at 0 raised package temperature from 52 °C to 62 °C over
  the 100 s run (val4). Unheld runs stayed at 35–39 °C. No throttling and no
  SMIs occurred in any of the four runs.
- The ~110 / ~250 µs modes probably correspond to two idle depths, such as a
  core C-state versus a package C-state exit. This has not been confirmed yet.
  `turbostat` residency during a run would test it.
- val3's `cyclictest` max of 2045 µs is a single sample beyond the
  2000 µs histogram range. It has not been explained yet.

## Still to validate (Phase C)

- [ ] Repeat the val4 pair 3× to get run-to-run spread for the held state.
- [ ] Memory results vs `perf stat` cache/TLB counters (once `memlat` exists).
