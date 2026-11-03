/* §2.1 Scheduler wakeup latency.
 *
 * Sleep to an absolute CLOCK_MONOTONIC deadline, wake, and record how late we
 * woke. Deadlines advance by a fixed interval from the previous deadline, never
 * from the wake time, so error doesn't accumulate (same method as cyclictest).
 */
#define _GNU_SOURCE
#include "common.h"

#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

static void usage(void)
{
	fprintf(stderr,
		"usage: sched_latency [-c cpu] [-p prio] [-i interval_us] [-n samples]\n"
		"                     [-w warmup] [-m monitor_cpu] [-o outdir] [-T]\n"
		"  defaults: -c 2 -p 90 -i 1000 -n 100000 -w 1000 -m 0 -o .\n"
		"  -T  record even if the kernel is tainted by an out-of-tree module\n");
	exit(2);
}

int main(int argc, char **argv)
{
	int cpu = 2, prio = 90, hk = 0, allow_tainted = 0, opt;
	long interval_us = 1000, n = 100000, warmup = 1000, i;
	const char *outdir = ".";
	struct lat_env before, after;
	lat_sample_t *buf;
	int64_t interval_ns, deadline, woke;
	struct timespec ts;
	char params[256];

	while ((opt = getopt(argc, argv, "c:p:i:n:w:m:o:T")) != -1) {
		switch (opt) {
		case 'c': cpu = atoi(optarg); break;
		case 'p': prio = atoi(optarg); break;
		case 'i': interval_us = atol(optarg); break;
		case 'n': n = atol(optarg); break;
		case 'w': warmup = atol(optarg); break;
		case 'm': hk = atoi(optarg); break;
		case 'o': outdir = optarg; break;
		case 'T': allow_tainted = 1; break;
		default: usage();
		}
	}
	if (cpu == hk || n <= 0 || warmup < 0 || interval_us <= 0)
		usage();
	interval_ns = interval_us * 1000;

	lat_check_taint(allow_tainted);
	buf = lat_alloc((size_t)n * sizeof(*buf));
	lat_sensors_open(cpu, hk);
	lat_monitor_start(hk, (n + warmup) * interval_ns);
	lat_rt_setup(cpu, prio);
	lat_env_read(&before);

	/* ---- measurement loop: no allocation, I/O or arithmetic beyond the subtraction ---- */
	deadline = lat_now_ns() + interval_ns;
	for (i = 0; i < warmup + n; i++) {
		ts = lat_ns_to_ts(deadline);
		clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &ts, NULL);
		woke = lat_now_ns();
		if (i >= warmup) {
			buf[i - warmup].t_ns = deadline;
			buf[i - warmup].v_ns = woke - deadline;
		}
		deadline += interval_ns;
	}
	/* ---- end of measurement loop ---- */

	lat_env_read(&after);
	lat_monitor_stop();

	snprintf(params, sizeof(params),
		 "\"cpu\": %d, \"prio\": %d, \"policy\": \"SCHED_FIFO\", \"interval_us\": %ld, "
		 "\"monitor_cpu\": %d, \"monitor_period_ms\": 100",
		 cpu, prio, interval_us, hk);
	lat_write_samples(lat_path(outdir, "sched_latency.bin"), buf, n);
	lat_write_monitor(lat_path(outdir, "sched_latency.monitor.csv"));
	lat_write_sidecar(lat_path(outdir, "sched_latency.json"), "sched_latency", params, n,
			  warmup, &before, &after);
	printf("sched_latency: %ld samples (cpu %d, prio %d, %ld us) -> %s/\n", n, cpu, prio,
	       interval_us, outdir);
	return 0;
}
