/* §2.2 Syscall overhead, plus the harness's own timing overhead (§3.1).
 *
 * Each sample brackets one operation with two CLOCK_MONOTONIC reads:
 *   empty     nothing: the cost of the timestamp pair itself (subtract offline)
 *   getppid   a real kernel entry that no vDSO or libc cache can serve
 *   mono      clock_gettime(CLOCK_MONOTONIC), normally vDSO, no kernel entry
 *   mono_raw  clock_gettime(CLOCK_MONOTONIC_RAW), vDSO or syscall by clocksource
 * Every mode has its own copy of the loop with the operation inlined, so
 * `empty` has exactly the instrumentation the other modes have.
 */
#define _GNU_SOURCE
#include "common.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>

#define MEASURE(OP)                                                  \
	for (i = 0; i < warmup + n; i++) {                           \
		t0 = lat_now_ns();                                   \
		OP;                                                  \
		t1 = lat_now_ns();                                   \
		if (i >= warmup) {                                   \
			buf[i - warmup].t_ns = t0;                   \
			buf[i - warmup].v_ns = t1 - t0;              \
		}                                                    \
	}

static void usage(void)
{
	fprintf(stderr,
		"usage: syscall_bench -t empty|getppid|mono|mono_raw [-c cpu] [-p prio]\n"
		"                     [-n samples] [-w warmup] [-m monitor_cpu] [-o outdir] [-T]\n"
		"  defaults: -c 2 -p 90 -n 100000 -w 1000 -m 0 -o .\n"
		"  -T  record even if the kernel is tainted by an out-of-tree module\n");
	exit(2);
}

int main(int argc, char **argv)
{
	int cpu = 2, prio = 90, hk = 0, allow_tainted = 0, opt;
	long n = 100000, warmup = 1000, i;
	const char *outdir = ".", *mode = NULL;
	struct lat_env before, after;
	lat_sample_t *buf;
	int64_t t0, t1;
	struct timespec ts;
	char params[256], name[64];

	while ((opt = getopt(argc, argv, "t:c:p:n:w:m:o:T")) != -1) {
		switch (opt) {
		case 't': mode = optarg; break;
		case 'c': cpu = atoi(optarg); break;
		case 'p': prio = atoi(optarg); break;
		case 'n': n = atol(optarg); break;
		case 'w': warmup = atol(optarg); break;
		case 'm': hk = atoi(optarg); break;
		case 'o': outdir = optarg; break;
		case 'T': allow_tainted = 1; break;
		default: usage();
		}
	}
	if (!mode || (strcmp(mode, "empty") && strcmp(mode, "getppid") &&
		      strcmp(mode, "mono") && strcmp(mode, "mono_raw")))
		usage();
	if (cpu == hk || n <= 0 || warmup < 0)
		usage();

	lat_check_taint(allow_tainted);
	buf = lat_alloc((size_t)n * sizeof(*buf));
	lat_sensors_open(cpu, hk);
	lat_monitor_start(hk, 0); /* runs take milliseconds; before/after env is what counts */
	lat_rt_setup(cpu, prio);
	lat_env_read(&before);

	/* ---- measurement loop: no allocation, I/O or arithmetic beyond the subtraction ---- */
	if (!strcmp(mode, "empty")) {
		MEASURE((void)0);
	} else if (!strcmp(mode, "getppid")) {
		MEASURE(syscall(SYS_getppid));
	} else if (!strcmp(mode, "mono")) {
		MEASURE(clock_gettime(CLOCK_MONOTONIC, &ts));
	} else {
		MEASURE(clock_gettime(CLOCK_MONOTONIC_RAW, &ts));
	}
	/* ---- end of measurement loop ---- */

	lat_env_read(&after);
	lat_monitor_stop();

	snprintf(params, sizeof(params),
		 "\"mode\": \"%s\", \"cpu\": %d, \"prio\": %d, \"policy\": \"SCHED_FIFO\", "
		 "\"monitor_cpu\": %d, \"monitor_period_ms\": 100",
		 mode, cpu, prio, hk);
	snprintf(name, sizeof(name), "syscall_%s.bin", mode);
	lat_write_samples(lat_path(outdir, name), buf, n);
	snprintf(name, sizeof(name), "syscall_%s.monitor.csv", mode);
	lat_write_monitor(lat_path(outdir, name));
	snprintf(name, sizeof(name), "syscall_%s.json", mode);
	lat_write_sidecar(lat_path(outdir, name), "syscall_bench", params, n, warmup, &before,
			  &after);
	printf("syscall_bench: %ld samples of %s (cpu %d, prio %d) -> %s/\n", n, mode, cpu, prio,
	       outdir);
	return 0;
}
