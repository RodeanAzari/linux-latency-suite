/* §2.2 Syscall overhead, plus the harness's own timing overhead (§3.1).
 *
 * Each sample brackets one operation with two CLOCK_MONOTONIC reads:
 *   empty     nothing: the cost of the timestamp pair itself (subtract offline)
 *   getppid   a real kernel entry that no vDSO or libc cache can serve
 *   mono      clock_gettime(CLOCK_MONOTONIC), normally vDSO, no kernel entry
 *   mono_raw  clock_gettime(CLOCK_MONOTONIC_RAW), vDSO or syscall by clocksource
 * Every mode has its own copy of the loop with the operation inlined, so
 * `empty` has exactly the instrumentation the other modes have.
 *
 * Warmup is by time as well as count: at ~50 ns per sample, 1000 iterations
 * last 50 us, while the governor needs tens of ms to raise the clock. Without
 * the time-based warmup, the same mode measured 26 ns or 53 ns depending on
 * where in the ramp it ran.
 */
#define _GNU_SOURCE
#include "common.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>

#define MEASURE(OP)                                                     \
	do {                                                            \
		warm_end = lat_now_ns() + warmup_ms * 1000000LL;        \
		do {                                                    \
			t0 = lat_now_ns();                              \
			OP;                                             \
			t1 = lat_now_ns();                              \
			warm++;                                         \
		} while (warm < warmup || t1 < warm_end);               \
		for (i = 0; i < n; i++) {                               \
			t0 = lat_now_ns();                              \
			OP;                                             \
			t1 = lat_now_ns();                              \
			buf[i].t_ns = t0;                               \
			buf[i].v_ns = t1 - t0;                          \
		}                                                       \
	} while (0)

static void usage(void)
{
	fprintf(stderr,
		"usage: syscall_bench -t empty|getppid|mono|mono_raw [-c cpu] [-p prio]\n"
		"                     [-n samples] [-w warmup] [-W warmup_ms] [-m monitor_cpu]\n"
		"                     [-o outdir] [-T]\n"
		"  defaults: -c 2 -p 90 -n 100000 -w 1000 -W 200 -m 0 -o .\n"
		"  warmup runs at least -w iterations and at least -W milliseconds\n"
		"  -T  record even if the kernel is tainted by an out-of-tree module\n");
	exit(2);
}

int main(int argc, char **argv)
{
	int cpu = 2, prio = 90, hk = 0, allow_tainted = 0, opt;
	long n = 100000, warmup = 1000, warmup_ms = 200, warm = 0, i;
	const char *outdir = ".", *mode = NULL;
	struct lat_env before, after;
	lat_sample_t *buf;
	int64_t t0, t1, warm_end;
	struct timespec ts;
	char params[320], name[64];

	while ((opt = getopt(argc, argv, "t:c:p:n:w:W:m:o:T")) != -1) {
		switch (opt) {
		case 't': mode = optarg; break;
		case 'c': cpu = atoi(optarg); break;
		case 'p': prio = atoi(optarg); break;
		case 'n': n = atol(optarg); break;
		case 'w': warmup = atol(optarg); break;
		case 'W': warmup_ms = atol(optarg); break;
		case 'm': hk = atoi(optarg); break;
		case 'o': outdir = optarg; break;
		case 'T': allow_tainted = 1; break;
		default: usage();
		}
	}
	if (!mode || (strcmp(mode, "empty") && strcmp(mode, "getppid") &&
		      strcmp(mode, "mono") && strcmp(mode, "mono_raw")))
		usage();
	if (cpu == hk || n <= 0 || warmup < 0 || warmup_ms < 0)
		usage();

	lat_check_taint(allow_tainted);
	buf = lat_alloc((size_t)n * sizeof(*buf));
	lat_sensors_open(cpu, hk);
	lat_monitor_start(hk, warmup_ms * 1000000LL);
	lat_rt_setup(cpu, prio);
	lat_env_read(&before);

	/* ---- warmup + measurement loop: no allocation, I/O or arithmetic beyond the subtraction ---- */
	if (!strcmp(mode, "empty"))
		MEASURE((void)0);
	else if (!strcmp(mode, "getppid"))
		MEASURE(syscall(SYS_getppid));
	else if (!strcmp(mode, "mono"))
		MEASURE(clock_gettime(CLOCK_MONOTONIC, &ts));
	else
		MEASURE(clock_gettime(CLOCK_MONOTONIC_RAW, &ts));
	/* ---- end of measurement loop ---- */

	lat_env_read(&after);
	lat_monitor_stop();

	snprintf(params, sizeof(params),
		 "\"mode\": \"%s\", \"cpu\": %d, \"prio\": %d, \"policy\": \"SCHED_FIFO\", "
		 "\"warmup_min_iters\": %ld, \"warmup_ms\": %ld, "
		 "\"monitor_cpu\": %d, \"monitor_period_ms\": 100",
		 mode, cpu, prio, warmup, warmup_ms, hk);
	snprintf(name, sizeof(name), "syscall_%s.bin", mode);
	lat_write_samples(lat_path(outdir, name), buf, n);
	snprintf(name, sizeof(name), "syscall_%s.monitor.csv", mode);
	lat_write_monitor(lat_path(outdir, name));
	snprintf(name, sizeof(name), "syscall_%s.json", mode);
	lat_write_sidecar(lat_path(outdir, name), "syscall_bench", params, n, warm, &before,
			  &after);
	printf("syscall_bench: %ld samples of %s (cpu %d, prio %d, %ld warmup iters) -> %s/\n", n,
	       mode, cpu, prio, warm, outdir);
	return 0;
}
