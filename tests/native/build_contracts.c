/* Test-only contracts for the production headers included by fixture runtime.c.
 * No shared-library build, ctypes or external test interpreter is involved. */
#include <assert.h>
#include <poll.h>
#include <pthread.h>
#include <stdatomic.h>
#include <dirent.h>

static int ci_read_response(int fd) {
    struct pollfd ready = {fd, POLLIN, 0};
    assert(poll(&ready, 1, 15000) == 1);
    int response = -99;
    assert(read(fd, &response, sizeof(response)) == sizeof(response));
    return response;
}

typedef struct { pid_t pid; int command, response; } ci_child;
static ci_child ci_job_child(const char *path, bool crash) {
    int commands[2], responses[2];
    assert(pipe(commands) == 0 && pipe(responses) == 0);
    pid_t pid = fork();
    assert(pid >= 0);
    if (pid == 0) {
        close(commands[1]); close(responses[0]);
        size_t handle = encore_build_jobserver_attach_path(path);
        int response = handle == 0 ? -99 : encore_build_jobserver_try_acquire(handle);
        assert(write(responses[1], &response, sizeof(response)) == sizeof(response));
        if (crash) _exit(17);
        char command = 0;
        assert(read(commands[0], &command, 1) == 1);
        if (command == 'a') {
            response = encore_build_jobserver_try_acquire(handle);
            assert(write(responses[1], &response, sizeof(response)) == sizeof(response));
        }
        encore_build_jobserver_close(handle);
        _exit(0);
    }
    close(commands[0]); close(responses[1]);
    return (ci_child){pid, commands[1], responses[0]};
}

static void ci_finish(ci_child child, char command, int status) {
    if (command != 0) assert(write(child.command, &command, 1) == 1);
    close(child.command); close(child.response);
    int result = 0;
    assert(waitpid(child.pid, &result, 0) == child.pid && WIFEXITED(result) && WEXITSTATUS(result) == status);
}

int32_t encore_ci_jobserver(encore_compiler_str directory) {
    char *root = encore_compiler_cstr(directory);
    assert(root != NULL);
    char path[4096];
    const size_t budgets[] = {1, 2, 4, 8};
    for (size_t index = 0; index < 4; ++index) {
        size_t jobs = budgets[index];
        snprintf(path, sizeof(path), "%s/jobs-%zu", root, jobs);
        size_t server = encore_build_jobserver_create_path(path, jobs);
        assert(server != 0 && !encore_build_jobserver_create_path(path, jobs));
        assert(!encore_build_jobserver_release(server));
        ci_child workers[8];
        for (size_t worker = 0; worker < jobs; ++worker) {
            workers[worker] = ci_job_child(path, false);
            assert(ci_read_response(workers[worker].response) == 1);
        }
        assert(encore_build_jobserver_used(server) == jobs);
        ci_child extra = ci_job_child(path, false);
        assert(ci_read_response(extra.response) == 0);
        ci_finish(workers[jobs - 1], 'd', 0);
        assert(encore_build_jobserver_used(server) == jobs - 1);
        assert(write(extra.command, "a", 1) == 1);
        assert(ci_read_response(extra.response) == 1);
        ci_finish(extra, 0, 0);
        for (size_t worker = 0; worker + 1 < jobs; ++worker) ci_finish(workers[worker], 'd', 0);
        assert(encore_build_jobserver_used(server) == 0);
        ci_child crashed = ci_job_child(path, true);
        assert(ci_read_response(crashed.response) == 1);
        ci_finish(crashed, 0, 17);
        assert(encore_build_jobserver_used(server) == 0);
        for (size_t worker = 0; worker < jobs; ++worker) assert(encore_build_jobserver_try_acquire(server) == 1);
        assert(encore_build_jobserver_try_acquire(server) == 0);
        for (size_t worker = 0; worker < jobs; ++worker) assert(encore_build_jobserver_release(server));
        assert(!encore_build_jobserver_release(server));
        encore_build_jobserver_cancel(server);
        assert(encore_build_jobserver_try_acquire(server) == -1);
        ci_child rejected = ci_job_child(path, false);
        assert(ci_read_response(rejected.response) == -99);
        ci_finish(rejected, 'd', 0);
        encore_build_jobserver_close(server);
    }
    snprintf(path, sizeof(path), "%s/coordinator-close", root);
    size_t server = encore_build_jobserver_create_path(path, 2);
    ci_child first = ci_job_child(path, false);
    assert(ci_read_response(first.response) == 1);
    ci_child second = ci_job_child(path, false);
    assert(ci_read_response(second.response) == 1);
    assert(encore_build_jobserver_used(server) == 2);
    encore_build_jobserver_close(server);
    assert(write(first.command, "a", 1) == 1 && ci_read_response(first.response) == -1);
    ci_finish(first, 0, 0); ci_finish(second, 'd', 0);
    snprintf(path, sizeof(path), "%s/processes", root);
    server = encore_build_jobserver_create_path(path, 1);
    first = ci_job_child(path, false);
    assert(ci_read_response(first.response) == 1);
    second = ci_job_child(path, false);
    assert(ci_read_response(second.response) == 0);
    ci_child refused = ci_job_child(path, false);
    assert(ci_read_response(refused.response) == -99);
    ci_finish(refused, 'd', 0); ci_finish(first, 'd', 0); ci_finish(second, 'd', 0);
    encore_build_jobserver_close(server);
    snprintf(path, sizeof(path), "%s/malformed", root);
    assert(encore_build_artifact_write(path, "bad", 3));
    assert(!encore_build_jobserver_attach_path(path));
    snprintf(path, sizeof(path), "%s/zero", root);
    assert(!encore_build_jobserver_create_path(path, 0));
    free(root); return 0;
}

enum { CI_BLOB_SIZE = 65540 };
typedef struct { const char *path; unsigned char blobs[4][CI_BLOB_SIZE]; atomic_bool running; } ci_artifact_state;
static void *ci_artifact_reader(void *raw) {
    ci_artifact_state *state = raw;
    do {
        size_t length = 0;
        char *data = encore_build_artifact_read(state->path, &length);
        assert(data != NULL && length == CI_BLOB_SIZE);
        bool valid = false;
        for (size_t index = 0; index < 4; ++index) if (!memcmp(data, state->blobs[index], CI_BLOB_SIZE)) valid = true;
        assert(valid);
        free(data);
    } while (atomic_load(&state->running));
    return NULL;
}
typedef struct { ci_artifact_state *state; size_t index; } ci_artifact_writer_args;
static void *ci_artifact_writer(void *raw) {
    ci_artifact_writer_args *args = raw;
    for (size_t iteration = 0; iteration < 25; ++iteration)
        assert(encore_build_artifact_write(args->state->path, args->state->blobs[args->index], CI_BLOB_SIZE));
    return NULL;
}

int32_t encore_ci_artifact(encore_compiler_str directory) {
    char *root = encore_compiler_cstr(directory); assert(root != NULL);
    char path[4096], stale[4096], other[4096];
    snprintf(path, sizeof(path), "%s/metadata.ermeta", root);
    snprintf(stale, sizeof(stale), "%s/metadata.ermeta.tmp-%lu-0", root, (unsigned long)getpid());
    FILE *file = fopen(stale, "wb"); assert(file != NULL);
    assert(fwrite("previous", 1, 8, file) == 8); fclose(file);
    ci_artifact_state state = {.path = path, .running = true};
    for (size_t index = 0; index < 4; ++index) {
        memset(state.blobs[index], (int)('A' + index), CI_BLOB_SIZE);
        memcpy(state.blobs[index] + CI_BLOB_SIZE - 4, "\0end", 4);
    }
    assert(encore_build_artifact_write(path, state.blobs[0], CI_BLOB_SIZE));
    pthread_t reader, writers[4]; ci_artifact_writer_args args[4];
    assert(pthread_create(&reader, NULL, ci_artifact_reader, &state) == 0);
    for (size_t index = 0; index < 4; ++index) {
        args[index] = (ci_artifact_writer_args){&state, index};
        assert(pthread_create(&writers[index], NULL, ci_artifact_writer, &args[index]) == 0);
    }
    for (size_t index = 0; index < 4; ++index) assert(pthread_join(writers[index], NULL) == 0);
    atomic_store(&state.running, false); assert(pthread_join(reader, NULL) == 0);
    file = fopen(stale, "rb"); assert(file != NULL);
    char data[9] = {0}; assert(fread(data, 1, 9, file) == 8 && !strcmp(data, "previous")); fclose(file);
    snprintf(other, sizeof(other), "%s/missing/artifact", root);
    assert(!encore_build_artifact_write(other, "x", 1));
    /* A failed transaction must neither change the committed blob nor leak
     * any temporary file. Only the deliberately stale file may remain. */
    atomic_store(&state.running, false);
    ci_artifact_reader(&state);
    DIR *entries = opendir(root); assert(entries != NULL);
    size_t temporary_count = 0;
    struct dirent *entry;
    while ((entry = readdir(entries)) != NULL)
        if (strncmp(entry->d_name, "metadata.ermeta.tmp-", 20) == 0) ++temporary_count;
    closedir(entries); assert(temporary_count == 1);
    snprintf(other, sizeof(other), "%s/empty", root);
    assert(encore_build_artifact_write(other, NULL, 0));
    struct stat info; assert(stat(other, &info) == 0 && info.st_size == 0);
    snprintf(path, sizeof(path), "%s/unit.lock", root);
    size_t lock = encore_build_cache_lock_open(path); assert(lock != 0 && encore_build_cache_lock_try(lock) == 1);
    for (size_t iteration = 0; iteration < 2; ++iteration) {
        pid_t child = fork(); assert(child >= 0);
        if (child == 0) {
            size_t competitor = encore_build_cache_lock_open(path); assert(competitor != 0);
            assert(encore_build_cache_lock_try(competitor) == (iteration == 0 ? 0 : 1));
            _exit(iteration == 0 ? 0 : 17);
        }
        int status; assert(waitpid(child, &status, 0) == child && WIFEXITED(status) && WEXITSTATUS(status) == (iteration == 0 ? 0 : 17));
        if (iteration == 0) encore_build_cache_lock_close(lock);
    }
    lock = encore_build_cache_lock_open(path); assert(lock != 0 && encore_build_cache_lock_try(lock) == 1);
    encore_build_cache_lock_close(lock);
    snprintf(other, sizeof(other), "%s/linked.lock", root);
    assert(symlink(path, other) == 0 && !encore_build_cache_lock_open(other));
    free(root); return 0;
}
