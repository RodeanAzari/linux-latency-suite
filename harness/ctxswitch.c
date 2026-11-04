/* §2.3 Context switch cost: pipe ping-pong between two pinned SCHED_FIFO threads.
 *
 * Thread A timestamps, writes one byte to B, and blocks reading B's reply.
 * Each sample is one round trip (t1 - t0), stored raw; halving and
 * subtracting timer overhead happen offline.
 *   -a N -b N   same CPU: a round trip is two real context switches
 *   -a 2 -b 6   SMT siblings: two cross-CPU wakeups on one physical core
 *   -a 2 -b 3   different physical cores, shared L3
 * Warmup is at least -w round trips and at least -W ms, so the clock has
 * ramped before sampling (see docs/validation.md, syscall_bench).
 */
#define _GNU_SOURCE
#include "common.h"

#include <errno.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static int p_ab[2], p_ba[2]; /* A->B and B->A pipes */
static int cpu_b, prio;

static void xread(int fd)
{
	char c;
	if (read(fd, &c, 1) != 1)
		lat_die("pipe read: %s", strerror(errno));
}

static void xwrite(int fd)
{
	char c = 0;
	if (write(fd, &c, 1) != 1)
		lat_die("pipe write: %s", strerror(errno));
}

static void *thread_b(void *arg)
{
	char c;

	(void)arg;
	lat_rt_setup(cpu_b, prio);
	/* Echo until A closes its write end. */
	while (read(p_ab[0], &c, 1) == 1)
		xwrite(p_ba[1]);
	return NULL;
}

static void usage(void)
{
	fprintf(stderr,
		"usage: ctxswitch [-a cpuA] [-b cpuB] [-p prio] [-n samples] [-w warmup]\n"
		"                 [-W warmup_ms] [-m monitor_cpu] [-o outdir] [-T]\n"
		"  defaults: -a 2 -b 2 -p 90 -n 100000 -w 1000 -W 200 -m 0 -o .\n"
		"  -T  record even if the kernel is tainted by an out-of-tree module\n");
	exit(2);
}

int main(int argc, char **argv)
{
	int cpu_a = 2, hk = 0, allow_tainted = 0, opt;
	long n = 100000, warmup = 1000, warmup_ms = 200, warm = 0, i;
	const char *outdir = ".";
	struct lat_env before, after;
	lat_sample_t *buf;
	int64_t t0, t1, warm_end;
	pthread_t tb;
	char params[320], name[64];

	cpu_b = 2;
	prio = 90;
	while ((opt = getopt(argc, argv, "a:b:p:n:w:W:m:o:T")) != -1) {
		switch (opt) {
		case 'a': cpu_a = atoi(optarg); break;
		case 'b': cpu_b = atoi(optarg); break;
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
	if (cpu_a == hk || cpu_b == hk || n <= 0 || warmup < 0 || warmup_ms < 0)
		usage();

	lat_check_taint(allow_tainted);
	if (pipe(p_ab) || pipe(p_ba))
		lat_die("pipe: %s", strerror(errno));
	buf = lat_alloc((size_t)n * sizeof(*buf));
	lat_sensors_open(cpu_a, hk);
	/* Monitor sizing only: assume <= 1 ms per round trip. */
	lat_monitor_start(hk, warmup_ms * 1000000LL + n * 1000000LL);
	lat_rt_setup(cpu_a, prio);
	if (pthread_create(&tb, NULL, thread_b, NULL))
		lat_die("pthread_create failed");
	lat_env_read(&before);

	/* ---- warmup + measurement loop: no allocation, I/O or arithmetic beyond the subtraction ---- */
	warm_end = lat_now_ns() + warmup_ms * 1000000LL;
	do {
		xwrite(p_ab[1]);
		xread(p_ba[0]);
		warm++;
	} while (warm < warmup || lat_now_ns() < warm_end);
	for (i = 0; i < n; i++) {
		t0 = lat_now_ns();
		xwrite(p_ab[1]);
		xread(p_ba[0]);
		t1 = lat_now_ns();
		buf[i].t_ns = t0;
		buf[i].v_ns = t1 - t0;
	}
	/* ---- end of measurement loop ---- */

	lat_env_read(&after);
	close(p_ab[1]); /* B's read returns 0 and it exits */
	pthread_join(tb, NULL);
	lat_monitor_stop();

	snprintf(params, sizeof(params),
		 "\"mechanism\": \"pipe\", \"value\": \"round_trip\", \"cpu_a\": %d, \"cpu_b\": %d, "
		 "\"prio\": %d, \"policy\": \"SCHED_FIFO\", \"warmup_min_iters\": %ld, "
		 "\"warmup_ms\": %ld, \"monitor_cpu\": %d, \"monitor_period_ms\": 100",
		 cpu_a, cpu_b, prio, warmup, warmup_ms, hk);
	snprintf(name, sizeof(name), "ctxswitch_%d_%d.bin", cpu_a, cpu_b);
	lat_write_samples(lat_path(outdir, name), buf, n);
	snprintf(name, sizeof(name), "ctxswitch_%d_%d.monitor.csv", cpu_a, cpu_b);
	lat_write_monitor(lat_path(outdir, name));
	snprintf(name, sizeof(name), "ctxswitch_%d_%d.json", cpu_a, cpu_b);
	lat_write_sidecar(lat_path(outdir, name), "ctxswitch", params, n, warm, &before, &after);
	printf("ctxswitch: %ld round trips, cpu %d <-> %d (prio %d, %ld warmup) -> %s/\n", n, cpu_a,
	       cpu_b, prio, warm, outdir);
	return 0;
}
