/* §2.4 Memory subsystem: dependent-load latency across working-set sizes.
 *
 * The buffer is cut into 64-byte lines linked into one random cycle
 * (Sattolo's algorithm, fixed seed). Each load's address comes from the
 * previous load, so loads cannot overlap, and the random order defeats the
 * hardware prefetcher. Sweeping -s across 4K..256M maps L1, L2, L3 and DRAM.
 *
 * Each sample times K dependent loads with one timestamp pair; per-load
 * latency, (v_ns - timer overhead) / K, is computed offline.
 *
 * Page size is explicit, never left to THP:
 *   default  4 KiB pages (MADV_NOHUGEPAGE before first touch)
 *   -H       2 MiB hugetlb pages (needs vm.nr_hugepages reserved)
 * At large sizes nearly every load also misses the dTLB with 4 KiB pages;
 * the 4K-vs-2M difference there is the TLB miss cost.
 *
 * Warmup runs at least -w samples, -W ms, and one full trip round the cycle,
 * so the working set is resident in whatever level it fits.
 */
#define _GNU_SOURCE
#include "common.h"

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

#define LINE 64
#define K 256 /* dependent loads per sample */
#define HUGE_2M (2UL << 20)

#define L4(p) p = *(void **)p; p = *(void **)p; p = *(void **)p; p = *(void **)p
#define L16(p) L4(p); L4(p); L4(p); L4(p)
#define L256(p) L16(p); L16(p); L16(p); L16(p); L16(p); L16(p); L16(p); L16(p); \
		L16(p); L16(p); L16(p); L16(p); L16(p); L16(p); L16(p); L16(p)

static void *volatile sink;

static size_t parse_size(const char *s)
{
	char *end;
	unsigned long v = strtoul(s, &end, 10);

	switch (*end) {
	case 'K': case 'k': return v << 10;
	case 'M': case 'm': return v << 20;
	case 'G': case 'g': return v << 30;
	case '\0': return v;
	default: return 0;
	}
}

static uint64_t xorshift64(uint64_t *s)
{
	*s ^= *s << 13;
	*s ^= *s >> 7;
	*s ^= *s << 17;
	return *s;
}

/* Page-size-controlled, pre-faulted buffer. Not lat_alloc: that populates
 * at mmap time, before MADV_NOHUGEPAGE could take effect. */
static char *alloc_ws(size_t bytes, int huge)
{
	char *p;

	if (huge) {
		p = mmap(NULL, bytes, PROT_READ | PROT_WRITE,
			 MAP_PRIVATE | MAP_ANONYMOUS | MAP_HUGETLB, -1, 0);
		if (p == MAP_FAILED)
			lat_die("mmap %zu bytes MAP_HUGETLB: %s (reserve pages: "
				"sysctl vm.nr_hugepages=%zu)", bytes, strerror(errno),
				bytes / HUGE_2M);
	} else {
		p = mmap(NULL, bytes, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS,
			 -1, 0);
		if (p == MAP_FAILED)
			lat_die("mmap %zu bytes: %s", bytes, strerror(errno));
		/* EINVAL: kernel built without THP (PREEMPT_RT), so 4 KiB is guaranteed */
		if (madvise(p, bytes, MADV_NOHUGEPAGE) && errno != EINVAL)
			lat_die("madvise(MADV_NOHUGEPAGE): %s", strerror(errno));
	}
	memset(p, 0, bytes);
	return p;
}

/* Link every line into a single random cycle; returns the start. */
static void *build_chain(char *ws, size_t lines)
{
	uint32_t *perm = lat_alloc(lines * sizeof(*perm));
	uint64_t seed = 0x9e3779b97f4a7c15ULL;
	size_t i, j;
	uint32_t t;

	for (i = 0; i < lines; i++)
		perm[i] = (uint32_t)i;
	for (i = lines - 1; i > 0; i--) { /* Sattolo: j < i gives one cycle */
		j = xorshift64(&seed) % i;
		t = perm[i];
		perm[i] = perm[j];
		perm[j] = t;
	}
	for (i = 0; i < lines; i++)
		*(void **)(ws + (size_t)perm[i] * LINE) = ws + (size_t)perm[(i + 1) % lines] * LINE;
	munmap(perm, lines * sizeof(*perm));
	return ws;
}

static void usage(void)
{
	fprintf(stderr,
		"usage: memlat -s size[K|M|G] [-H] [-c cpu] [-p prio] [-n samples]\n"
		"              [-w warmup] [-W warmup_ms] [-m monitor_cpu] [-o outdir] [-T]\n"
		"  defaults: -c 2 -p 90 -n 100000 -w 1000 -W 200 -m 0 -o .\n"
		"  -H  2 MiB hugetlb pages (size rounded up to 2 MiB); default 4 KiB pages\n"
		"  -T  record even if the kernel is tainted by an out-of-tree module\n");
	exit(2);
}

int main(int argc, char **argv)
{
	int cpu = 2, prio = 90, hk = 0, allow_tainted = 0, huge = 0, opt;
	long n = 100000, warmup = 1000, warmup_ms = 200, warm = 0, warm_min, i;
	size_t size = 0, lines;
	const char *outdir = ".";
	struct lat_env before, after;
	lat_sample_t *buf;
	int64_t t0, t1, warm_end;
	char params[384], name[64], *ws;
	void *p;

	while ((opt = getopt(argc, argv, "s:Hc:p:n:w:W:m:o:T")) != -1) {
		switch (opt) {
		case 's': size = parse_size(optarg); break;
		case 'H': huge = 1; break;
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
	if (size < 2 * LINE || cpu == hk || n <= 0 || warmup < 0 || warmup_ms < 0)
		usage();
	if (huge)
		size = (size + HUGE_2M - 1) & ~(HUGE_2M - 1);
	lines = size / LINE;
	if (lines > UINT32_MAX)
		lat_die("size too large");
	warm_min = (long)((lines + K - 1) / K); /* one full trip round the cycle */
	if (warm_min < warmup)
		warm_min = warmup;

	lat_check_taint(allow_tainted);
	buf = lat_alloc((size_t)n * sizeof(*buf));
	ws = alloc_ws(size, huge);
	p = build_chain(ws, lines);
	lat_sensors_open(cpu, hk);
	lat_monitor_start(hk, warmup_ms * 1000000LL);
	lat_rt_setup(cpu, prio);
	lat_env_read(&before);

	/* ---- warmup + measurement loop: no allocation, I/O or arithmetic beyond the subtraction ---- */
	warm_end = lat_now_ns() + warmup_ms * 1000000LL;
	do {
		t0 = lat_now_ns();
		L256(p);
		t1 = lat_now_ns();
		warm++;
	} while (warm < warm_min || t1 < warm_end);
	for (i = 0; i < n; i++) {
		t0 = lat_now_ns();
		L256(p);
		t1 = lat_now_ns();
		buf[i].t_ns = t0;
		buf[i].v_ns = t1 - t0;
	}
	/* ---- end of measurement loop ---- */
	sink = p;

	lat_env_read(&after);
	lat_monitor_stop();

	snprintf(params, sizeof(params),
		 "\"size_bytes\": %zu, \"page\": \"%s\", \"line_bytes\": %d, "
		 "\"loads_per_sample\": %d, \"order\": \"random cycle (Sattolo, fixed seed)\", "
		 "\"cpu\": %d, \"prio\": %d, \"policy\": \"SCHED_FIFO\", "
		 "\"warmup_min_iters\": %ld, \"warmup_ms\": %ld, "
		 "\"monitor_cpu\": %d, \"monitor_period_ms\": 100",
		 size, huge ? "2M" : "4K", LINE, K, cpu, prio, warm_min, warmup_ms, hk);
	snprintf(name, sizeof(name), "memlat_%zuK_%s.bin", size >> 10, huge ? "2M" : "4K");
	lat_write_samples(lat_path(outdir, name), buf, n);
	snprintf(name, sizeof(name), "memlat_%zuK_%s.monitor.csv", size >> 10, huge ? "2M" : "4K");
	lat_write_monitor(lat_path(outdir, name));
	snprintf(name, sizeof(name), "memlat_%zuK_%s.json", size >> 10, huge ? "2M" : "4K");
	lat_write_sidecar(lat_path(outdir, name), "memlat", params, n, warm, &before, &after);
	printf("memlat: %ld samples x %d loads, %zu KiB, %s pages (cpu %d, prio %d, %ld warmup) -> %s/\n",
	       n, K, size >> 10, huge ? "2M" : "4K", cpu, prio, warm, outdir);
	return 0;
}
