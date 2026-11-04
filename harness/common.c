#define _GNU_SOURCE
#include "common.h"

#include <errno.h>
#include <fcntl.h>
#include <glob.h>
#include <pthread.h>
#include <sched.h>
#include <stdarg.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/utsname.h>
#include <unistd.h>

#define MSR_SMI_COUNT 0x34
#define MONITOR_PERIOD_NS 100000000LL /* 100 ms */
#define TAINT_OOT_MODULE (1L << 12)
#define TAINT_UNSIGNED_MODULE (1L << 13)

void lat_die(const char *fmt, ...)
{
	va_list ap;
	va_start(ap, fmt);
	fputs("error: ", stderr);
	vfprintf(stderr, fmt, ap);
	fputc('\n', stderr);
	va_end(ap);
	exit(1);
}

/* ---- small file helpers (never called inside a measurement loop) ---- */

static void read_str(const char *path, char *buf, size_t len)
{
	FILE *f = fopen(path, "r");
	buf[0] = '\0';
	if (!f)
		return;
	if (!fgets(buf, (int)len, f))
		buf[0] = '\0';
	fclose(f);
	buf[strcspn(buf, "\n")] = '\0';
}

static long read_long_fd(int fd)
{
	char buf[32];
	ssize_t n;

	if (fd < 0)
		return -1;
	n = pread(fd, buf, sizeof(buf) - 1, 0); /* sysfs regenerates at offset 0 */
	if (n <= 0)
		return -1;
	buf[n] = '\0';
	return strtol(buf, NULL, 10);
}

static void json_str(FILE *f, const char *s)
{
	fputc('"', f);
	for (; *s; s++) {
		if (*s == '"' || *s == '\\')
			fputc('\\', f);
		if ((unsigned char)*s >= 0x20)
			fputc(*s, f);
	}
	fputc('"', f);
}

/* ---- process setup ---- */

void lat_check_taint(int allow_tainted)
{
	char buf[32];
	long t;

	read_str("/proc/sys/kernel/tainted", buf, sizeof(buf));
	t = strtol(buf, NULL, 10);
	if ((t & (TAINT_OOT_MODULE | TAINT_UNSIGNED_MODULE)) && !allow_tainted)
		lat_die("kernel tainted (%ld): an out-of-tree or unsigned module was loaded "
			"this boot. Reboot, or pass -T to record anyway.", t);
}

void lat_rt_setup(int cpu, int prio)
{
	cpu_set_t want, got;
	struct sched_param sp = { .sched_priority = prio };

	if (mlockall(MCL_CURRENT | MCL_FUTURE))
		lat_die("mlockall: %s", strerror(errno));

	CPU_ZERO(&want);
	CPU_SET(cpu, &want);
	if (sched_setaffinity(0, sizeof(want), &want))
		lat_die("sched_setaffinity(cpu %d): %s", cpu, strerror(errno));
	/* setaffinity can be silently narrowed by cgroups/cpusets: verify. */
	if (sched_getaffinity(0, sizeof(got), &got) || CPU_COUNT(&got) != 1 ||
	    !CPU_ISSET(cpu, &got))
		lat_die("affinity did not take: not pinned to cpu %d only", cpu);

	if (sched_setscheduler(0, SCHED_FIFO, &sp))
		lat_die("sched_setscheduler(SCHED_FIFO, %d): %s (run as root)", prio,
			strerror(errno));

	sched_yield(); /* let the migration happen before we check */
	if (sched_getcpu() != cpu)
		lat_die("running on cpu %d, expected %d", sched_getcpu(), cpu);
}

void *lat_alloc(size_t bytes)
{
	void *p = mmap(NULL, bytes, PROT_READ | PROT_WRITE,
		       MAP_PRIVATE | MAP_ANONYMOUS | MAP_POPULATE, -1, 0);
	if (p == MAP_FAILED)
		lat_die("mmap %zu bytes: %s", bytes, strerror(errno));
	memset(p, 0, bytes); /* touch every page so no fault happens later */
	return p;
}

/* ---- sensors ---- */

static int msr_fd = -1, temp_fd = -1, freq_fd = -1, core_thr_fd = -1, pkg_thr_fd = -1;
static long dma_lat_before = -1;

/* Current PM QoS CPU latency target in us (2000000000 = unconstrained), or -1.
 * cyclictest holds it at 0 by default, which keeps every core out of deep
 * C-states and changes wakeup latency ~100x on this machine, so every run
 * records it. Opening the device adds a no-op request, so never call this
 * from the monitor thread. */
static long read_dma_latency(void)
{
	int32_t v;
	int fd = open("/dev/cpu_dma_latency", O_RDONLY);
	long r = -1;

	if (fd >= 0) {
		if (read(fd, &v, sizeof(v)) == sizeof(v))
			r = v;
		close(fd);
	}
	return r;
}

static int open_ro(const char *path, int warn)
{
	int fd = open(path, O_RDONLY | O_CLOEXEC);
	if (fd < 0 && warn)
		fprintf(stderr, "warning: cannot open %s: %s (recorded as -1)\n", path,
			strerror(errno));
	return fd;
}

void lat_sensors_open(int meas_cpu, int hk_cpu)
{
	char path[256], type[64];
	glob_t g;
	size_t i;

	dma_lat_before = read_dma_latency();

	/* SMIs are broadcast to every CPU, so the housekeeping CPU's counter
	 * sees them too, and reading it there costs the measured CPU no IPI. */
	snprintf(path, sizeof(path), "/dev/cpu/%d/msr", hk_cpu);
	msr_fd = open_ro(path, 0);
	if (msr_fd < 0)
		fprintf(stderr, "warning: cannot open %s: %s (run `modprobe msr`; SMI "
			"count recorded as -1)\n", path, strerror(errno));

	if (glob("/sys/class/thermal/thermal_zone*/type", 0, NULL, &g) == 0) {
		for (i = 0; i < g.gl_pathc && temp_fd < 0; i++) {
			read_str(g.gl_pathv[i], type, sizeof(type));
			if (strcmp(type, "x86_pkg_temp") == 0) {
				snprintf(path, sizeof(path), "%.*s/temp",
					 (int)(strrchr(g.gl_pathv[i], '/') - g.gl_pathv[i]),
					 g.gl_pathv[i]);
				temp_fd = open_ro(path, 1);
			}
		}
		globfree(&g);
	}
	if (temp_fd < 0)
		fprintf(stderr, "warning: no x86_pkg_temp thermal zone (recorded as -1)\n");

	snprintf(path, sizeof(path), "/sys/devices/system/cpu/cpu%d/cpufreq/scaling_cur_freq",
		 meas_cpu);
	freq_fd = open_ro(path, 1);
	snprintf(path, sizeof(path),
		 "/sys/devices/system/cpu/cpu%d/thermal_throttle/core_throttle_count", meas_cpu);
	core_thr_fd = open_ro(path, 1);
	snprintf(path, sizeof(path),
		 "/sys/devices/system/cpu/cpu%d/thermal_throttle/package_throttle_count",
		 meas_cpu);
	pkg_thr_fd = open_ro(path, 1);
}

void lat_env_read(struct lat_env *e)
{
	uint64_t v;

	e->mono_ns = lat_now_ns();
	e->smi_count = -1;
	if (msr_fd >= 0 && pread(msr_fd, &v, sizeof(v), MSR_SMI_COUNT) == sizeof(v))
		e->smi_count = (int64_t)(v & 0xffffffffu);
	e->core_throttle = read_long_fd(core_thr_fd);
	e->pkg_throttle = read_long_fd(pkg_thr_fd);
	e->pkg_temp_mc = read_long_fd(temp_fd);
	e->cur_khz = read_long_fd(freq_fd);
}

/* ---- monitor thread ---- */

static struct lat_env *mon_rows;
static size_t mon_cap, mon_n;
static int mon_overflow;
static atomic_int mon_stop;
static pthread_t mon_thread;

static void *mon_main(void *arg)
{
	int64_t next = lat_now_ns();
	struct timespec ts;

	(void)arg;
	while (!atomic_load(&mon_stop)) {
		if (mon_n < mon_cap)
			lat_env_read(&mon_rows[mon_n++]);
		else
			mon_overflow = 1;
		next += MONITOR_PERIOD_NS;
		ts = lat_ns_to_ts(next);
		clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &ts, NULL);
	}
	return NULL;
}

void lat_monitor_start(int hk_cpu, int64_t expected_run_ns)
{
	pthread_attr_t attr;
	struct sched_param sp = { .sched_priority = 0 };
	cpu_set_t set;
	int rc;

	/* 2x the expected duration plus a minute of slack. */
	mon_cap = (size_t)((2 * expected_run_ns + 60000000000LL) / MONITOR_PERIOD_NS);
	mon_rows = lat_alloc(mon_cap * sizeof(*mon_rows));

	/* Set placement and policy explicitly so the thread never inherits the
	 * creator's RT priority or CPU, even briefly. */
	CPU_ZERO(&set);
	CPU_SET(hk_cpu, &set);
	pthread_attr_init(&attr);
	pthread_attr_setaffinity_np(&attr, sizeof(set), &set);
	pthread_attr_setinheritsched(&attr, PTHREAD_EXPLICIT_SCHED);
	pthread_attr_setschedpolicy(&attr, SCHED_OTHER);
	pthread_attr_setschedparam(&attr, &sp);
	rc = pthread_create(&mon_thread, &attr, mon_main, NULL);
	pthread_attr_destroy(&attr);
	if (rc)
		lat_die("monitor thread: %s", strerror(rc));
}

void lat_monitor_stop(void)
{
	atomic_store(&mon_stop, 1);
	pthread_join(mon_thread, NULL);
	if (mon_overflow)
		fprintf(stderr, "warning: monitor buffer full; later rows dropped\n");
}

void lat_write_monitor(const char *path)
{
	FILE *f = fopen(path, "w");
	size_t i;

	if (!f)
		lat_die("%s: %s", path, strerror(errno));
	fprintf(f, "t_ns,smi_count,pkg_temp_mc,cur_khz,core_throttle,pkg_throttle\n");
	for (i = 0; i < mon_n; i++)
		fprintf(f, "%lld,%lld,%ld,%ld,%ld,%ld\n", (long long)mon_rows[i].mono_ns,
			(long long)mon_rows[i].smi_count, mon_rows[i].pkg_temp_mc,
			mon_rows[i].cur_khz, mon_rows[i].core_throttle, mon_rows[i].pkg_throttle);
	if (fclose(f))
		lat_die("%s: %s", path, strerror(errno));
}

/* ---- output ---- */

const char *lat_path(const char *outdir, const char *name)
{
	static char slots[4][512];
	static int next;
	char *p = slots[next++ % 4], *s;

	/* mkdir -p: results land in results/<config>/<run>/ */
	snprintf(p, sizeof(slots[0]), "%s/", outdir);
	for (s = strchr(p + 1, '/'); s; s = strchr(s + 1, '/')) {
		*s = '\0';
		if (mkdir(p, 0755) && errno != EEXIST)
			lat_die("mkdir %s: %s", p, strerror(errno));
		*s = '/';
	}
	snprintf(p, sizeof(slots[0]), "%s/%s", outdir, name);
	return p;
}

void lat_write_samples(const char *path, const lat_sample_t *buf, long n)
{
	FILE *f = fopen(path, "wb");

	if (!f)
		lat_die("%s: %s", path, strerror(errno));
	if (fwrite(buf, sizeof(*buf), (size_t)n, f) != (size_t)n || fclose(f))
		lat_die("%s: write failed", path);
}

static void json_env(FILE *f, const char *key, const struct lat_env *e)
{
	fprintf(f, "  \"%s\": {\"mono_ns\": %lld, \"smi_count\": %lld, \"core_throttle\": %ld, "
		   "\"pkg_throttle\": %ld, \"pkg_temp_mc\": %ld, \"cur_khz\": %ld}",
		key, (long long)e->mono_ns, (long long)e->smi_count, e->core_throttle,
		e->pkg_throttle, e->pkg_temp_mc, e->cur_khz);
}

void lat_write_sidecar(const char *path, const char *test, const char *params_json,
		       long samples, long warmup, const struct lat_env *before,
		       const struct lat_env *after)
{
	struct utsname u;
	char buf[1024];
	time_t now = time(NULL);
	FILE *f = fopen(path, "w");

	if (!f)
		lat_die("%s: %s", path, strerror(errno));
	uname(&u);

	fprintf(f, "{\n  \"test\": ");
	json_str(f, test);
	fprintf(f, ",\n  \"format\": {\"record\": \"<i8 t_ns, <i8 v_ns\", \"clock\": "
		   "\"CLOCK_MONOTONIC\", \"unit\": \"ns\"},\n");
	fprintf(f, "  \"samples\": %ld,\n  \"warmup_discarded\": %ld,\n", samples, warmup);
	fprintf(f, "  \"params\": {%s},\n", params_json);

	strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%S%z", localtime(&now));
	fprintf(f, "  \"finished_at\": \"%s\",\n  \"hostname\": ", buf);
	json_str(f, u.nodename);
	fprintf(f, ",\n  \"kernel_release\": ");
	json_str(f, u.release);
	fprintf(f, ",\n  \"kernel_version\": ");
	json_str(f, u.version);

	read_str("/proc/cmdline", buf, sizeof(buf));
	fprintf(f, ",\n  \"cmdline\": ");
	json_str(f, buf);
	read_str("/proc/sys/kernel/tainted", buf, sizeof(buf));
	fprintf(f, ",\n  \"tainted\": %s", buf[0] ? buf : "-1");
	read_str("/sys/devices/system/clocksource/clocksource0/current_clocksource", buf,
		 sizeof(buf));
	fprintf(f, ",\n  \"clocksource\": ");
	json_str(f, buf);
	read_str("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor", buf, sizeof(buf));
	fprintf(f, ",\n  \"governor_cpu0\": ");
	json_str(f, buf);
	read_str("/sys/devices/system/cpu/intel_pstate/no_turbo", buf, sizeof(buf));
	fprintf(f, ",\n  \"no_turbo\": %s", buf[0] ? buf : "-1");
	/* ThinkPad DYTC: "balanced" selects cTDP-down (800 MHz guaranteed),
	 * "performance" nominal (1.6 GHz). Decides the clock when turbo is off. */
	read_str("/sys/firmware/acpi/platform_profile", buf, sizeof(buf));
	fprintf(f, ",\n  \"platform_profile\": ");
	json_str(f, buf);
	fprintf(f, ",\n");
	fprintf(f, "  \"cpu_dma_latency_us\": {\"before\": %ld, \"after\": %ld},\n",
		dma_lat_before, read_dma_latency());

	json_env(f, "env_before", before);
	fprintf(f, ",\n");
	json_env(f, "env_after", after);
	fprintf(f, ",\n  \"smi_delta\": %lld,\n  \"monitor_rows\": %zu,\n  \"monitor_overflow\": %s\n}\n",
		(before->smi_count >= 0 && after->smi_count >= 0)
			? (long long)(after->smi_count - before->smi_count) : -1LL,
		mon_n, mon_overflow ? "true" : "false");
	if (fclose(f))
		lat_die("%s: %s", path, strerror(errno));
}
