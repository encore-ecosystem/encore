#ifndef _WIN32
#define _POSIX_C_SOURCE 200809L
#endif
#include "../../runtime/build_artifact.h"

bool test_artifact_write(const char *path, const void *contents, size_t length) {
    return encore_build_artifact_write(path, contents, length);
}
size_t test_cache_lock_open(const char *path) { return encore_build_cache_lock_open(path); }
int test_cache_lock_try(size_t lock) { return encore_build_cache_lock_try(lock); }
void test_cache_lock_close(size_t lock) { encore_build_cache_lock_close(lock); }
