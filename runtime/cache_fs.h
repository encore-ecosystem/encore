#ifndef ENCORE_CACHE_FS_H
#define ENCORE_CACHE_FS_H

/* Filesystem facts only. Retention and eviction policy live in Encore. */
static uint64_t encore_cache_file_fact(const char *path, unsigned field) {
    if (path == NULL) return 0;
#ifdef _WIN32
    wchar_t *wide = encore_build_artifact_wide(path);
    if (wide == NULL) return 0;
    HANDLE file = CreateFileW(wide, FILE_READ_ATTRIBUTES,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, NULL, OPEN_EXISTING,
        FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT, NULL);
    free(wide);
    if (file == INVALID_HANDLE_VALUE) return 0;
    BY_HANDLE_FILE_INFORMATION info;
    bool valid = GetFileInformationByHandle(file, &info) != 0;
    CloseHandle(file);
    if (!valid) return 0;
    if (field == 0) return (info.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) ? 3 :
        ((info.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) ? 2 : 1);
    if (field == 1) return ((uint64_t)info.nFileSizeHigh << 32) | info.nFileSizeLow;
    uint64_t ticks = ((uint64_t)info.ftLastWriteTime.dwHighDateTime << 32) | info.ftLastWriteTime.dwLowDateTime;
    return ticks < UINT64_C(116444736000000000) ? 0 : (ticks - UINT64_C(116444736000000000)) / 10000;
#else
    struct stat info;
    if (lstat(path, &info) != 0) return 0;
    if (field == 0) return S_ISREG(info.st_mode) ? 1 : (S_ISDIR(info.st_mode) ? 2 : 3);
    if (field == 1) return info.st_size < 0 ? 0 : (uint64_t)info.st_size;
    return info.st_mtime < 0 ? 0 : (uint64_t)info.st_mtime * 1000;
#endif
}

static int encore_cache_lock_shared(size_t raw) {
    encore_build_cache_lock *lock = (encore_build_cache_lock *)raw;
    if (lock == NULL) return -1;
#ifdef _WIN32
    OVERLAPPED offset = {0};
    if (LockFileEx(lock->file, LOCKFILE_FAIL_IMMEDIATELY, 0, 1, 0, &offset)) return 1;
    return GetLastError() == ERROR_LOCK_VIOLATION ? 0 : -1;
#else
    int result;
    do { result = flock(lock->file, LOCK_SH | LOCK_NB); } while (result < 0 && errno == EINTR);
    return result == 0 ? 1 : (errno == EWOULDBLOCK || errno == EAGAIN ? 0 : -1);
#endif
}
#endif
