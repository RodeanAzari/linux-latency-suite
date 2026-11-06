/* Shared setup, timing, monitoring and output for every latency test.
 *
 * Every test follows the same shape:
 *   lat_sensors_open -> lat_alloc -> lat_monitor_start -> lat_rt_setup
 *   -> lat_env_read(before) -> measurement loop -> lat_env_read(after)
 *   -> lat_monitor_stop -> lat_write_samples / lat_write_sidecar
 * Nothing in the measurement loop may allocate, print, or compute statistics.
 */
#ifndef LAT_COMMON_H
#define LAT_COMMON_H

#include <stdint.h>
#include <stddef.h>
#include <time.h>

/* One measured event: when it happened and how long it took. The timestamp
 * lets analysis line samples up with the thermal/SMI monitor log. */
typedef struct {
	int64_t t_ns; /* CLOCK_MONOTONIC */
	int64_t v_ns; /* measured latency */
} lat_sample_t;

/* Point-in-time platform state, taken before and after a run. -1 = unreadable. */
struct lat_env {
	int64_t mono_ns;
	int64_t smi_count;       /* MSR_SMI_COUNT (0x34), read on the housekeeping CPU */
	long core_throttle;      /* measured CPU's core_throttle_count */
	long pkg_throttle;       /* package_throttle_count */
	long pkg_temp_mc;        /* x86_pkg_temp, millidegrees C */
	long cur_khz;            /* measured CPU's scaling_cur_freq (reads min on nohz_full) */
	long tdp_level;          /* CONFIG_TDP_CONTROL (0x64B) bits 1:0, package scope, read
				  * on the housekeeping CPU; firmware can change it unasked */
	int64_t aperf, mperf;    /* measured CPU's APERF/MPERF; before/after only, -1 in
				  * monitor rows (reading them there would IPI that CPU) */
};

static inline int64_t lat_now_ns(void)
{
	struct timespec ts;
	clock_gettime(CLOCK_MONOTONIC, &ts);
	return (int64_t)ts.tv_sec * 1000000000LL + ts.tv_nsec;
}

static inline struct timespec lat_ns_to_ts(int64_t ns)
{
	struct timespec ts = { .tv_sec = ns / 1000000000LL, .tv_nsec = ns % 1000000000LL };
	return ts;
}

void lat_die(const char *fmt, ...) __attribute__((format(printf, 1, 2), noreturn));

/* Refuse to run on a kernel tainted by out-of-tree or unsigned modules. */
void lat_check_taint(int allow_tainted);

/* mlockall, pin to cpu (verified), SCHED_FIFO at prio. Dies on any failure. */
void lat_rt_setup(int cpu, int prio);

/* Zeroed, pre-faulted, page-aligned buffer. */
void *lat_alloc(size_t bytes);

/* Open the sysfs/MSR files for the measured CPU and the housekeeping CPU. */
void lat_sensors_open(int meas_cpu, int hk_cpu);
void lat_env_read(struct lat_env *e);

/* Background thread on hk_cpu, SCHED_OTHER, sampling lat_env every 100 ms. */
void lat_monitor_start(int hk_cpu, int64_t expected_run_ns);
void lat_monitor_stop(void);
void lat_write_monitor(const char *path);

/* Create outdir if missing and return "<outdir>/<name>" in a static buffer slot. */
const char *lat_path(const char *outdir, const char *name);

void lat_write_samples(const char *path, const lat_sample_t *buf, long n);

/* params_json is a comma-separated list of extra "key": value pairs, no braces. */
void lat_write_sidecar(const char *path, const char *test, const char *params_json,
		       long samples, long warmup, const struct lat_env *before,
		       const struct lat_env *after);

#endif
