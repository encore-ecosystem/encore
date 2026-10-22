#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>

static int admitted_worker;

__attribute__((constructor)) static void detect_worker(void) {
    FILE *file = fopen("/proc/self/cmdline", "rb");
    if (file == NULL) return;
    char arguments[4096];
    size_t size = fread(arguments, 1, sizeof(arguments), file);
    fclose(file);
    for (size_t offset = 0; offset < size;) {
        const char *end = memchr(arguments + offset, '\0', size - offset);
        if (end == NULL) break;
        if (strcmp(arguments + offset, "__compile-unit") == 0) admitted_worker = 1;
        offset = (size_t)(end - arguments) + 1;
    }
}

/* A test-only permission boundary makes withdrawal of already published
 * private readiness deterministic, independent of consumer scheduling. Shared
 * locked CAS transactions and unpublished temporary files remain writable. */
int remove(const char *path) {
    const char *leaf = strrchr(path, '/');
    if (admitted_worker && leaf != NULL && strcmp(leaf, "/unit.ready") == 0 &&
        strstr(path, "/packages-") != NULL && strstr(path, "/unit-") != NULL) {
        fputs("published package readiness is immutable\n", stderr);
        errno = EACCES;
        return -1;
    }
    void *symbol = dlsym(RTLD_NEXT, "remove");
    int (*original)(const char *);
    _Static_assert(sizeof(original) == sizeof(symbol), "POSIX function pointer size");
    memcpy(&original, &symbol, sizeof(original));
    if (original == NULL) {
        errno = ENOSYS;
        return -1;
    }
    return original(path);
}
