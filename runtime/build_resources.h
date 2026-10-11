#ifndef ENCORE_BUILD_RESOURCES_H
#define ENCORE_BUILD_RESOURCES_H

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include <string.h>
#ifdef _WIN32
#include <windows.h>
#elif defined(__APPLE__)
#include <mach/mach.h>
#else
#include <stdio.h>
#endif

/* Cgroup byte values are strict decimal fields; "max" and malformed values
 * are unknown, never wrapped into a tiny or enormous admission budget. */
static inline bool encore_build_memory_number(const char *text, uint64_t *result) {
    if (text == NULL || result == NULL || *text < '0' || *text > '9') return false;
    uint64_t value = 0;
    while (*text >= '0' && *text <= '9') {
        unsigned digit = (unsigned)(*text++ - '0');
        if (value > (UINT64_MAX - digit) / 10) return false;
        value = value * 10 + digit;
    }
    while (*text == '\n' || *text == '\r') ++text;
    if (*text != '\0') return false;
    *result = value;
    return true;
}

static inline uint64_t encore_build_memory_remaining(uint64_t limit, uint64_t used) {
    /* Zero is reserved for unknown by callers. One means known exhaustion. */
    return used < limit ? limit - used : 1;
}

#if defined(__linux__)
static inline bool encore_build_read_memory_number(const char *path, uint64_t *result) {
    FILE *input = fopen(path, "r");
    if (input == NULL) return false;
    char text[128];
    bool valid = fgets(text, sizeof(text), input) != NULL && encore_build_memory_number(text, result);
    fclose(input);
    return valid;
}

static inline uint64_t encore_build_cgroup_directory_remaining(const char *directory, bool unified) {
    char path[8192];
    uint64_t limit, used;
    int length = snprintf(path, sizeof(path), "%s/%s", directory,
        unified ? "memory.max" : "memory.limit_in_bytes");
    if (length < 0 || (size_t)length >= sizeof(path) || !encore_build_read_memory_number(path, &limit)) return 0;
    length = snprintf(path, sizeof(path), "%s/%s", directory,
        unified ? "memory.current" : "memory.usage_in_bytes");
    if (length < 0 || (size_t)length >= sizeof(path) || !encore_build_read_memory_number(path, &used)) return 0;
    return encore_build_memory_remaining(limit, used);
}

static inline bool encore_build_cgroup_memory_controller(const char *controllers) {
    const char *cursor = controllers;
    while (*cursor != '\0') {
        const char *end = strchr(cursor, ',');
        size_t size = end == NULL ? strlen(cursor) : (size_t)(end - cursor);
        if (size == 6 && memcmp(cursor, "memory", 6) == 0) return true;
        if (end == NULL) break;
        cursor = end + 1;
    }
    return false;
}

static inline uint64_t encore_build_cgroup_available_memory(void) {
    uint64_t available = 0;
    /* Namespace roots can hide the host-relative path in /proc/self/cgroup. */
    const char *roots[] = {"/sys/fs/cgroup", "/sys/fs/cgroup/memory"};
    for (size_t i = 0; i < 2; ++i) {
        uint64_t value = encore_build_cgroup_directory_remaining(roots[i], i == 0);
        if (value != 0 && (available == 0 || value < available)) available = value;
    }
    FILE *input = fopen("/proc/self/cgroup", "r");
    if (input == NULL) return available;
    char line[8192];
    while (fgets(line, sizeof(line), input) != NULL) {
        char *first = strchr(line, ':');
        if (first == NULL) continue;
        char *second = strchr(first + 1, ':');
        if (second == NULL) continue;
        *second = '\0';
        bool unified = first[1] == '\0';
        if (!unified && !encore_build_cgroup_memory_controller(first + 1)) continue;
        char *relative = second + 1;
        relative[strcspn(relative, "\r\n")] = '\0';
        if (*relative != '/' || strstr(relative, "/../") != NULL || strstr(relative, "/./") != NULL ||
            strcmp(relative, "/..") == 0) continue;
        const char *root = roots[unified ? 0 : 1];
        char directory[8192];
        int length = snprintf(directory, sizeof(directory), "%s%s", root, relative);
        if (length < 0 || (size_t)length >= sizeof(directory)) continue;
        size_t boundary = strlen(root);
        /* Parent limits apply too, even when this leaf has memory.max=max. */
        while (strlen(directory) >= boundary) {
            uint64_t value = encore_build_cgroup_directory_remaining(directory, unified);
            if (value != 0 && (available == 0 || value < available)) available = value;
            if (strlen(directory) == boundary) break;
            char *slash = strrchr(directory, '/');
            if (slash == NULL || (size_t)(slash - directory) < boundary) break;
            *slash = '\0';
        }
    }
    fclose(input);
    return available;
}
#endif

/* Parse the kernel's physical-memory estimate, never swap or total RAM.
 * Overflow or an unknown format yields zero (unknown), not a fake huge budget. */
static inline uint64_t encore_build_memavailable_line(const char *line) {
    if (line == NULL || strncmp(line, "MemAvailable:", 13) != 0) return 0;
    const char *cursor = line + 13;
    while (*cursor == ' ' || *cursor == '\t') ++cursor;
    if (*cursor < '0' || *cursor > '9') return 0;
    uint64_t value = 0;
    while (*cursor >= '0' && *cursor <= '9') {
        unsigned digit = (unsigned)(*cursor++ - '0');
        if (value > (UINT64_MAX - digit) / 10) return 0;
        value = value * 10 + digit;
    }
    while (*cursor == ' ' || *cursor == '\t') ++cursor;
    if (cursor[0] != 'k' || cursor[1] != 'B') return 0;
    cursor += 2;
    while (*cursor == ' ' || *cursor == '\t' || *cursor == '\r' || *cursor == '\n') ++cursor;
    return *cursor == '\0' && value <= UINT64_MAX / 1024 ? value * 1024 : 0;
}

static inline uint64_t encore_build_available_memory(void) {
#ifdef _WIN32
    MEMORYSTATUSEX memory;
    memset(&memory, 0, sizeof(memory));
    memory.dwLength = sizeof(memory);
    return GlobalMemoryStatusEx(&memory) ? (uint64_t)memory.ullAvailPhys : 0;
#elif defined(__APPLE__)
    vm_statistics64_data_t memory;
    mach_msg_type_number_t count = HOST_VM_INFO64_COUNT;
    vm_size_t page_size;
    mach_port_t host = mach_host_self();
    bool valid = host_statistics64(host, HOST_VM_INFO64, (host_info64_t)&memory, &count) == KERN_SUCCESS
        && host_page_size(host, &page_size) == KERN_SUCCESS;
    mach_port_deallocate(mach_task_self(), host);
    if (!valid) return 0;
    uint64_t pages = (uint64_t)memory.free_count + memory.inactive_count + memory.speculative_count;
    return page_size != 0 && pages <= UINT64_MAX / page_size ? pages * page_size : 0;
#else
    FILE *input = fopen("/proc/meminfo", "r");
    if (input == NULL) return 0;
    char line[512];
    uint64_t available = 0;
    while (fgets(line, sizeof(line), input) != NULL) {
        if (strncmp(line, "MemAvailable:", 13) == 0) {
            available = encore_build_memavailable_line(line);
            break;
        }
    }
    fclose(input);
    uint64_t restricted = 0;
#if defined(__linux__)
    restricted = encore_build_cgroup_available_memory();
#endif
    return restricted != 0 && (available == 0 || restricted < available) ? restricted : available;
#endif
}

static inline uint64_t encore_build_memory_budget(uint64_t available) {
    /* Reserve 20%, without overflowing at UINT64_MAX. */
    return available - available / 5 - (available % 5 != 0);
}

static inline uint64_t encore_build_effective_memory_budget(void) {
    uint64_t available = encore_build_available_memory();
    uint64_t budget = encore_build_memory_budget(available);
    return available != 0 && budget == 0 ? 1 : budget;
}

#endif
