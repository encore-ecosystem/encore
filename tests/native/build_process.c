#ifndef _WIN32
#define _GNU_SOURCE
#define _POSIX_C_SOURCE 200809L
#endif
#include "../../runtime/build_process.h"

size_t test_worker_spawn(const char *program, const char *const *args, size_t count,
    const char *directory, const char *output, const char *error) {
    return encore_build_process_spawn(program, args, count, directory, output, error);
}
int test_worker_poll(size_t child) { return encore_build_process_poll(child); }
int test_worker_cancel(size_t child) { return encore_build_process_cancel(child); }
uint64_t test_worker_peak_rss(size_t child) { return encore_build_process_peak_rss(child); }
void test_worker_close(size_t child) { encore_build_process_close(child); }
int test_worker_interrupted(void) { return encore_build_process_interrupted(); }
bool test_worker_watch_parent(uint64_t parent) { return encore_build_worker_watch_parent(parent); }
