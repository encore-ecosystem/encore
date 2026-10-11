/* Native state isolation and dynamic queue contracts, independent of bootstrap. */
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdatomic.h>
#include <stdio.h>
#include "../../runtime/build_queue.h"

void encore_llvm_set_target_pointer_width(size_t bits);
void encore_llvm_set_windows_target(size_t enabled);
size_t encore_llvm_target_pointer_width(void);
size_t encore_llvm_is_windows_target(void);

#ifdef _WIN32
#include <windows.h>
typedef HANDLE test_thread;
#define TEST_THREAD_RESULT DWORD WINAPI
#define test_yield() SwitchToThread()
#else
#include <pthread.h>
#include <sched.h>
typedef pthread_t test_thread;
#define TEST_THREAD_RESULT void *
#define test_yield() sched_yield()
#endif

enum { TASKS = 20000, WORKERS = 12 };
static _Atomic unsigned seen[TASKS];
static _Atomic bool slow_started, release_slow;
static size_t queue;

static TEST_THREAD_RESULT stress_worker(void *argument) {
    const size_t worker = (size_t)argument;
    const size_t width = worker % 2 == 0 ? 32 : 64;
    const size_t windows = worker % 2;
    encore_llvm_set_target_pointer_width(width);
    encore_llvm_set_windows_target(windows);
    for (;;) {
        const size_t task = encore_build_queue_next(queue);
        if (task == SIZE_MAX) break;
        assert(task < TASKS);
        assert(atomic_fetch_add(&seen[task], 1) == 0);
        if (worker == 0 && task == 0) {
            atomic_store(&slow_started, true);
            while (!atomic_load(&release_slow)) test_yield();
        }
        if (task % 17 == 0) test_yield();
        assert(encore_llvm_target_pointer_width() == width);
        assert(encore_llvm_is_windows_target() == windows);
    }
    return 0;
}

static test_thread start_worker(size_t index) {
    test_thread thread;
#ifdef _WIN32
    thread = CreateThread(NULL, 0, stress_worker, (void *)index, 0, NULL);
    assert(thread != NULL);
#else
    assert(pthread_create(&thread, NULL, stress_worker, (void *)index) == 0);
#endif
    return thread;
}

static void join_worker(test_thread thread) {
#ifdef _WIN32
    assert(WaitForSingleObject(thread, INFINITE) == WAIT_OBJECT_0);
    assert(CloseHandle(thread));
#else
    assert(pthread_join(thread, NULL) == 0);
#endif
}

int main(void) {
    queue = encore_build_queue_new(TASKS);
    assert(queue != 0);
    test_thread threads[WORKERS];
    threads[0] = start_worker(0);
    while (!atomic_load(&slow_started)) test_yield();
    for (size_t index = 1; index < WORKERS; ++index) threads[index] = start_worker(index);
    for (size_t index = 1; index < WORKERS; ++index) join_worker(threads[index]);
    /* Even though the first task is still running, no static stripe or batch
     * barrier kept any of the other 19,999 tasks waiting behind it. */
    for (size_t index = 0; index < TASKS; ++index) assert(atomic_load(&seen[index]) == 1);
    atomic_store(&release_slow, true);
    join_worker(threads[0]);
    assert(encore_llvm_target_pointer_width() == sizeof(void *) * 8);
    assert(encore_llvm_is_windows_target() == 0);
    assert(encore_build_queue_next(queue) == SIZE_MAX);
    encore_build_queue_free(queue);

    queue = encore_build_queue_new(0);
    assert(queue && encore_build_queue_next(queue) == SIZE_MAX);
    encore_build_queue_free(queue);
    queue = encore_build_queue_new(100);
    assert(queue && encore_build_queue_next(queue) == 0);
    encore_build_queue_cancel(queue);
    assert(encore_build_queue_next(queue) == SIZE_MAX);
    encore_build_queue_free(queue);
    puts("dynamic queue: exactly-once, no batch barrier, cancellation; LLVM target TLS: isolated");
    return 0;
}
