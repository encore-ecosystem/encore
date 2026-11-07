/* Profile statistics are thread-owned; reporting/reset must never race with
 * writers. This small string adapter uses core's single private layout. */
#include "../packages/core/runtime_string.h"
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
_Static_assert(sizeof(encore_str) == sizeof(void *), "string handle ABI");
char *encore_str_data(encore_str value) { return value.object ? value.object->data : ""; }
size_t encore_str_size(encore_str value) { return value.object ? value.object->len : 0; }
encore_str encore_empty_str(void) { return (encore_str){NULL}; }
encore_str encore_from_owned_buffer(char *buffer, size_t len) {
    encore_str value = {malloc(sizeof(encore_str_object) + len + 1)};
    assert(value.object); atomic_init(&value.object->ref_count, 1); value.object->len = len;
    memcpy(value.object->data, buffer, len); value.object->data[len] = 0; free(buffer); return value;
}
static encore_str text(const char *source) {
    size_t len = strlen(source); char *data = malloc(len + 1); assert(data);
    memcpy(data, source, len + 1); return encore_from_owned_buffer(data, len);
}
#include "../packages/profile/runtime.c"
#ifdef _WIN32
#include <windows.h>
#define WORKER_RESULT DWORD WINAPI
#define WORKER_RETURN return 0
#else
#include <pthread.h>
#define WORKER_RESULT void *
#define WORKER_RETURN return NULL
#endif
static size_t manager, token;
static atomic_bool start = false;
static WORKER_RESULT worker(void *unused) {
    (void)unused;
    while (!atomic_load_explicit(&start, memory_order_acquire)) {}
    encore_str label = text("legacy");
    for (size_t i = 0; i < 10000; ++i) {
        encore_profile_record_registered(manager, token, 7);
        encore_profile_record(manager, label, 11);
    }
    free(label.object); WORKER_RETURN;
}
static void exercise(bool reset_during_write) {
    atomic_store(&start, false); encore_profile_reset(manager);
#ifdef _WIN32
    HANDLE workers[4];
    for (size_t i = 0; i < 4; ++i) { workers[i] = CreateThread(NULL, 0, worker, NULL, 0, NULL); assert(workers[i]); }
#else
    pthread_t workers[4];
    for (size_t i = 0; i < 4; ++i) assert(!pthread_create(&workers[i], NULL, worker, NULL));
#endif
    atomic_store_explicit(&start, true, memory_order_release);
    for (size_t i = 0; i < 100; ++i) {
        encore_str report = encore_profile_report(manager);
        assert(encore_str_size(report) >= 4); free(report.object);
        assert(encore_profile_sample_count(manager) <= 80000);
        if (reset_during_write) encore_profile_reset(manager);
    }
#ifdef _WIN32
    assert(WaitForMultipleObjects(4, workers, TRUE, INFINITE) == WAIT_OBJECT_0);
    for (size_t i = 0; i < 4; ++i) CloseHandle(workers[i]);
#else
    for (size_t i = 0; i < 4; ++i) assert(!pthread_join(workers[i], NULL));
#endif
    if (!reset_during_write) {
        assert(encore_profile_sample_count(manager) == 80000);
        encore_str report = encore_profile_report(manager);
        assert(strstr(encore_str_data(report), "registered: count=40000 total=280000ns avg=7ns min=7ns max=7ns"));
        assert(strstr(encore_str_data(report), "legacy: count=40000 total=440000ns avg=11ns min=11ns max=11ns"));
        free(report.object);
    }
}
int main(void) {
    encore_str name = text("test"), label = text("registered");
    manager = encore_profile_manager_new(name); assert(manager);
    assert(encore_profile_manager_new(name) == manager);
    token = encore_profile_register(manager, label); assert(token);
    assert(encore_profile_register(manager, label) == token);
    free(name.object); free(label.object);
    exercise(false); exercise(true);
    encore_profile_reset(manager); assert(encore_profile_sample_count(manager) == 0);
    encore_profile_record_registered(manager, token, 9);
    assert(encore_profile_sample_count(manager) == 1);
    puts("profile recording, reports, reset, and persistent label tokens: ok");
    return 0;
}
