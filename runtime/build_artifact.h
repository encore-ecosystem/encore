#ifndef ENCORE_BUILD_ARTIFACT_H
#define ENCORE_BUILD_ARTIFACT_H

/* Artifact transactions use same-directory atomic replacement. The caller
 * publishes a verified manifest last, while holding its per-unit cache lock.
 * OS locks disappear on crash; no stale PID file can strand a cache key. */
#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <stdatomic.h>

#ifdef _WIN32
#include <windows.h>
#else
#include <fcntl.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <unistd.h>
#endif

typedef struct encore_build_cache_lock {
#ifdef _WIN32
    HANDLE file;
#else
    int file;
#endif
} encore_build_cache_lock;

#ifdef _WIN32
static inline wchar_t *encore_build_artifact_wide(const char *text) {
    if (text == NULL) return NULL;
    int count = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text, -1, NULL, 0);
    if (count == 0) return NULL;
    wchar_t *wide = calloc((size_t)count, sizeof(*wide));
    if (wide != NULL && !MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text, -1, wide, count)) {
        free(wide); return NULL;
    }
    return wide;
}
#endif

static inline size_t encore_build_cache_lock_open(const char *path) {
    if (path == NULL || *path == '\0') return 0;
    encore_build_cache_lock *lock = malloc(sizeof(*lock));
    if (lock == NULL) return 0;
#ifdef _WIN32
    wchar_t *wide = encore_build_artifact_wide(path);
    if (wide == NULL) { free(lock); return 0; }
    lock->file = CreateFileW(wide, GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE,
        NULL, OPEN_ALWAYS, FILE_FLAG_OPEN_REPARSE_POINT, NULL);
    free(wide);
    if (lock->file == INVALID_HANDLE_VALUE) { free(lock); return 0; }
    BY_HANDLE_FILE_INFORMATION information;
    if (!GetFileInformationByHandle(lock->file, &information) ||
        (information.dwFileAttributes & (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT))) {
        CloseHandle(lock->file); free(lock); return 0;
    }
#else
    lock->file = open(path, O_RDWR | O_CREAT | O_CLOEXEC | O_NOFOLLOW, 0600);
    struct stat information;
    if (lock->file < 0) { free(lock); return 0; }
    if (fstat(lock->file, &information) != 0 || !S_ISREG(information.st_mode) ||
        information.st_uid != getuid() || (information.st_mode & 0077) != 0) {
        close(lock->file); free(lock); return 0;
    }
#endif
    return (size_t)lock;
}

/* Nonblocking so the coordinator can release its CPU lease while waiting. */
static inline int encore_build_cache_lock_try(size_t raw_lock) {
    encore_build_cache_lock *lock = (encore_build_cache_lock *)raw_lock;
    if (lock == NULL) return -1;
#ifdef _WIN32
    OVERLAPPED offset = {0};
    if (LockFileEx(lock->file, LOCKFILE_EXCLUSIVE_LOCK | LOCKFILE_FAIL_IMMEDIATELY, 0, 1, 0, &offset)) return 1;
    return GetLastError() == ERROR_LOCK_VIOLATION ? 0 : -1;
#else
    int status;
    do { status = flock(lock->file, LOCK_EX | LOCK_NB); } while (status < 0 && errno == EINTR);
    return status == 0 ? 1 : (errno == EWOULDBLOCK || errno == EAGAIN ? 0 : -1);
#endif
}

static inline void encore_build_cache_lock_close(size_t raw_lock) {
    encore_build_cache_lock *lock = (encore_build_cache_lock *)raw_lock;
    if (lock == NULL) return;
#ifdef _WIN32
    CloseHandle(lock->file);
#else
    close(lock->file);
#endif
    free(lock);
}

static inline bool encore_build_artifact_write(const char *path, const void *data, size_t length) {
    if (path == NULL || *path == '\0' || (length != 0 && data == NULL) || strlen(path) > SIZE_MAX - 80) return false;
    static _Atomic uint64_t sequence = 0;
    char *temporary = malloc(strlen(path) + 80);
    if (temporary == NULL) return false;
#ifdef _WIN32
    wchar_t *wide_temp = NULL;
    wchar_t *wide_path = encore_build_artifact_wide(path);
    HANDLE file = INVALID_HANDLE_VALUE;
    for (size_t attempt = 0; attempt < 32; ++attempt) {
        uint64_t serial = atomic_fetch_add_explicit(&sequence, 1, memory_order_relaxed);
        snprintf(temporary, strlen(path) + 80, "%s.tmp-%lu-%llu", path, (unsigned long)GetCurrentProcessId(), (unsigned long long)serial);
        free(wide_temp);
        wide_temp = encore_build_artifact_wide(temporary);
        if (wide_temp == NULL) break;
        file = CreateFileW(wide_temp, GENERIC_WRITE, 0, NULL, CREATE_NEW, FILE_ATTRIBUTE_NORMAL, NULL);
        if (file != INVALID_HANDLE_VALUE || (GetLastError() != ERROR_FILE_EXISTS && GetLastError() != ERROR_ALREADY_EXISTS)) break;
    }
    bool created = file != INVALID_HANDLE_VALUE;
    bool valid = created && wide_path != NULL;
    size_t offset = 0;
    while (valid && offset < length) {
        DWORD written;
        DWORD chunk = length - offset > 1048576 ? 1048576 : (DWORD)(length - offset);
        valid = WriteFile(file, (const char *)data + offset, chunk, &written, NULL) && written != 0;
        if (valid) offset += written;
    }
    if (valid) valid = FlushFileBuffers(file);
    if (created && !CloseHandle(file)) valid = false;
    if (valid) valid = MoveFileExW(wide_temp, wide_path, MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH);
    if (!valid && created) DeleteFileW(wide_temp);
    free(wide_temp); free(wide_path);
#else
    int file = -1;
    for (size_t attempt = 0; attempt < 32; ++attempt) {
        uint64_t serial = atomic_fetch_add_explicit(&sequence, 1, memory_order_relaxed);
        snprintf(temporary, strlen(path) + 80, "%s.tmp-%lu-%llu", path, (unsigned long)getpid(), (unsigned long long)serial);
        file = open(temporary, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW, 0600);
        if (file >= 0 || errno != EEXIST) break;
    }
    bool created = file >= 0;
    bool valid = created;
    size_t offset = 0;
    while (valid && offset < length) {
        size_t count = length - offset > 1048576 ? 1048576 : length - offset;
        ssize_t written = write(file, (const char *)data + offset, count);
        if (written < 0 && errno == EINTR) continue;
        valid = written > 0;
        if (valid) offset += (size_t)written;
    }
    if (valid) valid = fsync(file) == 0;
    if (created && close(file) != 0) valid = false;
    if (valid) valid = rename(temporary, path) == 0;
    if (!valid && created) unlink(temporary);
#endif
    free(temporary);
    return valid;
}

/* Read one committed snapshot. On Windows the CRT reader can lose a race
 * with replacement or a transient scanner lock even after GetFileAttributes
 * succeeded. Open the immutable receipt with delete sharing and retry only
 * OS sharing errors; malformed bytes are never retried or accepted. */
static inline char *encore_build_artifact_read(const char *path, size_t *length) {
    *length = 0;
    if (path == NULL) return NULL;
#ifdef _WIN32
    wchar_t *wide = encore_build_artifact_wide(path);
    if (wide == NULL) return NULL;
    HANDLE file = INVALID_HANDLE_VALUE;
    for (size_t attempt = 0; attempt < 100; ++attempt) {
        file = CreateFileW(wide, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
            NULL, OPEN_EXISTING, FILE_FLAG_SEQUENTIAL_SCAN, NULL);
        if (file != INVALID_HANDLE_VALUE) break;
        DWORD error = GetLastError();
        if (error != ERROR_SHARING_VIOLATION && error != ERROR_LOCK_VIOLATION) break;
        Sleep(10);
    }
    free(wide);
    if (file == INVALID_HANDLE_VALUE) return NULL;
    LARGE_INTEGER size;
    if (!GetFileSizeEx(file, &size) || size.QuadPart < 0 || (uint64_t)size.QuadPart >= SIZE_MAX) {
        CloseHandle(file); return NULL;
    }
    size_t count = (size_t)size.QuadPart;
    char *data = malloc(count + 1);
    if (data == NULL) { CloseHandle(file); return NULL; }
    size_t offset = 0;
    while (offset < count) {
        DWORD read_count = 0;
        DWORD chunk = count - offset > 1048576 ? 1048576 : (DWORD)(count - offset);
        if (!ReadFile(file, data + offset, chunk, &read_count, NULL) || read_count == 0) {
            free(data); CloseHandle(file); return NULL;
        }
        offset += read_count;
    }
    CloseHandle(file);
#else
    FILE *file = fopen(path, "rb");
    if (file == NULL) return NULL;
    struct stat information;
    if (fstat(fileno(file), &information) != 0 || !S_ISREG(information.st_mode) ||
        information.st_size < 0 || (uintmax_t)information.st_size >= SIZE_MAX) {
        fclose(file); return NULL;
    }
    size_t count = (size_t)information.st_size;
    char *data = malloc(count + 1);
    if (data == NULL) { fclose(file); return NULL; }
    if (fread(data, 1, count, file) != count || ferror(file)) {
        free(data); fclose(file); return NULL;
    }
    fclose(file);
#endif
    data[count] = '\0';
    *length = count;
    return data;
}

#endif
