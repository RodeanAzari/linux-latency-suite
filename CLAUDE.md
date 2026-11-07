# CLAUDE.md — Linux Latency Characterization Suite

A reproducible harness that measures where latency comes from on Linux and what each tuning knob buys: **5 latency classes × 8 cumulative kernel configurations**, percentiles, run-to-run variance, thermal annotation. Runs on a dedicated ThinkPad T490.

**The full spec is `docs/buildplan.md`** (not loaded every turn). Every `§N` in code, scripts and docs refers to it: §2 what is measured, §3 methodology, §4 matrix, §5 automation, §6 PREEMPT_RT, §8 phase done-checklists, §9 out of scope, §11 deliverables. Read the relevant section before starting a phase. Decisions that override the spec are in `progress.md`.

## Keep always-loaded docs lean
CLAUDE.md ≤ 250 lines and `progress.md` ≤ 150 lines. Trim them at the end of every session that edits them, and at once if either is over. Keep only what a future session would get wrong without being told (current state, open work, rules, traps that cost real time). Cut finished-work narratives, dated history, reasons the code, tests, commits or reports already record, and duplicates of other docs. Move what must be kept but isn't needed every turn (the spec, append-only measurement tables, long verification detail) to files that aren't imported, such as `docs/buildplan.md` and `docs/measurements.md`, and leave a one-line pointer.

## ★ Portfolio project
It goes on the user's GitHub, website and resume, so decisions also serve how it looks to a reviewer:
- **Measure things.** Real numbers (percentiles, histograms, per-knob deltas) are the headline result.
- **Capture evidence as we go.** At each milestone, say what's worth capturing (screenshots, asciinema casts, plots), saved under `docs/imgs/` with descriptive names.
- **The README is a deliverable** (§11): diagrams, the matrix, plots, findings, limitations, build-from-clean instructions.
- **Credibility beats flash.** Laptop numbers are not server numbers; deltas between configs are the result. Never overstate.

## Build process
1. Write code in small steps that can each be checked, with a stated check for each.
2. Commit and push, then build and test on the T490 over SSH (`ssh t490@192.168.40.117`) in Claude's own tmux session (`claude-latency`). Never touch the user's tmux session. Review the output before moving on.
3. After each big step, explain it to the user (what, why, technical detail, fit in the architecture), with ASCII diagrams where they help.
4. Prompt the user only when needed: power-cycling a hung T490, credentials, real screenshots/recordings, and decisions that are theirs. Label every command block with the machine and folder.

## Progress file
`progress.md` is the session handoff. Read it at the start of every session. Update it when a milestone completes, a decision is made or next steps change: environment facts, status, decisions that affect future work, next steps. No routine commands or small fixes. Update the status table below when a phase's §8 checklist (in `docs/buildplan.md`) passes.

## Current status

| Phase | Work | Status |
|---|---|---|
| A | Machine prep, baseline kernel, tooling | DONE |
| B | Measurement harness core | DONE (timer jitter moved to D) |
| C | Validation against reference tools | DONE |
| D | Platform floor: SMI and thermal characterization | DONE |
| E | Configuration matrix automation | DONE (27/27 runs ok, 2026-11-05) |
| F | PREEMPT_RT build and comparison | DONE (Debian -rt kernel; throughput 6/6 ok, 2026-11-07) |
| G | Analysis, plots, report | DONE (2026-11-07; repo public, MIT) |

## Hardware target
ThinkPad T490, i5-8365U 4C/8T (SMT siblings 0/4, 1/5, 2/6, 3/7), 15 GiB, headless Debian 13, stock and PREEMPT_RT 6.12.115 kernels (held). BIOS state and platform findings: `docs/platform.md`. Changing BIOS settings mid-campaign invalidates earlier runs. SMIs cannot be disabled on this machine; they are the measured floor, not a bug.

## Toolchain and build targets
- C (gcc, make): `make -C harness` → `harness/build/{sched_latency,syscall_bench,ctxswitch,memlat,ipc_latency,hwgap}`. Shared timing, pinning, mlockall, sample I/O, sidecar and monitor code in `harness/common.{c,h}`.
- POSIX sh scripts in `scripts/` (run from the repo root on the T490), Python 3 + numpy/pandas/matplotlib in `analysis/`.
- Tests: `python3 -m pytest` from the repo root (`analysis/test_*.py`, synthetic fixtures; pytest via pip on the laptop, `python3-pytest` on the T490). New analysis logic gets a test plus a bug-injection check.
- Reference tools: `rt-tests` (cyclictest, hwlatdetect), `perf`, `stress-ng`, `msr-tools`, `linux-cpupower`.

## Repository layout
```
harness/     one binary per measurement class + hwgap gap detector; common.c/.h
scripts/     set-config.sh, run-suite.sh, collect.sh + latency-collect.service (campaign);
             phase-d-*.sh, validate-*.sh, sweep-memlat.sh (one-off experiments)
configs/     matrix.json — the §4 table as data
analysis/    analyze.py (percentiles, thermal split), gaps.py, match_*.py, plot_*.py
results/     results/<config>/run<r>/{idle,loaded}/<test>.bin + .json sidecar + .monitor.csv
             (*.bin gitignored; commit a representative subset with git add -f)
docs/        buildplan.md (spec), platform.md, validation.md, imgs/
```

## Coding standards
- Match the existing style: C in kernel-ish style with tabs; every measurement binary takes `-o outdir`, `-m monitor_cpu`, `-T` and writes `.bin` + `.json` sidecar + `.monitor.csv` via `common.c`.
- Scripts: `#!/bin/sh`, `set -eu`, `export PATH="$PATH:/usr/sbin:/sbin"`, restore any system state they change in an EXIT trap.
- Fail loud: a skipped or failed test is recorded (`FAILED`, `run.json`), never silently absent.

## Measurement rules (§3, every run)
- `CLOCK_MONOTONIC` (invariant TSC confirmed); `clock_nanosleep(TIMER_ABSTIME)` with absolute deadlines, never relative sleeps.
- `mlockall`, pinned affinity (verify it took), `SCHED_FIFO` with a documented priority, every buffer pre-faulted.
- ≥1,000 warmup iterations and ≥200 ms warmup for busy loops; ≥100,000 measured samples.
- Raw samples to binary files; **no statistics inside a measurement loop**. All stats offline in Python.
- Instrumentation overhead (`syscall_bench -t empty`) measured per config and reported.
- Thermal and frequency logged alongside every run; analysis splits throttled vs unthrottled (§3.5).
- ≥3 runs per config with a reboot between; if run-to-run spread exceeds a difference, call it inconclusive (§3.6).
- Never measure latency while tracepoints are on (`perf stat` with tracepoints inflated ipc up to 57%). Counts and latencies come from separate runs.
- A result without its kernel, cmdline, BIOS/runtime state and thermal context recorded is not a result.

## Known failure modes
- Harness vs cyclictest disagree: relative-sleep bug, or a mismatched `/dev/cpu_dma_latency` (cyclictest holds it at 0 by default).
- Bimodal results: thread migrated; `sched_setaffinity` can fail silently against cgroups.
- p99.9 dominated by a few huge outliers: SMI or thermal. Identify, never just discard.
- `isolcpus` appears to do nothing: measured idle only; the benefit shows under load (§4.2).
- Frequency drifting mid-run: governor/turbo not set; the monitor logs `scaling_cur_freq` continuously.
- RT kernel won't boot: it is one-shot via `grub-reboot`, so the next boot falls back to stock.
- Results not reproducible across reboots: something uncontrolled (ambient, a service, ASLR). Investigate.
- `mitigations=off` shows little effect: this CPU is not affected by Meltdown/MDS (no KPTI). Report what is measured.

## Working principles
- **Validate before you believe.** Phase C gates everything downstream.
- **Deltas, not absolutes.** Same-hardware comparisons are the result.
- **Partition by thermal state.**
- **Variance before conclusions.**
- **Record every configuration.**
- **Name the floor.** SMIs dominating the tail is a finding.
