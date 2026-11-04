/* Phase D gap detector: every interval in which the measured CPU was taken away.
 *
 * A pinned SCHED_FIFO thread spins reading CLOCK_MONOTONIC. Any interval
 * between consecutive reads longer than -g ns means the CPU did something
 * else: an interrupt (on stock, the 250 Hz tick), a kernel thread, or an SMI,
 * which the OS cannot see at all. Each gap is recorded with MSR_SMI_COUNT read
 * on the measured CPU itself; a gap during which the count moved is an SMI.
 * This is the userspace analogue of the kernel's hwlat tracer, which the stock
 * Debian kernel lacks; the RT kernel has it, for cross-checking.
 *
 * The loop does one compare per iteration; work happens only after a gap,
 * and the clock is re-read afterwards so that work is never counted as a gap.
 * Output record: <i8 t_ns (gap start), <i8 gap_ns, <i8 smi_count.
 */
#define _GNU_SOURCE
#include "common.h"

#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define MSR_SMI_COUNT 0x34

typedef struct {
	int64_t t_ns;
	int64_t gap_ns;
	int64_t smi_count;
} gap_t;

static void usage(void)
{
	fprintf(stderr,
		"usage: hwgap [-c cpu] [-p prio] [-d seconds] [-g gap_ns] [-N max_gaps]\n"
		"             [-m monitor_cpu] [-o outdir] [-T]\n"
		"  defaults: -c 2 -p 90 -d 60 -g 1000 -N 2000000 -m 0 -o .\n"
		"  -T  record even if the kernel is tainted by an out-of-tree module\n");
	exit(2);
}

static long read_sysctl(const char *path)
{
	FILE *f = fopen(path, "r");
	long v = -1;
	if (f) {
		if (fscanf(f, "%ld", &v) != 1)
			v = -1;
		fclose(f);
	}
	return v;
}

int main(int argc, char **argv)
{
	int cpu = 2, prio = 90, hk = 0, allow_tainted = 0, msr, opt;
	long dur_s = 60, gap_min = 1000, cap = 2000000, n = 0, overflow = 0;
	long iters = 0;
	const char *outdir = ".";
	struct lat_env before, after;
	gap_t *gaps;
	int64_t prev, t, end, start;
	uint64_t smi;
	char path[64], params[512], name[64];
	FILE *f;

	while ((opt = getopt(argc, argv, "c:p:d:g:N:m:o:T")) != -1) {
		switch (opt) {
		case 'c': cpu = atoi(optarg); break;
		case 'p': prio = atoi(optarg); break;
		case 'd': dur_s = atol(optarg); break;
		case 'g': gap_min = atol(optarg); break;
		case 'N': cap = atol(optarg); break;
		case 'm': hk = atoi(optarg); break;
		case 'o': outdir = optarg; break;
		case 'T': allow_tainted = 1; break;
		default: usage();
		}
	}
	if (cpu == hk || dur_s <= 0 || gap_min <= 0 || cap <= 0)
		usage();

	lat_check_taint(allow_tainted);
	snprintf(path, sizeof(path), "/dev/cpu/%d/msr", cpu);
	msr = open(path, O_RDONLY | O_CLOEXEC);
	if (msr < 0)
		lat_die("%s: %s (run `modprobe msr` as root): SMI attribution needs it", path,
			strerror(errno));
	gaps = lat_alloc((size_t)cap * sizeof(*gaps));
	lat_sensors_open(cpu, hk);
	lat_monitor_start(hk, dur_s * 1000000000LL);
	lat_rt_setup(cpu, prio);
	lat_env_read(&before);

	/* ---- spin loop: one compare per iteration; work only after a gap ---- */
	start = prev = lat_now_ns();
	end = start + dur_s * 1000000000LL;
	while (prev < end) {
		t = lat_now_ns();
		iters++;
		if (t - prev > gap_min) {
			if (n < cap) {
				gaps[n].t_ns = prev;
				gaps[n].gap_ns = t - prev;
				gaps[n].smi_count = pread(msr, &smi, sizeof(smi), MSR_SMI_COUNT) ==
							    sizeof(smi)
							    ? (int64_t)(smi & 0xffffffffu)
							    : -1;
				n++;
			} else {
				overflow++;
			}
			t = lat_now_ns(); /* the MSR read is not the next gap */
		}
		prev = t;
	}
	/* ---- end of spin loop ---- */

	lat_env_read(&after);
	lat_monitor_stop();

	snprintf(name, sizeof(name), "hwgap_cpu%d.bin", cpu);
	f = fopen(lat_path(outdir, name), "wb");
	if (!f || fwrite(gaps, sizeof(*gaps), (size_t)n, f) != (size_t)n || fclose(f))
		lat_die("%s: write failed", name);
	snprintf(params, sizeof(params),
		 "\"record\": \"<i8 t_ns, <i8 gap_ns, <i8 smi_count\", "
		 "\"gap_threshold_ns\": %ld, \"duration_s\": %ld, \"spin_ns\": %lld, "
		 "\"loop_iterations\": %ld, \"gaps_dropped\": %ld, "
		 "\"sched_rt_runtime_us\": %ld, \"cpu\": %d, \"prio\": %d, "
		 "\"policy\": \"SCHED_FIFO\", \"monitor_cpu\": %d, \"monitor_period_ms\": 100",
		 gap_min, dur_s, (long long)(prev - start), iters, overflow,
		 read_sysctl("/proc/sys/kernel/sched_rt_runtime_us"), cpu, prio, hk);
	snprintf(name, sizeof(name), "hwgap_cpu%d.monitor.csv", cpu);
	lat_write_monitor(lat_path(outdir, name));
	snprintf(name, sizeof(name), "hwgap_cpu%d.json", cpu);
	lat_write_sidecar(lat_path(outdir, name), "hwgap", params, n, 0, &before, &after);
	printf("hwgap: %ld gaps > %ld ns in %ld s on cpu %d (%ld iterations, %ld dropped) -> %s/\n",
	       n, gap_min, dur_s, cpu, iters, overflow, outdir);
	return overflow ? 1 : 0;
}
