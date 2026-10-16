#ifndef ENCORE_BUILD_JOBSERVER_H
#define ENCORE_BUILD_JOBSERVER_H

/* Private, process-shared CPU leases. The file is created in the build's
 * private temporary directory, not a global named semaphore. File locks are
 * automatically released on process death; local locks also serialize threads
 * using the same handle (POSIX file locks alone do not provide that property).
 * No lock is held across a tool invocation or while waiting for a CPU lease. */
#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>

#ifdef _WIN32
#include <windows.h>
#else
#include <fcntl.h>
#include <signal.h>
#include <pthread.h>
#include <sys/file.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
#endif

#define ENCORE_JOBSERVER_MAGIC UINT64_C(0x454e434a4f425332)
#define ENCORE_JOBSERVER_MAX_JOBS 65536

typedef struct encore_jobserver_slot {
    uint64_t pid;
    uint64_t leases;
} encore_jobserver_slot;

typedef struct encore_jobserver_shared {
    uint64_t magic;
    uint64_t coordinator_pid;
    uint64_t jobs;
    uint64_t slot_count;
    uint64_t used;
    uint64_t cancelled;
    encore_jobserver_slot slots[];
} encore_jobserver_shared;

typedef struct encore_build_jobserver {
    encore_jobserver_shared *shared;
    size_t map_size;
    size_t slot;
    bool coordinator;
#ifdef _WIN32
    HANDLE file;
    HANDLE mapping;
    SRWLOCK local_lock;
#else
    int file;
    pthread_mutex_t local_lock;
#endif
} encore_build_jobserver;

static inline uint64_t encore_jobserver_pid(void) {
#ifdef _WIN32
    return GetCurrentProcessId();
#else
    return (uint64_t)getpid();
#endif
}

static inline bool encore_jobserver_alive(uint64_t pid) {
    if (pid == 0) return false;
#ifdef _WIN32
    HANDLE process = OpenProcess(SYNCHRONIZE, FALSE, (DWORD)pid);
    if (process == NULL) return GetLastError() != ERROR_INVALID_PARAMETER;
    DWORD status = WaitForSingleObject(process, 0);
    CloseHandle(process);
    return status != WAIT_OBJECT_0;
#else
    return kill((pid_t)pid, 0) == 0 || errno != ESRCH;
#endif
}

static inline bool encore_jobserver_lock(encore_build_jobserver *server) {
#ifdef _WIN32
    AcquireSRWLockExclusive(&server->local_lock);
    OVERLAPPED offset = {0};
    if (LockFileEx(server->file, LOCKFILE_EXCLUSIVE_LOCK, 0, 1, 0, &offset)) return true;
    ReleaseSRWLockExclusive(&server->local_lock);
#else
    if (pthread_mutex_lock(&server->local_lock) != 0) return false;
    int status;
    do { status = flock(server->file, LOCK_EX); } while (status < 0 && errno == EINTR);
    if (status == 0) return true;
    pthread_mutex_unlock(&server->local_lock);
#endif
    return false;
}

static inline void encore_jobserver_unlock(encore_build_jobserver *server) {
#ifdef _WIN32
    OVERLAPPED offset = {0};
    UnlockFileEx(server->file, 0, 1, 0, &offset);
    ReleaseSRWLockExclusive(&server->local_lock);
#else
    flock(server->file, LOCK_UN);
    pthread_mutex_unlock(&server->local_lock);
#endif
}

static inline void encore_jobserver_reclaim_dead(encore_jobserver_shared *shared) {
    /* A coordinator that died also invalidates admission, even if its numeric
     * token count happened to be zero. Reaping a crashed worker releases all
     * its tokens automatically. */
    if (!encore_jobserver_alive(shared->coordinator_pid)) shared->cancelled = 1;
    uint64_t used = 0;
    for (size_t index = 0; index < shared->slot_count; ++index) {
        encore_jobserver_slot *slot = &shared->slots[index];
        if (slot->pid == 0 || !encore_jobserver_alive(slot->pid)) {
            memset(slot, 0, sizeof(*slot));
        } else {
            used += slot->leases;
        }
    }
    /* Derive totals from live owners. A crash between two stores in a lease
     * transaction cannot permanently strand a token. */
    shared->used = used;
}

static inline void encore_jobserver_dispose(encore_build_jobserver *server) {
    if (server == NULL) return;
#ifdef _WIN32
    if (server->shared != NULL) UnmapViewOfFile(server->shared);
    if (server->mapping != NULL) CloseHandle(server->mapping);
    if (server->file != INVALID_HANDLE_VALUE) CloseHandle(server->file);
#else
    if (server->shared != NULL) munmap(server->shared, server->map_size);
    if (server->file >= 0) close(server->file);
    pthread_mutex_destroy(&server->local_lock);
#endif
    free(server);
}

#ifdef _WIN32
static inline wchar_t *encore_jobserver_wide_path(const char *path) {
    int length = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, path, -1, NULL, 0);
    if (length == 0) return NULL;
    wchar_t *wide = calloc((size_t)length, sizeof(wchar_t));
    if (wide != NULL && !MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, path, -1, wide, length)) {
        free(wide);
        return NULL;
    }
    return wide;
}
#endif

static inline encore_build_jobserver *encore_jobserver_open(const char *path, size_t jobs) {
    if (path == NULL || *path == '\0' || jobs > ENCORE_JOBSERVER_MAX_JOBS) return NULL;
    encore_build_jobserver *server = calloc(1, sizeof(*server));
    if (server == NULL) return NULL;
    server->slot = SIZE_MAX;
    server->coordinator = jobs != 0;
#ifdef _WIN32
    InitializeSRWLock(&server->local_lock);
    server->file = INVALID_HANDLE_VALUE;
    wchar_t *wide = encore_jobserver_wide_path(path);
    if (wide == NULL) { encore_jobserver_dispose(server); return NULL; }
    server->file = CreateFileW(wide, GENERIC_READ | GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, NULL,
        jobs != 0 ? CREATE_NEW : OPEN_EXISTING, FILE_FLAG_OPEN_REPARSE_POINT, NULL);
    free(wide);
    if (server->file == INVALID_HANDLE_VALUE) { encore_jobserver_dispose(server); return NULL; }
    BY_HANDLE_FILE_INFORMATION information;
    if (!GetFileInformationByHandle(server->file, &information) ||
        (information.dwFileAttributes & (FILE_ATTRIBUTE_REPARSE_POINT | FILE_ATTRIBUTE_DIRECTORY))) {
        encore_jobserver_dispose(server); return NULL;
    }
#else
    server->file = -1;
    if (pthread_mutex_init(&server->local_lock, NULL) != 0) { free(server); return NULL; }
    int flags = O_RDWR | O_CLOEXEC | O_NOFOLLOW;
    if (jobs != 0) flags |= O_CREAT | O_EXCL;
    server->file = open(path, flags, 0600);
    if (server->file < 0) { encore_jobserver_dispose(server); return NULL; }
#endif
    if (!encore_jobserver_lock(server)) { encore_jobserver_dispose(server); return NULL; }
    bool valid = true;
    if (jobs != 0) {
        server->map_size = sizeof(encore_jobserver_shared) + (2 * jobs + 1) * sizeof(encore_jobserver_slot);
#ifdef _WIN32
        LARGE_INTEGER size;
        size.QuadPart = (LONGLONG)server->map_size;
        valid = SetFilePointerEx(server->file, size, NULL, FILE_BEGIN) && SetEndOfFile(server->file);
#else
        valid = ftruncate(server->file, (off_t)server->map_size) == 0;
#endif
    } else {
#ifdef _WIN32
        LARGE_INTEGER size;
        valid = GetFileSizeEx(server->file, &size) && size.QuadPart >= (LONGLONG)sizeof(encore_jobserver_shared)
            && size.QuadPart <= (LONGLONG)(sizeof(encore_jobserver_shared) +
                (2 * ENCORE_JOBSERVER_MAX_JOBS + 1) * sizeof(encore_jobserver_slot));
        if (valid) server->map_size = (size_t)size.QuadPart;
#else
        struct stat information;
        valid = fstat(server->file, &information) == 0 && S_ISREG(information.st_mode)
            && information.st_uid == getuid() && (information.st_mode & 0077) == 0
            && information.st_size >= (off_t)sizeof(encore_jobserver_shared)
            && information.st_size <= (off_t)(sizeof(encore_jobserver_shared) +
                (2 * ENCORE_JOBSERVER_MAX_JOBS + 1) * sizeof(encore_jobserver_slot));
        if (valid) server->map_size = (size_t)information.st_size;
#endif
    }
    if (valid) {
#ifdef _WIN32
        server->mapping = CreateFileMappingW(server->file, NULL, PAGE_READWRITE, 0, 0, NULL);
        if (server->mapping != NULL) server->shared = MapViewOfFile(server->mapping, FILE_MAP_ALL_ACCESS, 0, 0, server->map_size);
#else
        void *memory = mmap(NULL, server->map_size, PROT_READ | PROT_WRITE, MAP_SHARED, server->file, 0);
        if (memory != MAP_FAILED) server->shared = memory;
#endif
        valid = server->shared != NULL;
    }
    if (valid && jobs != 0) {
        memset(server->shared, 0, server->map_size);
        server->shared->magic = ENCORE_JOBSERVER_MAGIC;
        server->shared->coordinator_pid = encore_jobserver_pid();
        server->shared->jobs = jobs;
        server->shared->slot_count = 2 * jobs + 1;
        server->shared->slots[0].pid = encore_jobserver_pid();
        server->slot = 0;
    } else if (valid) {
        const encore_jobserver_shared *shared = server->shared;
        valid = shared->magic == ENCORE_JOBSERVER_MAGIC && shared->jobs > 0
            && shared->jobs <= ENCORE_JOBSERVER_MAX_JOBS && shared->slot_count == 2 * shared->jobs + 1
            && server->map_size == sizeof(*shared) + shared->slot_count * sizeof(encore_jobserver_slot)
            && shared->used <= shared->jobs;
    }
    encore_jobserver_unlock(server);
    if (!valid) { encore_jobserver_dispose(server); return NULL; }
    return server;
}

static inline size_t encore_build_jobserver_create_path(const char *path, size_t jobs) {
    if (jobs == 0) return 0;
    encore_build_jobserver *server = encore_jobserver_open(path, jobs);
    if (server == NULL) return 0;
    return (size_t)server;
}

static inline size_t encore_build_jobserver_attach_path(const char *path) {
    encore_build_jobserver *server = encore_jobserver_open(path, 0);
    if (server == NULL) return 0;
    if (!encore_jobserver_lock(server)) { encore_jobserver_dispose(server); return 0; }
    encore_jobserver_shared *shared = server->shared;
    encore_jobserver_reclaim_dead(shared);
    bool already_attached = false;
    for (size_t index = 0; index < shared->slot_count; ++index) {
        if (shared->slots[index].pid == encore_jobserver_pid()) already_attached = true;
    }
    if (!already_attached && !shared->cancelled) {
        for (size_t index = 1; index < shared->slot_count; ++index) {
            if (shared->slots[index].pid == 0) {
                shared->slots[index].pid = encore_jobserver_pid();
                server->slot = index;
                break;
            }
        }
    }
    encore_jobserver_unlock(server);
    if (server->slot == SIZE_MAX) { encore_jobserver_dispose(server); return 0; }
    return (size_t)server;
}

/* 1 = lease acquired, 0 = temporarily full, -1 = cancelled/invalid. */
static inline int encore_build_jobserver_try_acquire(size_t raw_server) {
    encore_build_jobserver *server = (encore_build_jobserver *)raw_server;
    if (server == NULL || !encore_jobserver_lock(server)) return -1;
    encore_jobserver_shared *shared = server->shared;
    encore_jobserver_reclaim_dead(shared);
    int result = -1;
    if (!shared->cancelled && shared->slots[server->slot].pid == encore_jobserver_pid()) {
        result = 0;
        if (shared->used < shared->jobs) {
            ++shared->used;
            ++shared->slots[server->slot].leases;
            result = 1;
        }
    }
    encore_jobserver_unlock(server);
    return result;
}

static inline bool encore_build_jobserver_release(size_t raw_server) {
    encore_build_jobserver *server = (encore_build_jobserver *)raw_server;
    if (server == NULL || !encore_jobserver_lock(server)) return false;
    encore_jobserver_slot *slot = &server->shared->slots[server->slot];
    bool released = slot->pid == encore_jobserver_pid() && slot->leases > 0;
    if (released) { --slot->leases; --server->shared->used; }
    encore_jobserver_unlock(server);
    return released;
}

static inline void encore_build_jobserver_cancel(size_t raw_server) {
    encore_build_jobserver *server = (encore_build_jobserver *)raw_server;
    if (server == NULL || !encore_jobserver_lock(server)) return;
    server->shared->cancelled = 1;
    encore_jobserver_unlock(server);
}

static inline size_t encore_build_jobserver_used(size_t raw_server) {
    encore_build_jobserver *server = (encore_build_jobserver *)raw_server;
    if (server == NULL || !encore_jobserver_lock(server)) return SIZE_MAX;
    encore_jobserver_reclaim_dead(server->shared);
    const size_t used = (size_t)server->shared->used;
    encore_jobserver_unlock(server);
    return used;
}

static inline void encore_build_jobserver_close(size_t raw_server) {
    encore_build_jobserver *server = (encore_build_jobserver *)raw_server;
    if (server == NULL) return;
    if (encore_jobserver_lock(server)) {
        encore_jobserver_slot *slot = &server->shared->slots[server->slot];
        if (slot->pid == encore_jobserver_pid()) {
            server->shared->used -= slot->leases;
            memset(slot, 0, sizeof(*slot));
        }
        if (server->coordinator) server->shared->cancelled = 1;
        encore_jobserver_unlock(server);
    }
    /* The supervisor removes the containing temporary directory only after
     * joining every child. Windows cannot unlink a still-open mapping safely. */
    encore_jobserver_dispose(server);
}

#endif
