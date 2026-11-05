# Build plan — Linux Latency Characterization Suite

The full project spec, moved out of CLAUDE.md so it is not loaded every turn. Section numbers are unchanged: every `§N` reference in code, scripts and docs points here. Live status is in CLAUDE.md ("Current status"); decisions that override this spec are in `progress.md`.

## What this is

A reproducible measurement harness that quantifies where latency comes from on a Linux system, and how much each tuning knob actually buys. Built and run on a **dedicated ThinkPad T490 with full BIOS and kernel control.**

The output is not a number. It is a **matrix**: five latency classes × eight system configurations, with percentile distributions, run-to-run variance, and thermal annotation — plus a written analysis of which knobs mattered and which didn't.

**Duration: 1–2 weeks.** Week 1 builds the harness and establishes a validated baseline. Week 2 runs the configuration matrix and writes the analysis. Going longer is fine; shipping a half-measured matrix is not.


> ### ⚠ The platform caveat, up front
>
> A T490 is a laptop: thermally constrained, with firmware SMIs you cannot disable and a shared power envelope. **Absolute numbers from this machine are not server numbers.**
>
> This does not invalidate the project — it defines it. The work is to (a) measure the platform's irreducible floor and *name* it, (b) report **deltas between configurations on the same hardware**, which are meaningful, and (c) detect and annotate thermal throttling rather than silently averaging over it. §3 is the methodology that makes this credible, and it is the most important section in this document.

---
## 1. Machine and setup

**ThinkPad T490**, wiped, dedicated, headless, SSH from a second machine. Full ownership of BIOS and kernel is what makes this project possible at all.

### 1.1 Distro

**Debian 12**, minimal install, **no desktop environment.** Not Ubuntu Desktop — background services, snapd and GNOME all generate timer activity and CPU wakeups that pollute measurements. The fewer processes on the box, the cleaner the data.

```
systemd-analyze blame        # audit what starts at boot
systemctl list-units --type=service --state=running
```

Disable anything you don't need. Document what you disabled — it's part of reproducibility.

### 1.2 BIOS settings to record and control

Record the state of every one of these before you start. Changing them mid-campaign invalidates earlier runs.

| Setting | Why it matters |
|---|---|
| **Secure Boot** | Must be **off** — unsigned kernel modules won't load otherwise |
| Intel SpeedStep / Turbo | Turbo causes frequency variance; disabling it trades throughput for determinism |
| C-States | Deep C-state exit latency is a major p99.9 contributor |
| Hyper-Threading / SMT | Sibling contention adds jitter |
| Thermal mode / fan policy | Set to maximum performance; document it |

⚠ **You cannot disable SMIs on this machine.** System Management Interrupts are firmware traps invisible to the OS — the CPU vanishes for microseconds and Linux never knows. On server boards you can often reduce them in BIOS; on a ThinkPad you cannot. **Measuring them is Phase D**, and naming SMI as your irreducible floor is a genuinely strong finding, not an admission of defeat.

### 1.3 Packages

```bash
sudo apt install build-essential linux-headers-$(uname -r) \
  rt-tests stress-ng linux-perf trace-cmd kernelshark \
  python3 python3-numpy python3-matplotlib python3-pandas \
  cpufrequtils msr-tools lm-sensors git tmux
```

`rt-tests` provides `cyclictest` and `hwlatdetect` — used as **reference implementations to validate your harness against**, not as the harness itself.

---

## 2. What gets measured

Five classes. Each needs its own measurement technique; don't try to unify them.

### 2.1 Scheduler wakeup latency
A thread sleeps on a timer, wakes, and measures actual vs. intended wake time. The classic real-time metric and the one `cyclictest` reports.

Implement with `clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME)` and absolute deadlines — never relative sleeps, which accumulate drift.

### 2.2 Syscall overhead
Null syscall cost. Measure three distinct things, because they differ by an order of magnitude:
- A true syscall that cannot be served by vDSO (`getppid()`)
- `clock_gettime(CLOCK_MONOTONIC)` — normally vDSO, no kernel entry
- `clock_gettime(CLOCK_MONOTONIC_RAW)` behaviour, which may or may not go to the kernel depending on clocksource

**This is where speculative-execution mitigations show up.** The `mitigations=off` delta on syscall cost is one of the strongest single findings available in this project.

### 2.3 Context switch cost
Pipe or eventfd ping-pong between two threads. Measure three placements:
- Same physical core, SMT siblings
- Different physical cores, same L3
- Pinned to isolated vs. non-isolated cores

### 2.4 Memory subsystem
- Pointer-chase latency across working-set sizes, to map L1/L2/L3/DRAM
- TLB miss cost: 4 KiB pages vs. hugepages over a large working set
- Validate against `perf stat -e cache-misses,dTLB-load-misses`

### 2.5 Interrupt and IPC path
- Loopback UDP round-trip
- `eventfd` wakeup latency
- Timer interrupt jitter under `nohz_full` vs. stock

**Out of scope:** DPDK and kernel-bypass NIC work. The T490's Intel I219-LM has poor DPDK support. If you want a bypass comparison, use **AF_XDP**, which works on in-tree drivers — but treat it as optional, Phase G at the earliest.

---

## 3. Methodology — the section that makes this credible

A project that skips any of these is a tutorial. One that implements all of them is an engineering artifact.

### 3.1 Timing

Use `clock_gettime(CLOCK_MONOTONIC)` as the default. Check for invariant TSC first:

```bash
grep -o 'constant_tsc\|nonstop_tsc' /proc/cpuinfo | sort -u
cat /sys/devices/system/clocksource/clocksource0/current_clocksource
```

If you use `rdtscp` directly for the lowest-overhead path, you must: confirm invariant TSC, calibrate against `CLOCK_MONOTONIC`, use `rdtscp` (not `rdtsc`) for its implicit serialization, and pin the thread — TSC is per-package-synchronized on this CPU but migration still invalidates your assumptions.

**Measure and subtract your own instrumentation overhead.** Time an empty measurement loop; report that number in the README. If your timer costs 25 ns and you're measuring a 40 ns syscall, say so.

### 3.2 Process setup — all of these, every run

```c
mlockall(MCL_CURRENT | MCL_FUTURE);   /* no page faults mid-measurement */
sched_setaffinity(...);                /* pin to a specific core        */
sched_setscheduler(SCHED_FIFO, prio);  /* document the priority         */
```

Pre-fault and touch every buffer before the measurement loop. Disable ASLR for the run if you want reproducible cache layout (`setarch -R`).

### 3.3 Warmup and sample count

1,000 warmup iterations discarded, then **at least 100,000 measured** per configuration. Tail latency is the point; p99.9 on 10,000 samples is ten data points and means nothing.

### 3.4 Raw samples, offline statistics

Write every sample to a binary file. **Never compute statistics inside the measurement loop** — the arithmetic perturbs what you're measuring. Percentiles, histograms and comparisons all happen in Python afterward.

### 3.5 ⚠ Thermal annotation — the move that answers the laptop objection

Log package temperature and current frequency alongside every sample batch, from `/sys/class/thermal/` and `/sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq`. Also read the thermal-throttle counters:

```
/sys/devices/system/cpu/cpu*/thermal_throttle/core_throttle_count
```

Then in analysis, **partition the samples into throttled and unthrottled** and report both. "p99.9 was 340 µs overall, but 95 µs excluding the 4.2% of samples taken while the package was thermally throttled" is a far better result than either number alone — it shows you understood your platform instead of being defeated by it.

This single practice is what converts "measurements on a laptop" from a weakness into a demonstration of rigor.

### 3.6 Run-to-run variance

Every configuration runs **at least three separate times, with a reboot between.** Report the spread across runs. If run-to-run variance exceeds the difference between two configurations, **you have not shown those configurations differ** — say so explicitly rather than reporting the mean difference.

### 3.7 Validation against reference tools

Your scheduler-latency harness must be cross-checked against `cyclictest` on the same configuration. They should agree within a documented tolerance. If they don't, your harness is wrong — find out why before trusting anything else.

Document the comparison in `docs/validation.md`. **A harness nobody validated is a harness nobody should believe.**

---

## 4. Configuration matrix

Each configuration is a kernel command line plus a runtime setup. Define them as data, not as prose.

| # | Name | Kernel cmdline / setup |
|---|---|---|
| 0 | `baseline` | Stock Debian kernel, defaults, nothing tuned |
| 1 | `governor` | `cpupower frequency-set -g performance`, turbo off |
| 2 | `cstates` | + `intel_idle.max_cstate=0 processor.max_cstate=1` |
| 3 | `isolate` | + `isolcpus=2,3 nohz_full=2,3 rcu_nocbs=2,3` |
| 4 | `irqaffinity` | + `irqaffinity=0,1`, all IRQs moved off isolated cores |
| 5 | `nosmt` | + `nosmt` |
| 6 | `nomitigations` | + `mitigations=off` |
| 7 | `rt` | PREEMPT_RT kernel, all of the above |

Configurations are **cumulative** — each adds to the previous. That isolates the marginal contribution of each knob, which is the actual question. Also run a few non-cumulative spot checks (baseline + `mitigations=off` alone) to confirm the knobs are independent; if they aren't, that's a finding.

### 4.1 Hugepages

Orthogonal to the above. Run the memory-subsystem tests with and without hugepages at the best-performing configuration rather than adding two more rows.

### 4.2 Load conditions

Each configuration runs under two conditions:
- **Idle** — nothing else on the box
- **Loaded** — `stress-ng --cpu N --io 2 --vm 2` on the *non-isolated* cores

The loaded case is where isolation earns its keep. If `isolcpus` shows no benefit under idle but a large one under load, that is the headline result.

---

## 5. Automation

Twelve-plus reboots across the matrix, three runs each, is too many to drive by hand. Script it.

```
scripts/
├── set-config.sh      # rewrite GRUB cmdline for config N, update-grub
├── run-suite.sh       # runs all five measurement classes, writes raw samples
├── collect.sh         # on boot: detect configured run, execute, store, reboot into next
├── analyze.py         # percentiles, throttle partitioning, variance
└── plot.py            # HDR-style histograms, per-knob delta charts
```

A systemd unit that fires `collect.sh` at boot, runs the pending configuration, and reboots into the next makes the whole campaign unattended overnight. **This automation is itself a resume-relevant artifact** — every posting in the target list names scripting and automation, and "I automated a 48-run, 24-reboot measurement campaign" is concrete.

Store results as `results/<config>/<run>/<test>.bin` plus a JSON sidecar recording kernel version, cmdline, BIOS settings, ambient conditions and timestamp. **A result without its full configuration recorded is not a result.**

---

## 6. PREEMPT_RT

Phase F. Build a `PREEMPT_RT` kernel for Debian from `kernel.org` sources plus the RT patch matching that version.

Budget a full day: the build on four cores takes a couple of hours, and expect at least one failed boot. **This is exactly why the project is on a sacrificial machine** — keep the previous kernel in the GRUB menu so a failed boot costs a menu selection.

Report the RT kernel's cost as well as its benefit. RT typically improves worst-case latency and *reduces* throughput; measuring both is the honest comparison.

---

## 7. Repository layout

```
├── README.md                  # the result: matrix, plots, findings, caveats
├── harness/
│   ├── sched_latency.c        # §2.1
│   ├── syscall_bench.c        # §2.2
│   ├── ctxswitch.c            # §2.3
│   ├── memlat.c               # §2.4
│   ├── ipc_latency.c          # §2.5
│   ├── common.c/.h            # timing, pinning, mlockall, sample I/O
│   └── Makefile
├── scripts/                   # §5
├── configs/
│   └── matrix.json            # the §4 table as data
├── results/                   # raw samples + JSON sidecars (gitignore the bulk)
├── analysis/
│   ├── analyze.py
│   └── plot.py
├── docs/
│   ├── methodology.md         # §3, written out properly
│   ├── validation.md          # §3.7 cyclictest cross-check
│   ├── platform.md            # BIOS settings, SMI findings, thermal behaviour
│   └── results.md             # the full matrix
└── .github/workflows/         # build + lint the harness
```

Commit a **representative subset** of raw samples, not gigabytes. Commit all derived statistics.

---

## 8. Phases and definitions of done

### Phase A — Machine prep (1–2 days)
- [ ] T490 wiped, Debian 12 minimal, headless, SSH working
- [ ] Secure Boot off; all §1.2 BIOS settings recorded in `docs/platform.md`
- [ ] Background services audited and trimmed; list documented
- [ ] Packages installed; `cyclictest` runs
- [ ] Disk image taken so re-flattening is cheap

### Phase B — Harness core (3–4 days)
- [ ] All five measurement classes implemented
- [ ] Every one uses `mlockall`, pinning, `SCHED_FIFO`, pre-faulting (§3.2)
- [ ] Instrumentation overhead measured and documented
- [ ] Raw binary sample output with JSON sidecars
- [ ] 100k+ samples per run, 1k warmup discarded
- [ ] No statistics computed inside any measurement loop

### Phase C — Validation (1 day)
- [ ] Scheduler harness agrees with `cyclictest` within a documented tolerance on the same config
- [ ] Memory results consistent with `perf stat` cache/TLB counters
- [ ] `docs/validation.md` written, including anything that disagreed and why

**→ Until Phase C passes, no result from this project is trustworthy. Do not skip it.**

### Phase D — Platform floor (1 day)
- [ ] `hwlatdetect` run; SMI frequency and duration characterized
- [ ] Thermal logging integrated into every measurement run
- [ ] Throttle counters read and recorded per batch
- [ ] `docs/platform.md` states the machine's irreducible latency floor and its cause

### Phase E — Matrix (2–3 days)
- [ ] All 8 configurations defined in `configs/matrix.json`
- [ ] Boot-time automation runs a configuration and reboots into the next
- [ ] 3 runs per configuration, idle and loaded
- [ ] All results stored with full configuration metadata

### Phase F — PREEMPT_RT (1–2 days)
- [ ] RT kernel built and booting; previous kernel retained in GRUB
- [ ] Full matrix run under RT
- [ ] Throughput cost measured alongside latency benefit

### Phase G — Analysis and report (2 days)
- [ ] Percentiles computed: p50 / p90 / p99 / p99.9 / p99.99 / max
- [ ] Samples partitioned by thermal throttle state (§3.5)
- [ ] Run-to-run variance reported; differences smaller than variance flagged as inconclusive
- [ ] Per-knob marginal contribution chart
- [ ] Histograms for each class
- [ ] README written with findings and caveats

---

## 9. Out of scope

- DPDK (the I219-LM is not well supported). AF_XDP optional, Phase G at the earliest.
- Comparison against server-class hardware you don't own. Don't speculate about Xeon numbers.
- Kernel patching beyond applying the RT patch
- Real-time scheduling theory. Measure, don't write a survey.
- FPGA or hardware timestamping. That's Project 2's territory.
- Chasing sub-nanosecond precision. Your instrumentation overhead sets the floor; characterize it and move on.

---

## 10. Known failure modes

- **`cyclictest` and your harness disagree** — usually a relative vs. absolute sleep bug. Use `TIMER_ABSTIME` with an absolute deadline.
- **Unexpectedly bimodal results** — thread migrated between cores. Verify affinity actually took; `sched_setaffinity` can silently fail against cgroup restrictions.
- **p99.9 dominated by a handful of enormous outliers** — SMI or thermal. Phase D exists to distinguish the two. Don't discard outliers without identifying them.
- **`isolcpus` appears to do nothing** — you measured idle only. The benefit appears under load (§4.2).
- **Frequency drifting mid-run** — governor not set, or turbo still on. Log `scaling_cur_freq` continuously, not just once at start.
- **RT kernel won't boot** — keep the old kernel in GRUB. This is the designed-for case, not an emergency.
- **Results not reproducible across reboots** — something uncontrolled: ambient temperature, a background service, ASLR. This is why §3.6 mandates three runs; if you can't reproduce, that's the finding to investigate.
- **`mitigations=off` shows no effect** — check the CPU actually had mitigations active (`/sys/devices/system/cpu/vulnerabilities/*`). Some are microcode-dependent.

---

## 11. Deliverables

**README:**
- One-paragraph summary of the headline findings
- The matrix: 5 classes × 8 configurations, p50/p99/p99.9
- Per-knob marginal contribution chart — the single most communicative plot
- Platform floor section: SMI frequency, thermal behaviour, what that implies
- Methodology summary with a link to `docs/methodology.md`
- **Explicit limitations section.** Laptop, not server. Absolute numbers are platform-specific. Deltas are the result.

**Resume line:**

> **Linux Latency Characterization Suite** · C, Python, kernel tuning, PREEMPT_RT · [github]
> • Built a measurement harness for scheduler wakeup, syscall, context-switch, memory and IPC latency; 100k+ samples per run with `mlockall`, core pinning and `SCHED_FIFO`, validated against `cyclictest`
> • Automated a 48-run measurement campaign (8 cumulative kernel configurations × 3 reboots × idle/loaded) that executes unattended via a boot-time systemd unit
> • Quantified per-knob marginal contribution; `mitigations=off` cut null-syscall latency __%, isolation cut loaded p99.9 __%
> • Identified firmware SMIs as the platform's irreducible floor via `hwlatdetect`; partitioned results by thermal throttle state to separate platform effects from tuning effects

That last bullet is the one that distinguishes this from a tutorial. Lead with it in conversation.

---

## 12. Working principles

- **Validate before you believe.** Phase C gates everything downstream.
- **Deltas, not absolutes.** The platform limits what the absolute numbers mean; the comparison between configurations on identical hardware is the real result.
- **Partition by thermal state.** It is the difference between being limited by a laptop and understanding one.
- **Variance before conclusions.** If run-to-run spread exceeds the effect, there is no effect to report.
- **Record every configuration.** A number without its kernel cmdline, BIOS state and thermal context is not data.
- **Name the floor.** Finding that SMIs dominate your tail is a result, not a failure.
