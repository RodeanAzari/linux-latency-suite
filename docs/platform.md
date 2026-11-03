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
- Kernel `6.12.111+deb13-amd64`, held with `apt-mark hold linux-image-amd64 linux-headers-amd64`. Debian has since moved to 6.12.115.
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

## Sharing with DMA-Engine

This T490 also hosts the DMA-Engine project, which loads an out-of-tree kernel module. The kernel's taint flag (`/proc/sys/kernel/tainted`, bit 12) stays set until reboot even after the module is unloaded. **Measurement runs must start from a fresh boot with taint bits 12 and 13 clear**, and the harness records the taint value in every sidecar.

## SMI and thermal: first observations (not yet measured properly)

- `MSR_SMI_COUNT` (0x34) read **4,813 SMIs after 23 h 23 min of uptime**, about one every 17 s on average. The count includes SMIs during boot, so treat it as a rough rate, not a measurement. Phase D measures the rate per run and the duration.
- Package temperature was 66–81 °C with the fan near 3,500 RPM while another project was compiling. An idle baseline still needs to be taken on a quiet machine.
- Thermal throttle counters on CPU 2 (core and package): 0 and 0.

## Open items

- Idle temperature and fan baseline on a quiet machine.
- Phase D: the stock kernel lacks `HWLAT_TRACER`, so `hwlatdetect` won't work. Plan: SMI-counter deltas around every run, plus a TSC-gap spin on an isolated core.
- Disk image (Phase A): not taken. With DMA-Engine and other projects on the same disk, this is the user's call.
