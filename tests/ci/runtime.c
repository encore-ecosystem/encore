/* Only the disposable test package includes these bridges. Production runtime
 * and probe implementations remain unchanged and are compiled by Encore. */
#include "../../../runtime.c"
#include "../../../tests/native/cache_payload.c"
#include <sys/stat.h>

size_t encore_ci_process_id(void) {
#ifdef _WIN32
    return (size_t)GetCurrentProcessId();
#else
    return (size_t)getpid();
#endif
}

bool encore_ci_set_env(encore_compiler_str name, encore_compiler_str value) {
    char *key = encore_compiler_cstr(name), *text = encore_compiler_cstr(value);
    if (key == NULL || text == NULL) { free(key); free(text); return false; }
#ifdef _WIN32
    wchar_t *wide_key = encore_build_artifact_wide(key), *wide_text = encore_build_artifact_wide(text);
    bool result = wide_key != NULL && wide_text != NULL && _wputenv_s(wide_key, wide_text) == 0 &&
        SetEnvironmentVariableW(wide_key, wide_text) != 0;
    free(wide_key); free(wide_text);
#else
    bool result = setenv(key, text, 1) == 0;
#endif
    free(key); free(text); return result;
}

bool encore_ci_unset_env(encore_compiler_str name) {
    char *key = encore_compiler_cstr(name);
    if (key == NULL) return false;
#ifdef _WIN32
    wchar_t *wide_key = encore_build_artifact_wide(key);
    bool result = wide_key != NULL && _wputenv_s(wide_key, L"") == 0 &&
        SetEnvironmentVariableW(wide_key, NULL) != 0;
    free(wide_key);
#else
    bool result = unsetenv(key) == 0;
#endif
    free(key); return result;
}

uint64_t encore_ci_modified_ns(encore_compiler_str path) {
    char *name = encore_compiler_cstr(path);
    if (name == NULL) return 0;
#ifdef _WIN32
    WIN32_FILE_ATTRIBUTE_DATA data;
    uint64_t value = 0;
    wchar_t *wide = encore_build_artifact_wide(name);
    if (wide != NULL && GetFileAttributesExW(wide, GetFileExInfoStandard, &data)) {
        value = (((uint64_t)data.ftLastWriteTime.dwHighDateTime << 32) | data.ftLastWriteTime.dwLowDateTime) * 100;
    }
    free(wide);
#else
    struct stat data;
    uint64_t value = 0;
    if (stat(name, &data) == 0) {
#ifdef __APPLE__
        value = (uint64_t)data.st_mtimespec.tv_sec * 1000000000 + (uint64_t)data.st_mtimespec.tv_nsec;
#else
        value = (uint64_t)data.st_mtim.tv_sec * 1000000000 + (uint64_t)data.st_mtim.tv_nsec;
#endif
    }
#endif
    free(name); return value;
}

#ifdef _WIN32
static DWORD WINAPI ci_release_snapshot_lock(void *raw) {
    Sleep(50);
    CloseHandle((HANDLE)raw);
    return 0;
}
#endif

int32_t encore_ci_artifact_snapshot(encore_compiler_str directory) {
    char *root = encore_compiler_cstr(directory);
    if (root == NULL) return 1;
    char path[4096];
    snprintf(path, sizeof(path), "%s/snapshot.ready", root);
    free(root);
    const char bytes[] = "{\"ready\":true}\0binary";
    if (!encore_build_artifact_write(path, bytes, sizeof(bytes))) return 2;
#ifdef _WIN32
    wchar_t *wide = encore_build_artifact_wide(path);
    HANDLE lock = CreateFileW(wide, GENERIC_READ, 0, NULL, OPEN_EXISTING, 0, NULL);
    free(wide);
    if (lock == INVALID_HANDLE_VALUE) return 3;
    HANDLE thread = CreateThread(NULL, 0, ci_release_snapshot_lock, lock, 0, NULL);
    if (thread == NULL) { CloseHandle(lock); return 4; }
#endif
    size_t length = 0;
    char *snapshot = encore_build_artifact_read(path, &length);
    bool valid = snapshot != NULL && length == sizeof(bytes) && memcmp(snapshot, bytes, sizeof(bytes)) == 0;
    free(snapshot);
#ifdef _WIN32
    WaitForSingleObject(thread, INFINITE);
    CloseHandle(thread);
#endif
    if (!valid) return 5;
    if (!encore_build_artifact_write(path, NULL, 0)) return 6;
    snapshot = encore_build_artifact_read(path, &length);
    valid = snapshot != NULL && length == 0;
    free(snapshot);
    return valid ? 0 : 7;
}

#ifdef __linux__
#include "../../../tests/native/build_contracts.c"
#include "../../../tests/native/registry_server.c"
#define main encore_ci_heap_main
#include "../../../packages/core/tests/heap_capacity.c"
#undef main

int32_t encore_ci_heap_capacity(int32_t mode) {
    char *arguments[] = {"heap-capacity", mode == 1 ? "overflow" : "header-overflow", NULL};
    if (mode == 0) return encore_ci_heap_main(1, arguments);
    int descriptors[2];
    if (pipe(descriptors) != 0) return 1;
    pid_t child = fork();
    if (child < 0) { close(descriptors[0]); close(descriptors[1]); return 2; }
    if (child == 0) {
        close(descriptors[0]);
        if (dup2(descriptors[1], STDERR_FILENO) < 0) _exit(3);
        close(descriptors[1]);
        _exit(encore_ci_heap_main(2, arguments));
    }
    close(descriptors[1]);
    char message[1024] = {0};
    size_t used = 0;
    ssize_t count;
    while ((count = read(descriptors[0], message + used, sizeof(message) - 1 - used)) > 0) {
        used += (size_t)count;
        if (used == sizeof(message) - 1) break;
    }
    close(descriptors[0]);
    int status = 0;
    if (waitpid(child, &status, 0) != child) return 4;
    return !(WIFEXITED(status) && WEXITSTATUS(status) != 0 &&
        strstr(message, "Vec capacity overflow") != NULL);
}

#define main encore_ci_environment_threads
#include "../../../packages/platform/tests/environment_threads.c"
#undef main
#define main encore_ci_build_queue
#include "../../../tests/native/build_runtime.c"
#undef main
#define main encore_ci_build_identity
#include "../../../tests/native/build_identity.c"
#undef main
#endif
