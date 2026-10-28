/* Exercise the actual runtime boundary, including simultaneous first access. */
#include "../runtime.c"
#include <assert.h>
#ifndef _WIN32
#include <sched.h>
#endif

#ifdef _WIN32
typedef HANDLE test_thread;
typedef DWORD (WINAPI *test_function)(void *);
#define TEST_RESULT DWORD WINAPI
static void test_yield(void) { SwitchToThread(); }
static test_thread test_start(test_function function, void *argument) {
    HANDLE thread = CreateThread(NULL, 0, function, argument, 0, NULL);
    assert(thread != NULL);
    return thread;
}
static void test_join(test_thread thread) {
    assert(WaitForSingleObject(thread, INFINITE) == WAIT_OBJECT_0);
    assert(CloseHandle(thread));
}
#else
typedef pthread_t test_thread;
typedef void *(*test_function)(void *);
#define TEST_RESULT void *
static void test_yield(void) { sched_yield(); }
static test_thread test_start(test_function function, void *argument) {
    pthread_t thread;
    assert(pthread_create(&thread, NULL, function, argument) == 0);
    return thread;
}
static void test_join(test_thread thread) { assert(pthread_join(thread, NULL) == 0); }
#endif

enum { READERS = 24 };
static atomic_uint arrived;
static atomic_uint initializations;
static unsigned payload;
static unsigned dropped;
static void release_static(size_t value) {
    /* Dependencies publish before their owners; owners must drop first. */
    assert(value == 2u - dropped);
    ++dropped;
}
static uintptr_t release_address(void) {
    void (*function)(size_t) = release_static;
    uintptr_t address;
    memcpy(&address, &function, sizeof(address));
    return address;
}


static TEST_RESULT reader(void *unused) {
    (void)unused;
    encore_str key = encore_from_cstr_copy("concurrent-static");
    void *cell = encore_static_cell_get(key);
    encore_str_drop(key);
    atomic_fetch_add(&arrived, 1);
    if (encore_static_begin(cell)) {
        while (atomic_load(&arrived) != READERS) test_yield();
        atomic_fetch_add(&initializations, 1);
        payload = 42;
        encore_static_publish(cell, (size_t)&payload);
    }
    assert(*(unsigned *)encore_static_value(cell) == 42);
    assert(!encore_static_begin(cell));
    return 0;
}

static TEST_RESULT cycle(void *argument) {
    bool second = argument != NULL;
    encore_str left = encore_from_cstr_copy(second ? "cycle-right" : "cycle-left");
    encore_str right = encore_from_cstr_copy(second ? "cycle-left" : "cycle-right");
    void *own = encore_static_cell_get(left), *other = encore_static_cell_get(right);
    encore_str_drop(left); encore_str_drop(right);
    assert(encore_static_begin(own));
    atomic_fetch_add(&arrived, 1);
    while (atomic_load(&arrived) != 2) test_yield();
    (void)encore_static_begin(other);
    abort();
}

int main(int argc, char **argv) {
    encore_str key = encore_from_cstr_copy("one-static");
    void *cell = encore_static_cell_get(key);
    assert(cell == encore_static_cell_get(key));
    encore_str_drop(key);
    assert(encore_static_begin(cell));
    if (argc > 1 && strcmp(argv[1], "recursive") == 0) {
        (void)encore_static_begin(cell);
        abort();
    }
    /* A zero value is still initialized; nested cells remain independent. */
    key = encore_from_cstr_copy("nested-static");
    void *nested = encore_static_cell_get(key);
    encore_str_drop(key);
    assert(nested != cell && encore_static_begin(nested));
    encore_static_publish(nested, 0);
    assert(!encore_static_begin(nested) && encore_static_value(nested) == 0);
    encore_static_publish(cell, 7);
    assert(!encore_static_begin(cell) && encore_static_value(cell) == 7);
    if (argc > 1 && strcmp(argv[1], "cross-thread-cycle") == 0) {
        test_thread left = test_start(cycle, NULL);
        test_thread right = test_start(cycle, (void *)1);
        test_join(left); test_join(right);
        abort();
    }
    test_thread readers[READERS];
    for (unsigned i = 0; i < READERS; ++i) readers[i] = test_start(reader, NULL);
    for (unsigned i = 0; i < READERS; ++i) test_join(readers[i]);
    assert(atomic_load(&initializations) == 1);
    key = encore_from_cstr_copy("owned-dependency");
    void *dependency = encore_static_cell_get(key); encore_str_drop(key);
    assert(encore_static_begin(dependency));
    encore_static_publish_owned(dependency, 1, release_address());
    key = encore_from_cstr_copy("owned-parent");
    void *parent = encore_static_cell_get(key); encore_str_drop(key);
    assert(encore_static_begin(parent));
    encore_static_publish_owned(parent, 2, release_address());
    encore_static_shutdown();
    assert(dropped == 2 && encore_static_cells == NULL && encore_static_created == NULL && encore_static_published == NULL);
    encore_static_shutdown();
    assert(dropped == 2);
    puts("static runtime passed");
    return 0;
}
