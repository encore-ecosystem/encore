#define _POSIX_C_SOURCE 200809L

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <inttypes.h>
#include <limits.h>
#include <stdarg.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#ifdef __APPLE__
#include <crt_externs.h>
#endif
#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <winsock2.h>
#include <ws2tcpip.h>
#include <direct.h>
#include <io.h>
#pragma comment(lib, "Ws2_32.lib")
#else
#include <sys/time.h>
#include <sys/wait.h>
#include <dirent.h>
#include <dlfcn.h>
#include <time.h>
#include <unistd.h>
#include <arpa/inet.h>
#include <netdb.h>
#include <sys/socket.h>
#endif

void *__ehir_pcast(size_t value) {
    return (void *)(uintptr_t)value;
}

void *__ehir_hrealloc(void *ptr, size_t bytes) {
    return realloc(ptr, bytes);
}

void __ehir_hfree(void *ptr) {
    free(ptr);
}

typedef struct {
    size_t ref_count;
    size_t len;
    char data[];
} encore_str_object;

typedef struct {
    encore_str_object *object;
} encore_str;

static struct {
    size_t ref_count;
    size_t len;
    char data[1];
} g_empty_str_object = {.ref_count = 0, .len = 0, .data = {0}};

static char *encore_str_data(encore_str value) {
    if (value.object == NULL) {
        return g_empty_str_object.data;
    }
    return value.object->data;
}

static size_t encore_str_size(encore_str value) {
    if (value.object == NULL) {
        return 0;
    }
    return value.object->len;
}

static encore_str encore_empty_str(void) {
    return (encore_str){.object = (encore_str_object *)&g_empty_str_object};
}

static char *encore_to_cstr(encore_str value) {
    size_t len = encore_str_size(value);
    char *buffer = malloc(len + 1);
    if (buffer == NULL) {
        return NULL;
    }

    char *data = encore_str_data(value);
    if (len > 0 && data != NULL) {
        memcpy(buffer, data, len);
    }
    buffer[len] = '\0';
    return buffer;
}

static encore_str encore_from_owned_buffer(char *buffer, size_t len) {
    if (buffer == NULL) {
        return encore_empty_str();
    }
    encore_str_object *object = malloc(sizeof(encore_str_object) + len + 1);
    if (object == NULL) {
        free(buffer);
        return encore_empty_str();
    }
    object->ref_count = 1;
    object->len = len;
    if (len > 0) {
        memcpy(object->data, buffer, len);
    }
    object->data[len] = '\0';
    free(buffer);
    return (encore_str){.object = object};
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
    return encore_from_owned_buffer(buffer, len);
}

void *encore_str_from_cstr(const char *value) {
    encore_str result = encore_from_cstr_copy(value);
    return result.object;
}

typedef struct {
    encore_str *ptr;
    size_t len;
    size_t cap;
} encore_str_vec;

encore_str encore_str_join_lines(encore_str_vec lines) {
    size_t total = lines.len > 0 ? lines.len - 1 : 0;
    for (size_t index = 0; index < lines.len; index += 1) {
        total += encore_str_size(lines.ptr[index]);
    }
    char *buffer = malloc(total + 1);
    if (buffer == NULL) {
        return encore_empty_str();
    }
    size_t offset = 0;
    for (size_t index = 0; index < lines.len; index += 1) {
        if (index > 0) {
            buffer[offset] = '\n';
            offset += 1;
        }
        size_t len = encore_str_size(lines.ptr[index]);
        if (len > 0) {
            memcpy(buffer + offset, encore_str_data(lines.ptr[index]), len);
            offset += len;
        }
    }
    buffer[offset] = '\0';
    return encore_from_owned_buffer(buffer, offset);
}

void encore_str_retain(encore_str value) {
    if (value.object == NULL || value.object->ref_count == 0) {
        return;
    }
    value.object->ref_count += 1;
}

void encore_str_drop(encore_str value) {
    if (value.object == NULL || value.object->ref_count == 0) {
        return;
    }
    if (value.object->ref_count == 0) {
        return;
    }
    value.object->ref_count -= 1;
    if (value.object->ref_count != 0) {
        return;
    }
    free(value.object);
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

uint64_t encore_clock_ms(uint8_t kind) {
#ifdef _WIN32
    if (kind == 0) {
        FILETIME ft;
        GetSystemTimeAsFileTime(&ft);
        ULARGE_INTEGER value;
        value.LowPart = ft.dwLowDateTime;
        value.HighPart = ft.dwHighDateTime;
        return (uint64_t)(value.QuadPart / 10000ULL);
    }

    LARGE_INTEGER frequency;
    LARGE_INTEGER counter;
    if (QueryPerformanceFrequency(&frequency) && QueryPerformanceCounter(&counter) && frequency.QuadPart > 0) {
        return (uint64_t)((counter.QuadPart * 1000ULL) / frequency.QuadPart);
    }
    return (uint64_t)GetTickCount64();
#else
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
#endif
}

bool encore_sleep_ms(uint64_t ms) {
#ifdef _WIN32
    Sleep((DWORD)ms);
    return true;
#else
    struct timespec req;
    req.tv_sec = (time_t)(ms / 1000ULL);
    req.tv_nsec = (long)((ms % 1000ULL) * 1000000ULL);

    while (nanosleep(&req, &req) != 0) {
        if (errno != EINTR) {
            return false;
        }
    }
    return true;
#endif
}

bool encore_str_eq(encore_str lhs, encore_str rhs) {
    size_t lhs_len = encore_str_size(lhs);
    size_t rhs_len = encore_str_size(rhs);
    if (lhs_len != rhs_len) {
        return false;
    }
    if (lhs_len == 0) {
        return true;
    }
    char *lhs_data = encore_str_data(lhs);
    char *rhs_data = encore_str_data(rhs);
    if (lhs_data == NULL || rhs_data == NULL) {
        return false;
    }
    return memcmp(lhs_data, rhs_data, lhs_len) == 0;
}

size_t encore_str_len(encore_str value) {
    return encore_str_size(value);
}

uint8_t encore_str_byte_at(encore_str value, size_t index) {
    size_t len = encore_str_size(value);
    char *data = encore_str_data(value);
    if (data == NULL || index >= len) {
        return 0;
    }
    return (uint8_t)data[index];
}

static size_t encore_utf8_char_width(uint8_t lead) {
    if ((lead & 0x80u) == 0u) {
        return 1;
    }
    if ((lead & 0xE0u) == 0xC0u) {
        return 2;
    }
    if ((lead & 0xF0u) == 0xE0u) {
        return 3;
    }
    if ((lead & 0xF8u) == 0xF0u) {
        return 4;
    }
    return 1;
}

static encore_str encore_str_copy_range(encore_str value, size_t start, size_t slice_len) {
    size_t len = encore_str_size(value);
    char *data = encore_str_data(value);
    if (data == NULL || start >= len) {
        return encore_empty_str();
    }

    size_t remaining = len - start;
    size_t actual_len = slice_len < remaining ? slice_len : remaining;
    char *buffer = malloc(actual_len + 1);
    if (buffer == NULL) {
        return encore_empty_str();
    }

    memcpy(buffer, data + start, actual_len);
    return encore_from_owned_buffer(buffer, actual_len);
}

encore_str encore_str_slice_bytes(encore_str value, size_t start, size_t byte_len) {
    return encore_str_copy_range(value, start, byte_len);
}

size_t encore_str_char_len(encore_str value) {
    size_t len = encore_str_size(value);
    char *data = encore_str_data(value);
    if (data == NULL || len == 0) {
        return 0;
    }

    size_t chars = 0;
    size_t i = 0;
    while (i < len) {
        size_t width = encore_utf8_char_width((uint8_t)data[i]);
        if (i + width > len) {
            width = 1;
        }
        i += width;
        chars += 1;
    }
    return chars;
}

encore_str encore_str_char_at(encore_str value, size_t index) {
    size_t len = encore_str_size(value);
    char *data = encore_str_data(value);
    if (data == NULL || len == 0) {
        return encore_empty_str();
    }

    size_t i = 0;
    size_t char_index = 0;
    while (i < len) {
        size_t width = encore_utf8_char_width((uint8_t)data[i]);
        if (i + width > len) {
            width = 1;
        }
        if (char_index == index) {
            return encore_str_copy_range(value, i, width);
        }
        i += width;
        char_index += 1;
    }
    return encore_empty_str();
}

encore_str encore_str_slice_chars(encore_str value, size_t start, size_t char_len) {
    size_t len = encore_str_size(value);
    char *data = encore_str_data(value);
    if (data == NULL || len == 0 || char_len == 0) {
        return encore_empty_str();
    }

    size_t i = 0;
    size_t char_index = 0;
    size_t start_byte = len;
    size_t end_byte = len;

    while (i < len) {
        if (char_index == start) {
            start_byte = i;
            break;
        }
        size_t width = encore_utf8_char_width((uint8_t)data[i]);
        if (i + width > len) {
            width = 1;
        }
        i += width;
        char_index += 1;
    }

    if (start_byte == len) {
        return encore_empty_str();
    }

    i = start_byte;
    size_t taken = 0;
    while (i < len && taken < char_len) {
        size_t width = encore_utf8_char_width((uint8_t)data[i]);
        if (i + width > len) {
            width = 1;
        }
        i += width;
        taken += 1;
    }
    end_byte = i;
    return encore_str_copy_range(value, start_byte, end_byte - start_byte);
}

encore_str encore_str_slice(encore_str value, size_t start, size_t slice_len) {
    return encore_str_copy_range(value, start, slice_len);
}

encore_str encore_str_concat(encore_str lhs, encore_str rhs) {
    size_t lhs_len = encore_str_size(lhs);
    size_t rhs_len = encore_str_size(rhs);
    char *lhs_data = encore_str_data(lhs);
    char *rhs_data = encore_str_data(rhs);
    size_t total_len = lhs_len + rhs_len;
    char *buffer = malloc(total_len + 1);
    if (buffer == NULL) {
        return encore_empty_str();
    }

    if (lhs_data != NULL && lhs_len > 0) {
        memcpy(buffer, lhs_data, lhs_len);
    }
    if (rhs_data != NULL && rhs_len > 0) {
        memcpy(buffer + lhs_len, rhs_data, rhs_len);
    }

    return encore_from_owned_buffer(buffer, total_len);
}

encore_str encore_fmt_u64(uint64_t value) {
    return encore_format("%" PRIu64, value);
}

encore_str encore_fmt_i64(int64_t value) {
    return encore_format("%" PRId64, value);
}

encore_str encore_fmt_f64(double value) {
    return encore_format("%.17g", value);
}

encore_str encore_io_read(int32_t fd, size_t max_bytes) {
    if (fd < 0 || max_bytes == 0 || max_bytes > SIZE_MAX - 1) {
        return encore_empty_str();
    }

    char *buffer = malloc(max_bytes + 1);
    if (buffer == NULL) {
        return encore_empty_str();
    }

#ifdef _WIN32
    size_t request = max_bytes > UINT_MAX ? UINT_MAX : max_bytes;
    int bytes_read = _read(fd, buffer, (unsigned int)request);
    if (bytes_read <= 0) {
        free(buffer);
        return encore_empty_str();
    }
    return encore_from_owned_buffer(buffer, (size_t)bytes_read);
#else
    ssize_t bytes_read = read(fd, buffer, max_bytes);
    if (bytes_read <= 0) {
        free(buffer);
        return encore_empty_str();
    }
    return encore_from_owned_buffer(buffer, (size_t)bytes_read);
#endif
}

int32_t encore_io_write(int32_t fd, encore_str value) {
    if (fd < 0) {
        return -1;
    }
    size_t len = encore_str_size(value);
    char *data = encore_str_data(value);
    if (len == 0) {
        return 0;
    }
    if (data == NULL) {
        return -1;
    }

    size_t offset = 0;
    while (offset < len) {
#ifdef _WIN32
        size_t remaining = len - offset;
        size_t request = remaining > UINT_MAX ? UINT_MAX : remaining;
        int written = _write(fd, data + offset, (unsigned int)request);
        if (written <= 0) {
            return -1;
        }
        offset += (size_t)written;
#else
        ssize_t written = write(fd, data + offset, len - offset);
        if (written < 0) {
            if (errno == EINTR) {
                continue;
            }
            return -1;
        }
        if (written == 0) {
            return -1;
        }
        offset += (size_t)written;
#endif
    }

    if (fd == 1) {
        fflush(stdout);
    } else if (fd == 2) {
        fflush(stderr);
    }
    return 0;
}

static char g_net_last_error[256] = {0};

static void encore_set_net_error_cstr(const char *msg) {
    if (msg == NULL) {
        g_net_last_error[0] = '\0';
        return;
    }
    snprintf(g_net_last_error, sizeof(g_net_last_error), "%s", msg);
}

static void encore_set_net_error_code(const char *prefix, int code) {
    if (prefix == NULL) {
        prefix = "net";
    }
#ifdef _WIN32
    snprintf(g_net_last_error, sizeof(g_net_last_error), "%s: %d", prefix, code);
#else
    snprintf(g_net_last_error, sizeof(g_net_last_error), "%s: %s", prefix, strerror(code));
#endif
}

encore_str encore_net_last_error(void) {
    if (g_net_last_error[0] == '\0') {
        return encore_empty_str();
    }
    return encore_from_cstr_copy(g_net_last_error);
}

#ifdef _WIN32
static bool g_winsock_initialized = false;

static bool encore_net_init(void) {
    if (g_winsock_initialized) {
        return true;
    }
    WSADATA wsa_data;
    int rc = WSAStartup(MAKEWORD(2, 2), &wsa_data);
    if (rc != 0) {
        encore_set_net_error_code("WSAStartup failed", rc);
        return false;
    }
    g_winsock_initialized = true;
    return true;
}

static int encore_last_socket_error(void) {
    return WSAGetLastError();
}

static int encore_close_socket(SOCKET fd) {
    return closesocket(fd);
}
#else
static bool encore_net_init(void) {
    return true;
}

static int encore_last_socket_error(void) {
    return errno;
}

static int encore_close_socket(int fd) {
    return close(fd);
}
#endif

static int32_t encore_parse_port(const char *port_c) {
    if (port_c == NULL) {
        return -1;
    }
    char *end = NULL;
    long parsed = strtol(port_c, &end, 10);
    bool ok = end != NULL && *end == '\0' && parsed >= 0 && parsed <= 65535;
    if (!ok) {
        return -1;
    }
    return (int32_t)parsed;
}

int32_t encore_net_tcp_connect(encore_str addr) {
    if (!encore_net_init()) {
        return -1;
    }

    char *addr_c = encore_to_cstr(addr);
    if (addr_c == NULL) {
        encore_set_net_error_cstr("alloc failed");
        return -1;
    }

    char *colon = strrchr(addr_c, ':');
    if (colon == NULL) {
        free(addr_c);
        encore_set_net_error_cstr("invalid addr, expected host:port");
        return -1;
    }
    *colon = '\0';
    const char *host = addr_c;
    int32_t port = encore_parse_port(colon + 1);
    if (port < 0) {
        free(addr_c);
        encore_set_net_error_cstr("invalid port");
        return -1;
    }

    struct addrinfo hints;
    memset(&hints, 0, sizeof(hints));
    hints.ai_family = AF_UNSPEC;
    hints.ai_socktype = SOCK_STREAM;

    char port_buf[16];
    snprintf(port_buf, sizeof(port_buf), "%d", (int)port);
    struct addrinfo *results = NULL;
    int gai_rc = getaddrinfo(host, port_buf, &hints, &results);
    if (gai_rc != 0 || results == NULL) {
        free(addr_c);
        encore_set_net_error_cstr("getaddrinfo failed");
        return -1;
    }

    int32_t out_fd = -1;
    for (struct addrinfo *it = results; it != NULL; it = it->ai_next) {
#ifdef _WIN32
        SOCKET fd = socket(it->ai_family, it->ai_socktype, it->ai_protocol);
        if (fd == INVALID_SOCKET) {
            continue;
        }
        if (connect(fd, it->ai_addr, (int)it->ai_addrlen) == 0) {
            out_fd = (int32_t)fd;
            break;
        }
        encore_close_socket(fd);
#else
        int fd = socket(it->ai_family, it->ai_socktype, it->ai_protocol);
        if (fd < 0) {
            continue;
        }
        if (connect(fd, it->ai_addr, it->ai_addrlen) == 0) {
            out_fd = (int32_t)fd;
            break;
        }
        encore_close_socket(fd);
#endif
    }
    if (out_fd < 0) {
        encore_set_net_error_code("connect failed", encore_last_socket_error());
    }

    freeaddrinfo(results);
    free(addr_c);
    return out_fd;
}

int32_t encore_net_tcp_bind(encore_str addr) {
    if (!encore_net_init()) {
        return -1;
    }

    char *addr_c = encore_to_cstr(addr);
    if (addr_c == NULL) {
        encore_set_net_error_cstr("alloc failed");
        return -1;
    }
    char *colon = strrchr(addr_c, ':');
    if (colon == NULL) {
        free(addr_c);
        encore_set_net_error_cstr("invalid addr, expected host:port");
        return -1;
    }
    *colon = '\0';
    const char *host = addr_c;
    int32_t port = encore_parse_port(colon + 1);
    if (port < 0) {
        free(addr_c);
        encore_set_net_error_cstr("invalid port");
        return -1;
    }

    struct addrinfo hints;
    memset(&hints, 0, sizeof(hints));
    hints.ai_family = AF_UNSPEC;
    hints.ai_socktype = SOCK_STREAM;
    hints.ai_flags = AI_PASSIVE;

    char port_buf[16];
    snprintf(port_buf, sizeof(port_buf), "%d", (int)port);
    struct addrinfo *results = NULL;
    int gai_rc = getaddrinfo(host, port_buf, &hints, &results);
    if (gai_rc != 0 || results == NULL) {
        free(addr_c);
        encore_set_net_error_cstr("getaddrinfo failed");
        return -1;
    }

    int32_t out_fd = -1;
    for (struct addrinfo *it = results; it != NULL; it = it->ai_next) {
#ifdef _WIN32
        SOCKET fd = socket(it->ai_family, it->ai_socktype, it->ai_protocol);
        if (fd == INVALID_SOCKET) {
            continue;
        }
        BOOL reuse = 1;
        setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, (const char *)&reuse, sizeof(reuse));
        if (bind(fd, it->ai_addr, (int)it->ai_addrlen) == 0 && listen(fd, 64) == 0) {
            out_fd = (int32_t)fd;
            break;
        }
        encore_close_socket(fd);
#else
        int fd = socket(it->ai_family, it->ai_socktype, it->ai_protocol);
        if (fd < 0) {
            continue;
        }
        int reuse = 1;
        setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &reuse, sizeof(reuse));
        if (bind(fd, it->ai_addr, it->ai_addrlen) == 0 && listen(fd, 64) == 0) {
            out_fd = (int32_t)fd;
            break;
        }
        encore_close_socket(fd);
#endif
    }
    if (out_fd < 0) {
        encore_set_net_error_code("bind/listen failed", encore_last_socket_error());
    }

    freeaddrinfo(results);
    free(addr_c);
    return out_fd;
}

int32_t encore_net_tcp_accept(int32_t listener_fd) {
    if (!encore_net_init()) {
        return -1;
    }
#ifdef _WIN32
    SOCKET fd = accept((SOCKET)listener_fd, NULL, NULL);
    if (fd == INVALID_SOCKET) {
        encore_set_net_error_code("accept failed", encore_last_socket_error());
        return -1;
    }
    return (int32_t)fd;
#else
    int fd = accept(listener_fd, NULL, NULL);
    if (fd < 0) {
        encore_set_net_error_code("accept failed", errno);
        return -1;
    }
    return fd;
#endif
}

encore_str encore_net_tcp_read(int32_t fd, size_t max) {
    if (max == 0) {
        return encore_empty_str();
    }
    char *buffer = malloc(max + 1);
    if (buffer == NULL) {
        encore_set_net_error_cstr("alloc failed");
        return encore_empty_str();
    }
#ifdef _WIN32
    int n = recv((SOCKET)fd, buffer, (int)max, 0);
    if (n < 0) {
        free(buffer);
        encore_set_net_error_code("recv failed", encore_last_socket_error());
        return encore_empty_str();
    }
    return encore_from_owned_buffer(buffer, (size_t)n);
#else
    ssize_t n = recv(fd, buffer, max, 0);
    if (n < 0) {
        free(buffer);
        encore_set_net_error_code("recv failed", errno);
        return encore_empty_str();
    }
    return encore_from_owned_buffer(buffer, (size_t)n);
#endif
}

int32_t encore_net_tcp_write(int32_t fd, encore_str data) {
    size_t len = encore_str_size(data);
    char *bytes = encore_str_data(data);
    if (bytes == NULL && len > 0) {
        encore_set_net_error_cstr("invalid data");
        return -1;
    }
#ifdef _WIN32
    int n = send((SOCKET)fd, bytes, (int)len, 0);
    if (n < 0) {
        encore_set_net_error_code("send failed", encore_last_socket_error());
        return -1;
    }
    return n;
#else
    ssize_t n = send(fd, bytes, len, 0);
    if (n < 0) {
        encore_set_net_error_code("send failed", errno);
        return -1;
    }
    return (int32_t)n;
#endif
}

int32_t encore_net_tcp_close(int32_t fd) {
    int rc = encore_close_socket(
#ifdef _WIN32
        (SOCKET)fd
#else
        fd
#endif
    );
    if (rc != 0) {
        encore_set_net_error_code("close failed", encore_last_socket_error());
        return -1;
    }
    return 0;
}

int32_t encore_proc_exit(int32_t code) {
    exit(code);
    return code;
}

int32_t encore_proc_run(encore_str command) {
    char *command_c = encore_to_cstr(command);
    if (command_c == NULL) {
        return -1;
    }

    int rc = system(command_c);
    free(command_c);
    if (rc == -1) {
        return -1;
    }
#ifdef _WIN32
    return rc;
#else
    if (WIFEXITED(rc)) {
        return WEXITSTATUS(rc);
    }
    if (WIFSIGNALED(rc)) {
        return 128 + WTERMSIG(rc);
    }
    return rc;
#endif
}

static bool g_args_initialized = false;
static size_t g_argc = 0;
static char **g_argv = NULL;

static void encore_free_args(void) {
    if (g_argv == NULL) {
        return;
    }
    for (size_t i = 0; i < g_argc; ++i) {
        free(g_argv[i]);
    }
    free(g_argv);
    g_argv = NULL;
    g_argc = 0;
}

static void encore_init_args(void) {
    if (g_args_initialized) {
        return;
    }
    g_args_initialized = true;
    atexit(encore_free_args);

#ifdef __APPLE__
    int argc = *_NSGetArgc();
    char **argv = *_NSGetArgv();
    if (argc <= 0 || argv == NULL) {
        return;
    }
    g_argc = (size_t)argc;
    g_argv = calloc(g_argc, sizeof(char *));
    if (g_argv == NULL) {
        g_argc = 0;
        return;
    }
    for (size_t i = 0; i < g_argc; ++i) {
        if (argv[i] != NULL) {
            g_argv[i] = strdup(argv[i]);
        }
    }
    return;
#endif

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

size_t encore_os_argc(void) {
    encore_init_args();
    return g_argc;
}

encore_str encore_os_argv(size_t index) {
    encore_init_args();
    if (index >= g_argc || g_argv == NULL || g_argv[index] == NULL) {
        return encore_empty_str();
    }
    return encore_from_cstr_copy(g_argv[index]);
}

encore_str encore_os_cwd(void) {
    size_t size = 256;

    for (;;) {
        char *buffer = malloc(size);
        if (buffer == NULL) {
            return encore_empty_str();
        }

        char *cwd_result =
#ifdef _WIN32
            _getcwd(buffer, (int)size);
#else
            getcwd(buffer, size);
#endif
        if (cwd_result != NULL) {
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

encore_str encore_os_home_dir(void) {
#ifdef _WIN32
    const char *home = getenv("USERPROFILE");
    if (home == NULL || home[0] == '\0') {
        const char *drive = getenv("HOMEDRIVE");
        const char *path = getenv("HOMEPATH");
        if (drive != NULL && path != NULL) {
            size_t drive_len = strlen(drive);
            size_t path_len = strlen(path);
            char *buffer = malloc(drive_len + path_len + 1);
            if (buffer == NULL) {
                return encore_empty_str();
            }
            memcpy(buffer, drive, drive_len);
            memcpy(buffer + drive_len, path, path_len + 1);
            return encore_from_owned_buffer(buffer, drive_len + path_len);
        }
    }
#else
    const char *home = getenv("HOME");
#endif
    if (home == NULL || home[0] == '\0') {
        return encore_empty_str();
    }
    return encore_from_cstr_copy(home);
}

encore_str encore_fs_read_file(encore_str path) {
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

int32_t encore_fs_write_file(encore_str path, encore_str contents) {
    char *path_c = encore_to_cstr(path);
    if (path_c == NULL) {
        return -1;
    }

    FILE *file = fopen(path_c, "wb");
    free(path_c);
    if (file == NULL) {
        return -1;
    }

    size_t contents_len = encore_str_size(contents);
    char *contents_data = encore_str_data(contents);
    size_t written = fwrite(contents_data, 1, contents_len, file);
    fclose(file);
    return written == contents_len ? 0 : -1;
}

int32_t encore_fs_status(encore_str path) {
    char *path_c = encore_to_cstr(path);
    if (path_c == NULL) {
        return -1;
    }

    struct stat st;
    int32_t result = stat(path_c, &st) == 0 ? 0 : -1;
    free(path_c);
    return result;
}

int32_t encore_fs_remove_file(encore_str path) {
    char *path_c = encore_to_cstr(path);
    if (path_c == NULL) {
        return -1;
    }

    int result = remove(path_c);
    free(path_c);
    return result == 0 ? 0 : -1;
}

int32_t encore_fs_mkdir(encore_str path) {
    char *path_c = encore_to_cstr(path);
    if (path_c == NULL) {
        return -1;
    }

    int rc =
#ifdef _WIN32
        _mkdir(path_c);
#else
        mkdir(path_c, 0755);
#endif
    int32_t status = (rc == 0 || errno == EEXIST) ? 0 : -1;
    free(path_c);
    return status;
}

static bool encore_append_dir_entry(char **buffer, size_t *cap, size_t *len, const char *name) {
    if (strcmp(name, ".") == 0 || strcmp(name, "..") == 0) {
        return true;
    }

    size_t name_len = strlen(name);
    size_t need = *len + name_len + 1;
    if (need > *cap) {
        size_t next_cap = *cap;
        while (need > next_cap) {
            if (next_cap > (SIZE_MAX / 2)) {
                return false;
            }
            next_cap *= 2;
        }
        char *next = realloc(*buffer, next_cap + 1);
        if (next == NULL) {
            return false;
        }
        *buffer = next;
        *cap = next_cap;
    }

    memcpy(*buffer + *len, name, name_len);
    *len += name_len;
    (*buffer)[(*len)++] = '\n';
    return true;
}

encore_str encore_fs_read_dir(encore_str path) {
    char *path_c = encore_to_cstr(path);
    if (path_c == NULL) {
        return encore_empty_str();
    }

#ifdef _WIN32
    size_t path_len = strlen(path_c);
    const char *suffix = (path_len > 0 && (path_c[path_len - 1] == '\\' || path_c[path_len - 1] == '/')) ? "*" : "\\*";
    char *pattern = malloc(path_len + strlen(suffix) + 1);
    if (pattern == NULL) {
        free(path_c);
        return encore_empty_str();
    }
    strcpy(pattern, path_c);
    strcat(pattern, suffix);
    free(path_c);

    WIN32_FIND_DATAA data;
    HANDLE handle = FindFirstFileA(pattern, &data);
    free(pattern);
    if (handle == INVALID_HANDLE_VALUE) {
        return encore_empty_str();
    }
#else
    DIR *dir = opendir(path_c);
    free(path_c);
    if (dir == NULL) {
        return encore_empty_str();
    }
#endif

    size_t cap = 256;
    size_t len = 0;
    char *buffer = malloc(cap + 1);
    if (buffer == NULL) {
#ifdef _WIN32
        FindClose(handle);
#else
        closedir(dir);
#endif
        return encore_empty_str();
    }

#ifdef _WIN32
    do {
        if (!encore_append_dir_entry(&buffer, &cap, &len, data.cFileName)) {
            free(buffer);
            FindClose(handle);
            return encore_empty_str();
        }
    } while (FindNextFileA(handle, &data));
    FindClose(handle);
#else
    struct dirent *entry = NULL;
    while ((entry = readdir(dir)) != NULL) {
        if (!encore_append_dir_entry(&buffer, &cap, &len, entry->d_name)) {
            free(buffer);
            closedir(dir);
            return encore_empty_str();
        }
    }
    closedir(dir);
#endif

    if (len > 0 && buffer[len - 1] == '\n') {
        len -= 1;
    }
    return encore_from_owned_buffer(buffer, len);
}

#ifndef _WIN32
typedef void EncoreGuiDisplay;
typedef void *EncoreGuiGc;
typedef unsigned long EncoreGuiWindowId;
typedef unsigned long EncoreGuiAtom;

typedef struct {
    bool initialized;
    bool available;
    void *lib;

    EncoreGuiDisplay *(*XOpenDisplay)(const char *);
    int (*XDefaultScreen)(EncoreGuiDisplay *);
    EncoreGuiWindowId (*XRootWindow)(EncoreGuiDisplay *, int);
    unsigned long (*XBlackPixel)(EncoreGuiDisplay *, int);
    unsigned long (*XWhitePixel)(EncoreGuiDisplay *, int);
    EncoreGuiWindowId (*XCreateSimpleWindow)(
        EncoreGuiDisplay *,
        EncoreGuiWindowId,
        int,
        int,
        unsigned int,
        unsigned int,
        unsigned int,
        unsigned long,
        unsigned long);
    int (*XStoreName)(EncoreGuiDisplay *, EncoreGuiWindowId, const char *);
    int (*XSelectInput)(EncoreGuiDisplay *, EncoreGuiWindowId, long);
    int (*XMapWindow)(EncoreGuiDisplay *, EncoreGuiWindowId);
    EncoreGuiGc (*XCreateGC)(EncoreGuiDisplay *, EncoreGuiWindowId, unsigned long, void *);
    int (*XFreeGC)(EncoreGuiDisplay *, EncoreGuiGc);
    int (*XSetForeground)(EncoreGuiDisplay *, EncoreGuiGc, unsigned long);
    int (*XFillRectangle)(EncoreGuiDisplay *, EncoreGuiWindowId, EncoreGuiGc, int, int, unsigned int, unsigned int);
    int (*XFlush)(EncoreGuiDisplay *);
    int (*XPending)(EncoreGuiDisplay *);
    int (*XNextEvent)(EncoreGuiDisplay *, void *);
    int (*XDestroyWindow)(EncoreGuiDisplay *, EncoreGuiWindowId);
    int (*XCloseDisplay)(EncoreGuiDisplay *);
    EncoreGuiAtom (*XInternAtom)(EncoreGuiDisplay *, const char *, int);
    int (*XSetWMProtocols)(EncoreGuiDisplay *, EncoreGuiWindowId, EncoreGuiAtom *, int);
} EncoreGuiX11Api;

typedef struct {
    EncoreGuiDisplay *display;
    EncoreGuiWindowId window;
    EncoreGuiGc gc;
    EncoreGuiAtom wm_delete;
    bool open;
    uint32_t width;
    uint32_t height;
} EncoreGuiWindow;

typedef struct {
    int type;
    unsigned long serial;
    int send_event;
    EncoreGuiDisplay *display;
    EncoreGuiWindowId window;
    EncoreGuiAtom message_type;
    int format;
    union {
        char b[20];
        short s[10];
        long l[5];
    } data;
} EncoreGuiXClientMessageEvent;

static EncoreGuiX11Api g_gui_x11 = {0};

#define ENCORE_X11_LOAD(field)                                                            \
    do {                                                                                  \
        *(void **)(&g_gui_x11.field) = dlsym(g_gui_x11.lib, #field);                      \
        if (g_gui_x11.field == NULL) {                                                     \
            dlclose(g_gui_x11.lib);                                                        \
            memset(&g_gui_x11, 0, sizeof(g_gui_x11));                                      \
            g_gui_x11.initialized = true;                                                  \
            return false;                                                                  \
        }                                                                                  \
    } while (0)

static bool encore_gui_x11_load(void) {
    if (g_gui_x11.initialized) {
        return g_gui_x11.available;
    }

    g_gui_x11.initialized = true;
    g_gui_x11.lib = dlopen("libX11.so.6", RTLD_LAZY | RTLD_LOCAL);
    if (g_gui_x11.lib == NULL) {
        g_gui_x11.lib = dlopen("libX11.so", RTLD_LAZY | RTLD_LOCAL);
    }
    if (g_gui_x11.lib == NULL) {
        return false;
    }

    ENCORE_X11_LOAD(XOpenDisplay);
    ENCORE_X11_LOAD(XDefaultScreen);
    ENCORE_X11_LOAD(XRootWindow);
    ENCORE_X11_LOAD(XBlackPixel);
    ENCORE_X11_LOAD(XWhitePixel);
    ENCORE_X11_LOAD(XCreateSimpleWindow);
    ENCORE_X11_LOAD(XStoreName);
    ENCORE_X11_LOAD(XSelectInput);
    ENCORE_X11_LOAD(XMapWindow);
    ENCORE_X11_LOAD(XCreateGC);
    ENCORE_X11_LOAD(XFreeGC);
    ENCORE_X11_LOAD(XSetForeground);
    ENCORE_X11_LOAD(XFillRectangle);
    ENCORE_X11_LOAD(XFlush);
    ENCORE_X11_LOAD(XPending);
    ENCORE_X11_LOAD(XNextEvent);
    ENCORE_X11_LOAD(XDestroyWindow);
    ENCORE_X11_LOAD(XCloseDisplay);
    ENCORE_X11_LOAD(XInternAtom);
    ENCORE_X11_LOAD(XSetWMProtocols);

    g_gui_x11.available = true;
    return true;
}

#undef ENCORE_X11_LOAD

static EncoreGuiWindow *encore_gui_window_from_handle(size_t handle) {
    if (handle == 0) {
        return NULL;
    }
    return (EncoreGuiWindow *)(uintptr_t)handle;
}

size_t encore_gui_window_create(encore_str title, uint32_t width, uint32_t height) {
    if (width == 0 || height == 0 || !encore_gui_x11_load()) {
        return 0;
    }

    EncoreGuiDisplay *display = g_gui_x11.XOpenDisplay(NULL);
    if (display == NULL) {
        return 0;
    }

    EncoreGuiWindow *state = calloc(1, sizeof(EncoreGuiWindow));
    if (state == NULL) {
        g_gui_x11.XCloseDisplay(display);
        return 0;
    }

    int screen = g_gui_x11.XDefaultScreen(display);
    EncoreGuiWindowId root = g_gui_x11.XRootWindow(display, screen);
    unsigned long black = g_gui_x11.XBlackPixel(display, screen);
    unsigned long white = g_gui_x11.XWhitePixel(display, screen);

    EncoreGuiWindowId window = g_gui_x11.XCreateSimpleWindow(display, root, 0, 0, width, height, 0, black, white);
    if (window == 0) {
        free(state);
        g_gui_x11.XCloseDisplay(display);
        return 0;
    }

    EncoreGuiGc gc = g_gui_x11.XCreateGC(display, window, 0, NULL);
    if (gc == NULL) {
        g_gui_x11.XDestroyWindow(display, window);
        free(state);
        g_gui_x11.XCloseDisplay(display);
        return 0;
    }

    char *title_c = encore_to_cstr(title);
    if (title_c != NULL) {
        g_gui_x11.XStoreName(display, window, title_c);
        free(title_c);
    }

    const long event_mask = (1L << 15) | (1L << 17) | (1L << 0);
    g_gui_x11.XSelectInput(display, window, event_mask);

    EncoreGuiAtom wm_delete = g_gui_x11.XInternAtom(display, "WM_DELETE_WINDOW", 0);
    if (wm_delete != 0) {
        g_gui_x11.XSetWMProtocols(display, window, &wm_delete, 1);
    }

    g_gui_x11.XMapWindow(display, window);
    g_gui_x11.XFlush(display);

    state->display = display;
    state->window = window;
    state->gc = gc;
    state->wm_delete = wm_delete;
    state->open = true;
    state->width = width;
    state->height = height;

    return (size_t)(uintptr_t)state;
}

bool encore_gui_window_is_open(size_t handle) {
    EncoreGuiWindow *state = encore_gui_window_from_handle(handle);
    return state != NULL && state->open;
}

bool encore_gui_window_poll(size_t handle) {
    EncoreGuiWindow *state = encore_gui_window_from_handle(handle);
    if (state == NULL || !state->open) {
        return false;
    }

    while (g_gui_x11.XPending(state->display) > 0) {
        long event_storage[24];
        memset(event_storage, 0, sizeof(event_storage));
        g_gui_x11.XNextEvent(state->display, event_storage);

        int type = *((int *)event_storage);
        if (type == 17) {
            state->open = false;
        } else if (type == 33 && state->wm_delete != 0) {
            EncoreGuiXClientMessageEvent *client = (EncoreGuiXClientMessageEvent *)event_storage;
            if (client->format == 32 && (EncoreGuiAtom)client->data.l[0] == state->wm_delete) {
                state->open = false;
            }
        }
    }

    return state->open;
}

bool encore_gui_window_clear(size_t handle, uint32_t color_rgb) {
    EncoreGuiWindow *state = encore_gui_window_from_handle(handle);
    if (state == NULL || !state->open) {
        return false;
    }

    g_gui_x11.XSetForeground(state->display, state->gc, (unsigned long)color_rgb);
    g_gui_x11.XFillRectangle(state->display, state->window, state->gc, 0, 0, state->width, state->height);
    return true;
}

bool encore_gui_window_fill_rect(size_t handle, int32_t x, int32_t y, uint32_t width, uint32_t height, uint32_t color_rgb) {
    EncoreGuiWindow *state = encore_gui_window_from_handle(handle);
    if (state == NULL || !state->open || width == 0 || height == 0) {
        return false;
    }

    g_gui_x11.XSetForeground(state->display, state->gc, (unsigned long)color_rgb);
    g_gui_x11.XFillRectangle(state->display, state->window, state->gc, x, y, width, height);
    return true;
}

bool encore_gui_window_present(size_t handle) {
    EncoreGuiWindow *state = encore_gui_window_from_handle(handle);
    if (state == NULL || !state->open) {
        return false;
    }
    g_gui_x11.XFlush(state->display);
    return true;
}

bool encore_gui_window_destroy(size_t handle) {
    EncoreGuiWindow *state = encore_gui_window_from_handle(handle);
    if (state == NULL) {
        return false;
    }

    if (state->display != NULL) {
        if (state->gc != NULL) {
            g_gui_x11.XFreeGC(state->display, state->gc);
        }
        if (state->window != 0) {
            g_gui_x11.XDestroyWindow(state->display, state->window);
        }
        g_gui_x11.XCloseDisplay(state->display);
    }

    free(state);
    return true;
}
#else
size_t encore_gui_window_create(encore_str title, uint32_t width, uint32_t height) {
    (void)title;
    (void)width;
    (void)height;
    return 0;
}

bool encore_gui_window_is_open(size_t handle) {
    (void)handle;
    return false;
}

bool encore_gui_window_poll(size_t handle) {
    (void)handle;
    return false;
}

bool encore_gui_window_clear(size_t handle, uint32_t color_rgb) {
    (void)handle;
    (void)color_rgb;
    return false;
}

bool encore_gui_window_fill_rect(size_t handle, int32_t x, int32_t y, uint32_t width, uint32_t height, uint32_t color_rgb) {
    (void)handle;
    (void)x;
    (void)y;
    (void)width;
    (void)height;
    (void)color_rgb;
    return false;
}

bool encore_gui_window_present(size_t handle) {
    (void)handle;
    return false;
}

bool encore_gui_window_destroy(size_t handle) {
    (void)handle;
    return false;
}
#endif
