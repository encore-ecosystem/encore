/* Exercise the actual cache writer, reader, metadata and locks before bootstrap. */
#define _GNU_SOURCE
#define _DARWIN_C_SOURCE
#include "../../runtime/build_artifact.h"
#include "../../runtime/cache_fs.h"
#include <assert.h>

static void directory_append(char *path, size_t capacity, const char *suffix) {
    size_t length = strlen(path), bytes = strlen(suffix);
    assert(length < capacity && bytes < capacity - length);
    memcpy(path + length, suffix, bytes + 1);
}

static void directory_create(const char *path) {
#ifdef _WIN32
    wchar_t *wide = encore_build_artifact_path(path);
    assert(wide != NULL);
    bool valid = CreateDirectoryW(wide, NULL) || GetLastError() == ERROR_ALREADY_EXISTS;
    free(wide);
    assert(valid);
#else
    assert(mkdir(path, 0700) == 0 || errno == EEXIST);
#endif
}

static void directory_remove(const char *path) {
#ifdef _WIN32
    wchar_t *wide = encore_build_artifact_path(path);
    assert(wide != NULL && RemoveDirectoryW(wide));
    free(wide);
#else
    assert(rmdir(path) == 0);
#endif
}

static void file_remove(const char *path) {
#ifdef _WIN32
    wchar_t *wide = encore_build_artifact_path(path);
    assert(wide != NULL && DeleteFileW(wide));
    free(wide);
#else
    assert(unlink(path) == 0);
#endif
}

static void snapshot_contract(const char *directory) {
    char path[1024], lock_path[1024];
    assert(snprintf(path, sizeof(path), "%s/./source.snapshot", directory) < (int)sizeof(path));
    assert(snprintf(lock_path, sizeof(lock_path), "%s/cache.lock", directory) < (int)sizeof(lock_path));
    const char bytes[] = "source\0snapshot";
    assert(encore_build_artifact_write(path, bytes, sizeof(bytes)));
    size_t length = 0;
    char *snapshot = encore_build_artifact_read(path, &length);
    assert(snapshot != NULL && length == sizeof(bytes) && !memcmp(snapshot, bytes, length));
    free(snapshot);
    assert(encore_cache_file_fact(path, 0) == 1);
    assert(encore_cache_file_fact(path, 1) == sizeof(bytes));
    encore_cache_touch(path);
    assert(encore_cache_file_fact(path, 2) != 0);
    assert(encore_build_artifact_write(path, NULL, 0));
    snapshot = encore_build_artifact_read(path, &length);
    assert(snapshot != NULL && length == 0);
    free(snapshot);
    size_t lock = encore_build_cache_lock_open(lock_path);
    assert(lock != 0 && encore_cache_lock_shared(lock) == 1);
    encore_build_cache_lock_close(lock);
    lock = encore_build_cache_lock_open(lock_path);
    assert(lock != 0 && encore_build_cache_lock_try(lock) == 1);
    encore_build_cache_lock_close(lock);
    file_remove(path);
    file_remove(lock_path);
}

int main(void) {
#ifdef _WIN32
    unsigned long pid = (unsigned long)GetCurrentProcessId();
#else
    unsigned long pid = (unsigned long)getpid();
#endif
    directory_create("target");
    char directory[1024];
    int written = snprintf(directory, sizeof(directory), "target/artifact paths-%lu", pid);
    assert(written > 0 && written < (int)sizeof(directory));
    size_t root_length = strlen(directory);
    directory_create(directory);
    snapshot_contract(directory);
    directory_append(directory, sizeof(directory), "/snapshots-\xd0\xba\xd0\xb5\xd1\x88");
    directory_create(directory);
    while (strlen(directory) < 340) {
        directory_append(directory, sizeof(directory), "/cache-context-0123456789abcdef");
        directory_create(directory);
    }
    snapshot_contract(directory);
    while (strlen(directory) > root_length) {
        directory_remove(directory);
        char *slash = strrchr(directory, '/');
        assert(slash != NULL);
        *slash = '\0';
    }
    directory_remove(directory);
    puts("Native artifact paths, snapshots, metadata and locks passed");
    return 0;
}
