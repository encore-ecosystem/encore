/* Read the host's own high-water RSS after the full SDK benchmark. */
#include <stdint.h>
#if defined(__linux__) || defined(__APPLE__)
#include <sys/resource.h>
#endif
uint64_t encore_plugin_benchmark_peak_rss(void) {
#if defined(__linux__) || defined(__APPLE__)
    struct rusage usage;
    if (getrusage(RUSAGE_SELF, &usage) != 0) return 0;
#ifdef __APPLE__
    return (uint64_t)usage.ru_maxrss;
#else
    return (uint64_t)usage.ru_maxrss * 1024;
#endif
#else
    return 0;
#endif
}
