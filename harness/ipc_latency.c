/* §2.5 IPC path: loopback UDP round trip and eventfd wakeup latency.
 *
 * Two pinned SCHED_FIFO threads, A (-a) and B (-b):
 *   -t udp      A sends an 8-byte datagram over 127.0.0.1, B echoes it back.
 *               Sample = round trip, timed by A.
 *   -t eventfd  A takes t0 and writes an eventfd; B, blocked in read(), takes
 *               t1 when it returns. Sample = t1 - t0, one way (write syscall +
 *               wakeup + switch-in), stored by B. B then signals A on a second
 *               eventfd so rounds never overlap. CLOCK_MONOTONIC is TSC-backed
 *               and invariant across CPUs here, so one-way timing is valid.
 * Timer interrupt jitter (§2.5's third item) needs a busy-spin gap detector
 * rather than a ping-pong, and is measured with the Phase D tool.
 * Warmup is at least -w rounds and at least -W ms (see syscall_bench).
 */
#define _GNU_SOURCE
#include "common.h"

#include <arpa/inet.h>
#include <errno.h>
#include <netinet/in.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/eventfd.h>
#include <sys/socket.h>
#include <unistd.h>

#define STOP (-1L)

static int cpu_b, prio, use_udp;
static int sock_a, sock_b;      /* udp: connected to each other */
static int efd_ab, efd_ba;      /* eventfd: A->B wake, B->A pacing */
static lat_sample_t *buf;
/* eventfd: A publishes the round's t0 and index (<0 = warmup, STOP = exit)
 * before the write; the eventfd write/read pair orders them for B. */
static _Atomic int64_t shared_t0;
static _Atomic long shared_idx;

static void efd_write(int fd)
{
	uint64_t one = 1;
	if (write(fd, &one, sizeof(one)) != sizeof(one))
		lat_die("eventfd write: %s", strerror(errno));
}

static void efd_read(int fd)
{
	uint64_t v;
	if (read(fd, &v, sizeof(v)) != sizeof(v))
		lat_die("eventfd read: %s", strerror(errno));
}

static void udp_send(int s, long v)
{
	if (send(s, &v, sizeof(v), 0) != sizeof(v))
		lat_die("send: %s", strerror(errno));
}

static long udp_recv(int s)
{
	long v;
	if (recv(s, &v, sizeof(v), 0) != sizeof(v))
		lat_die("recv: %s", strerror(errno));
	return v;
}

static void *thread_b(void *arg)
{
	int64_t t1;
	long idx;

	(void)arg;
	lat_rt_setup(cpu_b, prio);
	if (use_udp) {
		long v;
		while ((v = udp_recv(sock_b)) != STOP)
			udp_send(sock_b, v);
		return NULL;
	}
	for (;;) {
		efd_read(efd_ab);
		t1 = lat_now_ns();
		idx = atomic_load_explicit(&shared_idx, memory_order_acquire);
		if (idx == STOP)
			return NULL;
		if (idx >= 0) {
			buf[idx].t_ns = atomic_load_explicit(&shared_t0, memory_order_relaxed);
			buf[idx].v_ns = t1 - buf[idx].t_ns;
		}
		efd_write(efd_ba);
	}
}

/* One eventfd round from A's side; idx < 0 for warmup. */
static inline void efd_round(long idx)
{
	atomic_store_explicit(&shared_t0, lat_now_ns(), memory_order_relaxed);
	atomic_store_explicit(&shared_idx, idx, memory_order_release);
	efd_write(efd_ab);
	efd_read(efd_ba);
}

static void udp_pair(void)
{
	struct sockaddr_in a = { .sin_family = AF_INET }, b;
	socklen_t len = sizeof(a);

	a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
	b = a;
	sock_a = socket(AF_INET, SOCK_DGRAM, 0);
	sock_b = socket(AF_INET, SOCK_DGRAM, 0);
	if (sock_a < 0 || sock_b < 0 || bind(sock_a, (void *)&a, sizeof(a)) ||
	    bind(sock_b, (void *)&b, sizeof(b)) || getsockname(sock_a, (void *)&a, &len) ||
	    getsockname(sock_b, (void *)&b, &len) || connect(sock_a, (void *)&b, sizeof(b)) ||
	    connect(sock_b, (void *)&a, sizeof(a)))
		lat_die("udp socket setup: %s", strerror(errno));
}

static void usage(void)
{
	fprintf(stderr,
		"usage: ipc_latency -t udp|eventfd [-a cpuA] [-b cpuB] [-p prio] [-n samples]\n"
		"                   [-w warmup] [-W warmup_ms] [-m monitor_cpu] [-o outdir] [-T]\n"
		"  defaults: -a 2 -b 3 -p 90 -n 100000 -w 1000 -W 200 -m 0 -o .\n"
		"  -T  record even if the kernel is tainted by an out-of-tree module\n");
	exit(2);
}

int main(int argc, char **argv)
{
	int cpu_a = 2, hk = 0, allow_tainted = 0, opt;
	long n = 100000, warmup = 1000, warmup_ms = 200, warm = 0, i;
	const char *outdir = ".", *mode = NULL;
	struct lat_env before, after;
	int64_t t0, t1, warm_end;
	pthread_t tb;
	char params[384], name[64];

	cpu_b = 3;
	prio = 90;
	while ((opt = getopt(argc, argv, "t:a:b:p:n:w:W:m:o:T")) != -1) {
		switch (opt) {
		case 't': mode = optarg; break;
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
	if (!mode || (strcmp(mode, "udp") && strcmp(mode, "eventfd")))
		usage();
	if (cpu_a == hk || cpu_b == hk || n <= 0 || warmup < 0 || warmup_ms < 0)
		usage();
	use_udp = !strcmp(mode, "udp");

	lat_check_taint(allow_tainted);
	if (use_udp) {
		udp_pair();
	} else {
		efd_ab = eventfd(0, EFD_CLOEXEC);
		efd_ba = eventfd(0, EFD_CLOEXEC);
		if (efd_ab < 0 || efd_ba < 0)
			lat_die("eventfd: %s", strerror(errno));
	}
	buf = lat_alloc((size_t)n * sizeof(*buf));
	lat_sensors_open(cpu_a, hk);
	/* Monitor sizing only: assume <= 1 ms per round. */
	lat_monitor_start(hk, warmup_ms * 1000000LL + n * 1000000LL);
	lat_rt_setup(cpu_a, prio);
	if (pthread_create(&tb, NULL, thread_b, NULL))
		lat_die("pthread_create failed");
	lat_env_read(&before);

	/* ---- warmup + measurement loop: no allocation, I/O or arithmetic beyond the subtraction ---- */
	warm_end = lat_now_ns() + warmup_ms * 1000000LL;
	if (use_udp) {
		do {
			udp_send(sock_a, warm);
			udp_recv(sock_a);
			warm++;
		} while (warm < warmup || lat_now_ns() < warm_end);
		for (i = 0; i < n; i++) {
			t0 = lat_now_ns();
			udp_send(sock_a, i);
			udp_recv(sock_a);
			t1 = lat_now_ns();
			buf[i].t_ns = t0;
			buf[i].v_ns = t1 - t0;
		}
	} else {
		do {
			efd_round(-2);
			warm++;
		} while (warm < warmup || lat_now_ns() < warm_end);
		for (i = 0; i < n; i++)
			efd_round(i);
	}
	/* ---- end of measurement loop ---- */

	lat_env_read(&after);
	if (use_udp) {
		udp_send(sock_a, STOP);
	} else {
		atomic_store_explicit(&shared_idx, STOP, memory_order_release);
		efd_write(efd_ab);
	}
	pthread_join(tb, NULL);
	lat_monitor_stop();

	snprintf(params, sizeof(params),
		 "\"mechanism\": \"%s\", \"value\": \"%s\", \"cpu_a\": %d, \"cpu_b\": %d, "
		 "\"prio\": %d, \"policy\": \"SCHED_FIFO\", \"warmup_min_iters\": %ld, "
		 "\"warmup_ms\": %ld, \"monitor_cpu\": %d, \"monitor_period_ms\": 100",
		 use_udp ? "udp_loopback" : "eventfd", use_udp ? "round_trip" : "one_way_wakeup",
		 cpu_a, cpu_b, prio, warmup, warmup_ms, hk);
	snprintf(name, sizeof(name), "ipc_%s_%d_%d.bin", mode, cpu_a, cpu_b);
	lat_write_samples(lat_path(outdir, name), buf, n);
	snprintf(name, sizeof(name), "ipc_%s_%d_%d.monitor.csv", mode, cpu_a, cpu_b);
	lat_write_monitor(lat_path(outdir, name));
	snprintf(name, sizeof(name), "ipc_%s_%d_%d.json", mode, cpu_a, cpu_b);
	lat_write_sidecar(lat_path(outdir, name), "ipc_latency", params, n, warm, &before, &after);
	printf("ipc_latency: %ld %s samples, cpu %d -> %d (prio %d, %ld warmup) -> %s/\n", n, mode,
	       cpu_a, cpu_b, prio, warm, outdir);
	return 0;
}
