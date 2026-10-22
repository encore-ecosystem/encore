#ifndef _WIN32
#if defined(__APPLE__) && !defined(_DARWIN_C_SOURCE)
#define _DARWIN_C_SOURCE
#endif
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#ifndef _POSIX_C_SOURCE
#define _POSIX_C_SOURCE 200809L
#endif
#endif
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include "runtime/build_queue.h"
#include "runtime/build_jobserver.h"
#include "runtime/build_process.h"
#include "runtime/build_artifact.h"
#include "runtime/cache_fs.h"
#include "runtime/build_identity.h"
#include "runtime/build_target.h"
#if defined(__GLIBC__)
#include <malloc.h>
#endif
#ifdef _WIN32
#include <process.h>
#else
#include <unistd.h>
#include <sys/types.h>
#include <sys/wait.h>
#endif

typedef struct encore_compiler_str_object {
    size_t ref_count;
    size_t len;
    char data[];
} encore_compiler_str_object;

typedef struct encore_compiler_str {
    encore_compiler_str_object *object;
} encore_compiler_str;

static char *encore_compiler_cstr(encore_compiler_str value) {
    size_t len = value.object == NULL ? 0 : value.object->len;
    char *out = (char *)malloc(len + 1);
    if (out == NULL) return NULL;
    if (len > 0) memcpy(out, value.object->data, len);
    out[len] = '\0';
    return out;
}

/* Bootstrap seeds use a std version from before the public set_env API. This
   fixed internal flag must also reach compiler workers spawned by `test`. */
bool encore_compiler_keep_build_artifacts(void) {
#ifdef _WIN32
    return _putenv_s("ENCORE_KEEP_TEMPS", "1") == 0 &&
        SetEnvironmentVariableW(L"ENCORE_KEEP_TEMPS", L"1") != 0;
#else
    return setenv("ENCORE_KEEP_TEMPS", "1", 1) == 0;
#endif
}

size_t encore_compiler_jobserver_create(encore_compiler_str path, size_t jobs) {
    char *name = encore_compiler_cstr(path);
    size_t server = encore_build_jobserver_create_path(name, jobs);
    free(name);
    return server;
}

size_t encore_compiler_jobserver_attach(encore_compiler_str path) {
    char *name = encore_compiler_cstr(path);
    size_t server = encore_build_jobserver_attach_path(name);
    free(name);
    return server;
}

int encore_compiler_jobserver_try_acquire(size_t server) {
    return encore_build_jobserver_try_acquire(server);
}

bool encore_compiler_jobserver_release(size_t server) {
    return encore_build_jobserver_release(server);
}

void encore_compiler_jobserver_cancel(size_t server) {
    encore_build_jobserver_cancel(server);
}

size_t encore_compiler_jobserver_used(size_t server) {
    return encore_build_jobserver_used(server);
}

void encore_compiler_jobserver_close(size_t server) {
    encore_build_jobserver_close(server);
}

size_t encore_compiler_worker_spawn_parts(encore_compiler_str program, size_t raw_args, size_t count,
    encore_compiler_str directory, encore_compiler_str stdout_path, encore_compiler_str stderr_path) {
    if (count > 65536 || (count != 0 && raw_args == 0)) return 0;
    const encore_compiler_str *args = (const encore_compiler_str *)raw_args;
    char **argv = calloc(count + 1, sizeof(*argv));
    char *name = encore_compiler_cstr(program);
    char *cwd = encore_compiler_cstr(directory);
    char *output = encore_compiler_cstr(stdout_path);
    char *error = encore_compiler_cstr(stderr_path);
    bool valid = argv != NULL && name != NULL && cwd != NULL && output != NULL && error != NULL;
    if (argv != NULL) for (size_t index = 0; index < count; ++index) {
        argv[index] = encore_compiler_cstr(args[index]);
        if (argv[index] == NULL) valid = false;
    }
    size_t child = valid ? encore_build_process_spawn(name, (const char *const *)argv, count, cwd, output, error) : 0;
    if (argv != NULL) for (size_t index = 0; index < count; ++index) free(argv[index]);
    free(argv); free(name); free(cwd); free(output); free(error);
    return child;
}

int encore_compiler_worker_poll(size_t child) { return encore_build_process_poll(child); }
int encore_compiler_worker_cancel(size_t child) { return encore_build_process_cancel(child); }
uint64_t encore_compiler_worker_peak_rss(size_t child) { return encore_build_process_peak_rss(child); }
void encore_compiler_worker_close(size_t child) { encore_build_process_close(child); }
int encore_compiler_worker_interrupted(void) { return encore_build_process_interrupted(); }
bool encore_compiler_worker_watch_parent(uint64_t parent) { return encore_build_worker_watch_parent(parent); }
uint64_t encore_compiler_process_id(void) { return encore_build_process_pid(); }

bool encore_compiler_write_atomic(encore_compiler_str path, encore_compiler_str contents) {
    char *name = encore_compiler_cstr(path);
    bool written = encore_build_artifact_write(name, contents.object == NULL ? NULL : contents.object->data,
        contents.object == NULL ? 0 : contents.object->len);
    free(name);
    return written;
}

size_t encore_compiler_cache_lock_open(encore_compiler_str path) {
    char *name = encore_compiler_cstr(path);
    size_t lock = encore_build_cache_lock_open(name);
    free(name);
    return lock;
}
int encore_compiler_cache_lock_try(size_t lock) { return encore_build_cache_lock_try(lock); }
void encore_compiler_cache_lock_close(size_t lock) { encore_build_cache_lock_close(lock); }

uint64_t encore_compiler_cache_file_fact(encore_compiler_str path, uint32_t field) {
    char *name = encore_compiler_cstr(path);
    uint64_t result = encore_cache_file_fact(name, field);
    free(name);
    return result;
}
int encore_compiler_cache_lock_shared(size_t lock) { return encore_cache_lock_shared(lock); }

/* Both paths are siblings in the registry cache. Publish only a fully checked
 * directory, under its registry installation lock. No external mv is needed. */
bool encore_compiler_publish_directory(encore_compiler_str source, encore_compiler_str destination) {
    char *from = encore_compiler_cstr(source), *to = encore_compiler_cstr(destination);
    bool moved = false;
    if (from != NULL && to != NULL) {
#ifdef _WIN32
        wchar_t *wide_from = encore_build_artifact_wide(from), *wide_to = encore_build_artifact_wide(to);
        moved = wide_from != NULL && wide_to != NULL && MoveFileExW(wide_from, wide_to, MOVEFILE_WRITE_THROUGH);
        free(wide_from); free(wide_to);
#else
        moved = rename(from, to) == 0;
#endif
    }
    free(from); free(to);
    return moved;
}

void encore_compiler_release_heap(void) {
#if defined(__GLIBC__)
    malloc_trim(0);
#endif
}

int encore_compiler_exec_parts(encore_compiler_str program, size_t raw_args, size_t args_len) {
    encore_compiler_str *args = (encore_compiler_str *)raw_args;
    char **argv = (char **)calloc(args_len + 2, sizeof(char *));
    if (argv == NULL) return -1;
    argv[0] = encore_compiler_cstr(program);
    if (argv[0] == NULL) { free(argv); return -1; }
    for (size_t index = 0; index < args_len; index += 1) {
        argv[index + 1] = encore_compiler_cstr(args[index]);
        if (argv[index + 1] == NULL) return -1;
    }
#ifdef _WIN32
    return (int)_spawnvp(_P_WAIT, argv[0], (const char *const *)argv);
#else
    execvp(argv[0], argv);
    return -1;
#endif
}

static encore_compiler_str encore_compiler_owned_string(char *data, size_t len) {
    encore_compiler_str out = {NULL};
    encore_compiler_str_object *object = malloc(sizeof(*object) + len + 1);
    if (object == NULL) { free(data); return out; }
    object->ref_count = 1; object->len = len;
    if (len > 0) memcpy(object->data, data, len);
    object->data[len] = '\0'; free(data); out.object = object; return out;
}

encore_compiler_str encore_compiler_read_artifact(encore_compiler_str path) {
    char *name = encore_compiler_cstr(path);
    size_t length = 0;
    char *data = encore_build_artifact_read(name, &length);
    free(name);
    if (data == NULL) return (encore_compiler_str){NULL};
    return encore_compiler_owned_string(data, length);
}

static bool encore_compiler_identifier_byte(unsigned char value) {
    return (value >= '0' && value <= '9') ||
           (value >= 'A' && value <= 'Z') ||
           (value >= 'a' && value <= 'z') || value == '_';
}

bool encore_compiler_str_contains(encore_compiler_str value,
                                  encore_compiler_str needle) {
    const size_t value_len = value.object == NULL ? 0 : value.object->len;
    const size_t needle_len = needle.object == NULL ? 0 : needle.object->len;
    if (needle_len == 0) return true;
    if (needle_len > value_len || value.object == NULL || needle.object == NULL)
        return false;
    for (size_t index = 0; index + needle_len <= value_len; ++index) {
        if (memcmp(value.object->data + index, needle.object->data, needle_len) == 0)
            return true;
    }
    return false;
}

static encore_compiler_str encore_compiler_replace_ehir_identifier_impl(
    encore_compiler_str value, encore_compiler_str token,
    encore_compiler_str replacement, bool scoped) {
    const char *source = value.object == NULL ? "" : value.object->data;
    const char *match = token.object == NULL ? "" : token.object->data;
    const char *insert = replacement.object == NULL ? "" : replacement.object->data;
    const size_t source_len = value.object == NULL ? 0 : value.object->len;
    const size_t match_len = token.object == NULL ? 0 : token.object->len;
    const size_t insert_len = replacement.object == NULL ? 0 : replacement.object->len;
    unsigned char *generic_mask = scoped ? encore_build_generic_mask(source, source_len, match, match_len) : NULL;
    if (scoped && generic_mask == NULL) return (encore_compiler_str){NULL};
    size_t count = 0, index = 0;
    bool quoted = false, escaped = false, comment = false;

    while (match_len > 0 && index < source_len) {
        const unsigned char byte = (unsigned char)source[index];
        if (comment) {
            if (byte == '\n') comment = false;
            ++index; continue;
        }
        if (quoted) {
            if (escaped) escaped = false;
            else if (byte == '\\') escaped = true;
            else if (byte == '"') quoted = false;
            ++index; continue;
        }
        if (byte == '"') { quoted = true; ++index; continue; }
        if (byte == '/' && index + 1 < source_len && source[index + 1] == '/') {
            comment = true; index += 2; continue;
        }
        if ((generic_mask == NULL || !generic_mask[index]) && index + match_len <= source_len &&
            (!scoped || !encore_build_member_identifier(source, source_len, index, match_len)) &&
            memcmp(source + index, match, match_len) == 0 &&
            (index == 0 || !encore_compiler_identifier_byte((unsigned char)source[index - 1])) &&
            (index + match_len == source_len ||
             !encore_compiler_identifier_byte((unsigned char)source[index + match_len]))) {
            ++count; index += match_len; continue;
        }
        ++index;
    }

    if (insert_len >= match_len && insert_len != match_len && count > (SIZE_MAX - source_len - 1) / (insert_len - match_len)) {
        free(generic_mask); return (encore_compiler_str){NULL};
    }
    const size_t output_len = insert_len >= match_len
        ? source_len + count * (insert_len - match_len)
        : source_len - count * (match_len - insert_len);
    char *output = malloc(output_len + 1);
    if (output == NULL) { free(generic_mask); return (encore_compiler_str){NULL}; }
    size_t written = 0; index = 0;
    quoted = false; escaped = false; comment = false;
    while (index < source_len) {
        const unsigned char byte = (unsigned char)source[index];
        bool replace = false;
        if (!comment && !quoted && match_len > 0 && (generic_mask == NULL || !generic_mask[index]) &&
            index + match_len <= source_len &&
            (!scoped || !encore_build_member_identifier(source, source_len, index, match_len)) &&
            memcmp(source + index, match, match_len) == 0 &&
            (index == 0 || !encore_compiler_identifier_byte((unsigned char)source[index - 1])) &&
            (index + match_len == source_len ||
             !encore_compiler_identifier_byte((unsigned char)source[index + match_len]))) {
            replace = true;
        }
        if (replace) {
            if (insert_len > 0) memcpy(output + written, insert, insert_len);
            written += insert_len; index += match_len; continue;
        }
        output[written++] = source[index++];
        if (comment) {
            if (byte == '\n') comment = false;
        } else if (quoted) {
            if (escaped) escaped = false;
            else if (byte == '\\') escaped = true;
            else if (byte == '"') quoted = false;
        } else if (byte == '"') {
            quoted = true;
        } else if (byte == '/' && index < source_len && source[index] == '/') {
            output[written++] = source[index++];
            comment = true;
        }
    }
    output[written] = '\0';
    free(generic_mask);
    return encore_compiler_owned_string(output, written);
}

encore_compiler_str encore_compiler_replace_ehir_identifier(encore_compiler_str value,
    encore_compiler_str token, encore_compiler_str replacement) {
    return encore_compiler_replace_ehir_identifier_impl(value, token, replacement, false);
}

encore_compiler_str encore_compiler_replace_scoped_ehir_identifier(encore_compiler_str value,
    encore_compiler_str token, encore_compiler_str replacement) {
    return encore_compiler_replace_ehir_identifier_impl(value, token, replacement, true);
}
