# Platform

Everything here was read from the machine, not typed from memory. Recorded 2026-11-02.

## Hardware

| | |
|---|---|
| Machine | Lenovo ThinkPad T490 |
| CPU | Intel Core i5-8365U (Whiskey Lake), 4 cores / 8 threads, base 1.6 GHz |
| SMT siblings | 0/4, 1/5, 2/6, 3/7 |
| Caches | L1d 32 KiB and L2 256 KiB per core; L3 6 MiB shared |
| Memory | 15 GiB, one NUMA node |
| Storage | NVMe, `/dev/nvme0n1` |
| Network | Wi-Fi only (`iwlwifi`); Ethernet `enp0s31f6` unused |
| Power | AC adapter connected for all runs; battery full |

## Firmware

BIOS **N2IETA6W (1.84)**, dated 2025-07-03. Read as root from `/sys/class/firmware-attributes/thinklmi/attributes/*/current_value`, so every run's sidecar can record it automatically.

| Setting | Value | Why it matters |
|---|---|---|
| SecureBoot | Disable | Unsigned modules (`msr`, harness helpers) load |
| HyperThreadingTechnology | Enable | SMT is controlled at boot with `nosmt` (config 5), not in BIOS |
| SpeedStep | Enable | Frequency is controlled by `intel_pstate` and the governor (config 1) |
| CPUPowerManagement | Enable | C-states are controlled by kernel cmdline (config 2) |
| AdaptiveThermalManagementAC | MaximizePerformance | Fan and thermal policy on AC |
| AdaptiveThermalManagementBattery | Balanced | Not used: runs are on AC |
| VirtualizationTechnology / VTdFeature | Enable / Enable | |
| KernelDMAProtection | Enable | |
| AMTControl | Enable | Intel AMT/ME, a possible SMI source (see below) |
| I8254ClockGating | Auto | |

This firmware has **no C-state or Turbo switch**, unlike some other ThinkPads. Turbo is turned off through `/sys/devices/system/cpu/intel_pstate/no_turbo`, and C-states through `intel_idle.max_cstate`. **Do not change any BIOS setting during the campaign**: doing so invalidates earlier runs.

## OS and kernel

- Debian 13 (trixie), minimal install with no desktop.
- Kernels: stock **`6.12.115+deb13.1-amd64`** and PREEMPT_RT **`6.12.115+deb13.1-rt-amd64`**, same Debian release, so the RT comparison changes only the preemption model. Both images and their header metapackages are held with `apt-mark hold`. 6.12.111 and 6.12.107 remain installed as GRUB fallbacks.
- GRUB: `GRUB_DEFAULT=saved`, with the saved entry set to stock 6.12.115 by name. Debian's menu lists the RT kernel first, so `GRUB_DEFAULT=0` would have booted RT. RT is booted one-shot with `grub-reboot`, so a failed RT boot falls back to stock on the next power cycle.
- Kconfig: `NO_HZ_FULL=y`, `RCU_NOCB_CPU=y`, `PREEMPT_DYNAMIC=y` (voluntary by default), `HZ=250`, **`HWLAT_TRACER` not set**.
- Clocksource `tsc`; CPU flags `constant_tsc` and `nonstop_tsc`.
- Default `intel_pstate` governor is `powersave` with turbo on. `intel_idle` exposes C-states down to C10.

### Speculative-execution mitigations (stock)

Meltdown, MDS and L1TF are **Not affected**, so the kernel runs without KPTI page-table isolation. Active mitigations include Enhanced IBRS (retbleed), a BHI software loop on syscall entry, VERW buffer clearing (mmio_stale_data) and IBPB (vmscape). Expect `mitigations=off` to change syscall cost by less than on a pre-2019 CPU.

## Background services

Disabled with `systemctl disable --now` (reversible with `enable --now`):

| Unit | Reason |
|---|---|
| `avahi-daemon.service` / `.socket` | mDNS broadcasts; SSH uses the IP address |
| `bluetooth.service` | Unused radio |
| `ModemManager.service` | No modem |
| `cron.service`, `anacron.service` / `.timer` | No crontabs on the machine; scheduled wakeups |
| `apt-daily.timer`, `apt-daily-upgrade.timer` | Background package activity; the kernel is held |
| `man-db.timer`, `e2scrub_all.timer`, `fstrim.timer`, `dpkg-db-backup.timer` | Periodic disk and CPU work |

Kept running: `ssh`, `NetworkManager`, `wpa_supplicant` (the only route in), `systemd-journald`, `logind`, `udevd`, `timesyncd`, `dbus`, `polkit`, `bolt`, `getty@tty1`. Kept as timers: `systemd-tmpfiles-clean` and `logrotate`; the run script stops them during measurement.

## Kernel taint

The machine previously hosted a project that loaded out-of-tree modules; that project is finished. The harness still records `/proc/sys/kernel/tainted` in every sidecar and **rejects a run if taint bit 12 (out-of-tree) or 13 (unsigned) is set**, since the flag stays set until reboot.

## Idle baseline and first SMI observation

Taken 2026-11-03 on a fresh boot (stock 6.12.115, taint 0, defaults: `powersave`, turbo on, all C-states), 5 minutes idle, sampled every 10 s:

| Metric | Value |
|---|---|
| Package temperature | mean 36.2 °C, min 34, max 48 |
| Fan | 0 RPM (off) |
| Mean `scaling_cur_freq` across CPUs | 842 MHz |
| Thermal throttle events (core / package) | 0 / 0 |
| `MSR_SMI_COUNT` (0x34) at 22 s after boot | **4,710** |
| SMIs during the 303 s idle window | **2** (about one per 150 s) |

**Almost all SMIs happen during boot.** An earlier reading of 4,813 after 23 h had suggested one SMI every 17 s, but nearly all of those were from boot. The steady-state rate at idle is about two orders of magnitude lower. So the harness must take SMI deltas around each run, never a since-boot count. Phase D measures the rate under load and the duration of each SMI.

## Open items

- Phase D: the stock kernel lacks `HWLAT_TRACER`, so `hwlatdetect` won't work. Plan: SMI-counter deltas around every run, plus a TSC-gap spin on an isolated core.
- No disk image taken. The machine is reproducible from this document plus the repo: Debian 13 minimal, the package list in `progress.md`, the services above, and the GRUB setup.
