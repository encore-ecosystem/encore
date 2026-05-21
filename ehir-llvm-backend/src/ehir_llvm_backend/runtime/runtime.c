#define _POSIX_C_SOURCE 200809L

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <inttypes.h>
#include <stdarg.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <dirent.h>
#include <time.h>
#include <unistd.h>

typedef struct {
    char *ptr;
    size_t len;
} encore_str;

static encore_str encore_empty_str(void) {
    static char empty[] = "";
    return (encore_str){.ptr = empty, .len = 0};
}

static char *encore_to_cstr(encore_str value) {
    char *buffer = malloc(value.len + 1);
    if (buffer == NULL) {
        return NULL;
    }

    if (value.len > 0 && value.ptr != NULL) {
        memcpy(buffer, value.ptr, value.len);
    }
    buffer[value.len] = '\0';
    return buffer;
}

static encore_str encore_from_owned_buffer(char *buffer, size_t len) {
    if (buffer == NULL) {
        return encore_empty_str();
    }
    buffer[len] = '\0';
    return (encore_str){.ptr = buffer, .len = len};
}

static encore_str encore_from_cstr_copy(const char *value) {
    if (value == NULL) {
        return encore_empty_str();
    }

    size_t len = strlen(value);
    char *buffer = malloc(len + 1);
    if (buffer == NULL) {
        return encore_empty_str();
    }
    memcpy(buffer, value, len + 1);
    return (encore_str){.ptr = buffer, .len = len};
}

static encore_str encore_format(const char *fmt, ...) {
    va_list args;
    va_start(args, fmt);
    int needed = vsnprintf(NULL, 0, fmt, args);
    va_end(args);
    if (needed < 0) {
        return encore_empty_str();
    }

    char *buffer = malloc((size_t)needed + 1);
    if (buffer == NULL) {
        return encore_empty_str();
    }

    va_start(args, fmt);
    int written = vsnprintf(buffer, (size_t)needed + 1, fmt, args);
    va_end(args);
    if (written < 0) {
        free(buffer);
        return encore_empty_str();
    }

    return encore_from_owned_buffer(buffer, (size_t)written);
}

uint64_t __ehir_rt_clock_ms(uint8_t kind) {
    struct timespec ts;
    clockid_t clock_kind = kind == 0 ? CLOCK_REALTIME : CLOCK_MONOTONIC;
    if (clock_gettime(clock_kind, &ts) == 0) {
        return ((uint64_t)ts.tv_sec * 1000ULL) + ((uint64_t)ts.tv_nsec / 1000000ULL);
    }

    struct timeval tv;
    if (gettimeofday(&tv, NULL) == 0) {
        return ((uint64_t)tv.tv_sec * 1000ULL) + ((uint64_t)tv.tv_usec / 1000ULL);
    }
    return 0ULL;
}

bool __ehir_rt_sleep_ms(uint64_t ms) {
    struct timespec req;
    req.tv_sec = (time_t)(ms / 1000ULL);
    req.tv_nsec = (long)((ms % 1000ULL) * 1000000ULL);

    while (nanosleep(&req, &req) != 0) {
        if (errno != EINTR) {
            return false;
        }
    }
    return true;
}

bool __ehir_rt_str_eq(encore_str lhs, encore_str rhs) {
    if (lhs.len != rhs.len) {
        return false;
    }
    if (lhs.len == 0) {
        return true;
    }
    if (lhs.ptr == NULL || rhs.ptr == NULL) {
        return false;
    }
    return memcmp(lhs.ptr, rhs.ptr, lhs.len) == 0;
}

size_t __ehir_rt_str_len(encore_str value) {
    return value.len;
}

uint8_t __ehir_rt_str_byte_at(encore_str value, size_t index) {
    if (value.ptr == NULL || index >= value.len) {
        return 0;
    }
    return (uint8_t)value.ptr[index];
}

encore_str __ehir_rt_str_slice(encore_str value, size_t start, size_t slice_len) {
    if (value.ptr == NULL || start >= value.len) {
        return encore_empty_str();
    }

    size_t remaining = value.len - start;
    size_t actual_len = slice_len < remaining ? slice_len : remaining;
    char *buffer = malloc(actual_len + 1);
    if (buffer == NULL) {
        return encore_empty_str();
    }

    memcpy(buffer, value.ptr + start, actual_len);
    return encore_from_owned_buffer(buffer, actual_len);
}

encore_str __ehir_rt_str_concat(encore_str lhs, encore_str rhs) {
    size_t total_len = lhs.len + rhs.len;
    char *buffer = malloc(total_len + 1);
    if (buffer == NULL) {
        return encore_empty_str();
    }

    if (lhs.ptr != NULL && lhs.len > 0) {
        memcpy(buffer, lhs.ptr, lhs.len);
    }
    if (rhs.ptr != NULL && rhs.len > 0) {
        memcpy(buffer + lhs.len, rhs.ptr, rhs.len);
    }

    return encore_from_owned_buffer(buffer, total_len);
}

encore_str __ehir_rt_fmt_u64(uint64_t value) {
    return encore_format("%" PRIu64, value);
}

encore_str __ehir_rt_fmt_i64(int64_t value) {
    return encore_format("%" PRId64, value);
}

encore_str __ehir_rt_fmt_f64(double value) {
    return encore_format("%.17g", value);
}

int32_t __ehir_rt_io_write(int32_t fd, encore_str value) {
    FILE *stream = NULL;
    if (fd == 1) {
        stream = stdout;
    } else if (fd == 2) {
        stream = stderr;
    } else {
        return -1;
    }
    size_t written = fwrite(value.ptr, 1, value.len, stream);
    fflush(stream);
    return written == value.len ? 0 : -1;
}

int32_t __ehir_rt_proc_exit(int32_t code) {
    exit(code);
    return code;
}

static bool g_args_initialized = false;
static size_t g_argc = 0;
static char **g_argv = NULL;

static void encore_init_args(void) {
    if (g_args_initialized) {
        return;
    }
    g_args_initialized = true;

    FILE *file = fopen("/proc/self/cmdline", "rb");
    if (file == NULL) {
        return;
    }
    size_t capacity = 256;
    size_t read_count = 0;
    char *buffer = malloc(capacity);
    if (buffer == NULL) {
        fclose(file);
        return;
    }

    while (true) {
        if (read_count == capacity) {
            size_t next_capacity = capacity * 2;
            char *next_buffer = realloc(buffer, next_capacity);
            if (next_buffer == NULL) {
                free(buffer);
                fclose(file);
                return;
            }
            buffer = next_buffer;
            capacity = next_capacity;
        }

        size_t chunk = fread(buffer + read_count, 1, capacity - read_count, file);
        read_count += chunk;
        if (chunk == 0) {
            break;
        }
    }
    fclose(file);
    if (read_count == 0) {
        free(buffer);
        return;
    }

    for (size_t i = 0; i < read_count; ++i) {
        if (buffer[i] == '\0') {
            g_argc += 1;
        }
    }
    if (g_argc == 0) {
        free(buffer);
        return;
    }

    g_argv = calloc(g_argc, sizeof(char *));
    if (g_argv == NULL) {
        g_argc = 0;
        free(buffer);
        return;
    }

    size_t arg_index = 0;
    size_t start = 0;
    for (size_t i = 0; i < read_count; ++i) {
        if (buffer[i] != '\0') {
            continue;
        }

        size_t len = i - start;
        char *arg = malloc(len + 1);
        if (arg == NULL) {
            start = i + 1;
            continue;
        }
        memcpy(arg, buffer + start, len);
        arg[len] = '\0';
        g_argv[arg_index++] = arg;
        start = i + 1;
    }

    free(buffer);
}

size_t __ehir_rt_os_argc(void) {
    encore_init_args();
    return g_argc;
}

encore_str __ehir_rt_os_argv(size_t index) {
    encore_init_args();
    if (index >= g_argc || g_argv == NULL || g_argv[index] == NULL) {
        return encore_empty_str();
    }
    return encore_from_cstr_copy(g_argv[index]);
}

encore_str __ehir_rt_os_cwd(void) {
    size_t size = 256;

    for (;;) {
        char *buffer = malloc(size);
        if (buffer == NULL) {
            return encore_empty_str();
        }

        if (getcwd(buffer, size) != NULL) {
            size_t len = strlen(buffer);
            return encore_from_owned_buffer(buffer, len);
        }

        free(buffer);
        if (errno != ERANGE) {
            return encore_empty_str();
        }

        if (size > (SIZE_MAX / 2)) {
            return encore_empty_str();
        }
        size *= 2;
    }
}

encore_str __ehir_rt_fs_read_file(encore_str path) {
    char *path_c = encore_to_cstr(path);
    if (path_c == NULL) {
        return encore_empty_str();
    }

    FILE *file = fopen(path_c, "rb");
    free(path_c);
    if (file == NULL) {
        return encore_empty_str();
    }

    if (fseek(file, 0, SEEK_END) != 0) {
        fclose(file);
        return encore_empty_str();
    }
    long length = ftell(file);
    if (length < 0) {
        fclose(file);
        return encore_empty_str();
    }
    rewind(file);

    char *buffer = malloc((size_t)length + 1);
    if (buffer == NULL) {
        fclose(file);
        return encore_empty_str();
    }

    size_t read_count = fread(buffer, 1, (size_t)length, file);
    fclose(file);
    return encore_from_owned_buffer(buffer, read_count);
}

int32_t __ehir_rt_fs_write_file(encore_str path, encore_str contents) {
    char *path_c = encore_to_cstr(path);
    if (path_c == NULL) {
        return -1;
    }

    FILE *file = fopen(path_c, "wb");
    free(path_c);
    if (file == NULL) {
        return -1;
    }

    size_t written = fwrite(contents.ptr, 1, contents.len, file);
    fclose(file);
    return written == contents.len ? 0 : -1;
}

int32_t __ehir_rt_fs_status(encore_str path) {
    char *path_c = encore_to_cstr(path);
    if (path_c == NULL) {
        return -1;
    }

    struct stat st;
    int32_t result = stat(path_c, &st) == 0 ? 0 : -1;
    free(path_c);
    return result;
}

int32_t __ehir_rt_fs_remove_file(encore_str path) {
    char *path_c = encore_to_cstr(path);
    if (path_c == NULL) {
        return -1;
    }

    int result = remove(path_c);
    free(path_c);
    return result == 0 ? 0 : -1;
}

int32_t __ehir_rt_fs_mkdir(encore_str path) {
    char *path_c = encore_to_cstr(path);
    if (path_c == NULL) {
        return -1;
    }

    int rc = mkdir(path_c, 0755);
    int32_t status = (rc == 0 || errno == EEXIST) ? 0 : -1;
    free(path_c);
    return status;
}

encore_str __ehir_rt_fs_read_dir(encore_str path) {
    char *path_c = encore_to_cstr(path);
    if (path_c == NULL) {
        return encore_empty_str();
    }

    DIR *dir = opendir(path_c);
    free(path_c);
    if (dir == NULL) {
        return encore_empty_str();
    }

    size_t cap = 256;
    size_t len = 0;
    char *buffer = malloc(cap + 1);
    if (buffer == NULL) {
        closedir(dir);
        return encore_empty_str();
    }

    struct dirent *entry = NULL;
    while ((entry = readdir(dir)) != NULL) {
        const char *name = entry->d_name;
        if (strcmp(name, ".") == 0 || strcmp(name, "..") == 0) {
            continue;
        }

        size_t name_len = strlen(name);
        size_t need = len + name_len + 1; // + '\n'
        if (need > cap) {
            size_t next_cap = cap;
            while (need > next_cap) {
                if (next_cap > (SIZE_MAX / 2)) {
                    free(buffer);
                    closedir(dir);
                    return encore_empty_str();
                }
                next_cap *= 2;
            }
            char *next = realloc(buffer, next_cap + 1);
            if (next == NULL) {
                free(buffer);
                closedir(dir);
                return encore_empty_str();
            }
            buffer = next;
            cap = next_cap;
        }

        memcpy(buffer + len, name, name_len);
        len += name_len;
        buffer[len++] = '\n';
    }
    closedir(dir);

    if (len > 0 && buffer[len - 1] == '\n') {
        len -= 1;
    }
    return encore_from_owned_buffer(buffer, len);
}
