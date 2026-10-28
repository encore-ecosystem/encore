#include "../../plugin_runtime.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <stdatomic.h>
#ifdef _WIN32
#include <windows.h>
#include <shellapi.h>
#include <process.h>
typedef HANDLE test_thread;
#define TEST_THREAD_RETURN unsigned __stdcall
#define TEST_THREAD_DONE 0
static void test_yield(void) { Sleep(0); }
#else
#include <pthread.h>
#include <sched.h>
typedef pthread_t test_thread;
#define TEST_THREAD_RETURN void *
#define TEST_THREAD_DONE NULL
static void test_yield(void) { sched_yield(); }
#endif
static encore_plugin_binding *worker_binding;
static _Atomic unsigned workers_started;
static _Atomic bool release_held_call;
static TEST_THREAD_RETURN increment_worker(void *unused) {
    (void)unused; atomic_fetch_add(&workers_started, 1);
    for (size_t i = 0; i < 250;) {
        encore_plugin_value arg = {.kind=ENCORE_PLUGIN_U64,.bits=1};
        encore_plugin_call result;
        encore_plugin_status status = encore_plugin_invoke(worker_binding, 0, &arg, 1, &result);
        assert(status == ENCORE_PLUGIN_OK || status == ENCORE_PLUGIN_BUSY);
        encore_plugin_call_clear(&result);
        if (status == ENCORE_PLUGIN_OK) ++i; else test_yield();
    }
    return TEST_THREAD_DONE;
}
static TEST_THREAD_RETURN hold_worker(void *unused) {
    (void)unused; encore_plugin_call result;
    assert(encore_plugin_invoke(worker_binding, 1, NULL, 0, &result) == ENCORE_PLUGIN_OK);
    atomic_fetch_add(&workers_started, 1);
    while (!atomic_load(&release_held_call)) test_yield();
    encore_plugin_call_clear(&result); return TEST_THREAD_DONE;
}
#ifdef _WIN32
static test_thread start_worker(unsigned (__stdcall *fn)(void *)) {
    uintptr_t handle = _beginthreadex(NULL, 0, fn, NULL, 0, NULL); assert(handle); return (HANDLE)handle;
}
static void join_worker(test_thread thread) { assert(WaitForSingleObject(thread, INFINITE) == WAIT_OBJECT_0); CloseHandle(thread); }
#else
static test_thread start_worker(void *(*fn)(void *)) { test_thread thread; assert(pthread_create(&thread,NULL,fn,NULL)==0); return thread; }
static void join_worker(test_thread thread) { assert(pthread_join(thread,NULL)==0); }
#endif

static uint64_t call(encore_plugin_binding *binding, uint64_t value) {
    encore_plugin_value argument = {.kind = ENCORE_PLUGIN_U64, .bits = value};
    encore_plugin_call result;
    assert(encore_plugin_invoke(binding, 0, &argument, 1, &result) == ENCORE_PLUGIN_OK);
    assert(result.value.kind == ENCORE_PLUGIN_U64);
    uint64_t returned = result.value.bits;
    encore_plugin_call_clear(&result);
    return returned;
}
int main(int argc, char **argv) {
#ifdef _WIN32
    int wide_count = 0; wchar_t **wide = CommandLineToArgvW(GetCommandLineW(), &wide_count);
    assert(wide && wide_count == argc);
    char **utf8 = calloc((size_t)argc, sizeof(*utf8)); assert(utf8);
    for (int i=0;i<argc;++i) {
        int bytes = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, wide[i], -1, NULL, 0, NULL, NULL); assert(bytes>0);
        utf8[i]=malloc((size_t)bytes); assert(utf8[i]);
        assert(WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, wide[i], -1, utf8[i], bytes, NULL, NULL));
    }
    LocalFree(wide); argv=utf8;
#endif
    assert(argc == 6);
    encore_plugin_diagnostic error = {0};
    encore_plugin_options options = encore_plugin_default_options();
    options.quiesce_timeout_ms = 25;
    encore_plugin_module *module = NULL;
    assert(encore_plugin_load(argv[1], &options, &module, &error) == ENCORE_PLUGIN_OK);
    encore_plugin_binding *binding = NULL;
    assert(encore_plugin_bind(module, "counter", "wrong", &binding, &error) == ENCORE_PLUGIN_ABI_MISMATCH);
    assert(binding == NULL);
    assert(encore_plugin_bind(module, "counter", "counter-contract-v1", &binding, &error) == ENCORE_PLUGIN_OK);
    assert(call(binding, 5) == 5);
    assert(encore_plugin_reload(module, argv[3], &error) == ENCORE_PLUGIN_ABI_MISMATCH);
    assert(call(binding, 1) == 6);
    assert(encore_plugin_reload(module, argv[5], &error) == ENCORE_PLUGIN_ABI_MISMATCH);
    assert(encore_plugin_reload(module, argv[4], &error) == ENCORE_PLUGIN_STATE_FAILED);
    assert(call(binding, 1) == 7);
    encore_plugin_call child_result;
    assert(encore_plugin_invoke(binding, 1, NULL, 0, &child_result) == ENCORE_PLUGIN_OK);
    encore_plugin_binding *child = NULL;
    assert(encore_plugin_take_resource(&child_result, child_result.value, &child) == ENCORE_PLUGIN_OK);
    /* A live call frame pins code and rejects reentrant reload. */
    assert(encore_plugin_reload(module, argv[2], &error) == ENCORE_PLUGIN_BUSY);
    encore_plugin_call_clear(&child_result);
    assert(encore_plugin_reload(module, argv[2], &error) == ENCORE_PLUGIN_OK);
    assert(encore_plugin_retired_count(module) == 1);
    assert(call(child, 1) == 8); /* Child keeps its original implementation. */
    encore_plugin_value old_resource;
    assert(encore_plugin_resource_value(child, &old_resource) == ENCORE_PLUGIN_OK);
    encore_plugin_call rejected;
    assert(encore_plugin_invoke(binding, 0, &old_resource, 1, &rejected) == ENCORE_PLUGIN_WRONG_GENERATION);
    encore_plugin_call_clear(&rejected);
    encore_plugin_binding_release(child);
    assert(encore_plugin_retired_count(module) == 0);
    assert(call(binding, 1) == 108);
    assert(encore_plugin_close(module, &error) == ENCORE_PLUGIN_BUSY);
    encore_plugin_binding_retain(binding);
    encore_plugin_binding_release(binding);
    assert(call(binding, 1) == 109);
    /* Retired generations are bounded and reclaimed as resources disappear. */
    encore_plugin_binding *held[3] = {0};
    for (size_t i = 0; i < 3; ++i) {
        encore_plugin_call forked;
        assert(encore_plugin_invoke(binding, 1, NULL, 0, &forked) == ENCORE_PLUGIN_OK);
        assert(encore_plugin_take_resource(&forked, forked.value, &held[i]) == ENCORE_PLUGIN_OK);
        encore_plugin_call_clear(&forked);
        encore_plugin_status expected = i == 2 ? ENCORE_PLUGIN_LIMIT : ENCORE_PLUGIN_OK;
        assert(encore_plugin_reload(module, argv[i % 2 + 1], &error) == expected);
    }
    assert(encore_plugin_retired_count(module) == 2);
    encore_plugin_binding_release(held[0]);
    assert(encore_plugin_retired_count(module) == 1);
    assert(encore_plugin_reload(module, argv[1], &error) == ENCORE_PLUGIN_OK);
    encore_plugin_binding_release(held[1]); encore_plugin_binding_release(held[2]);
    assert(encore_plugin_retired_count(module) == 0);
    /* Decoding guards reject malformed UTF-8 and cycles before invoking code. */
    const unsigned char invalid_utf8[] = {0xc0, 0x80};
    encore_plugin_value invalid = {.kind = ENCORE_PLUGIN_STRING, .data = invalid_utf8, .length = 2};
    encore_plugin_call invalid_call;
    assert(encore_plugin_invoke(binding, 0, &invalid, 1, &invalid_call) == ENCORE_PLUGIN_INVALID_VALUE);
    encore_plugin_call_clear(&invalid_call);
    invalid = (encore_plugin_value){.kind = ENCORE_PLUGIN_LIST, .data = &invalid, .length = 1};
    assert(encore_plugin_invoke(binding, 0, &invalid, 1, &invalid_call) == ENCORE_PLUGIN_LIMIT);
    encore_plugin_call_clear(&invalid_call);
    for (size_t i = 0; i < 50; ++i) assert(encore_plugin_reload(module, argv[i % 2 + 1], &error) == ENCORE_PLUGIN_OK);
    /* Reload drains admitted calls and rejects new admission during migration. */
    assert(encore_plugin_reload(module, argv[1], &error) == ENCORE_PLUGIN_OK);
    uint64_t before = call(binding,0); worker_binding = binding;
    test_thread workers[4];
    for(size_t i=0;i<4;++i) workers[i]=start_worker(increment_worker);
    while(atomic_load(&workers_started)<4) test_yield();
    for(size_t i=0;i<20;++i) assert(encore_plugin_reload(module,argv[i%2+1],&error)==ENCORE_PLUGIN_OK);
    for(size_t i=0;i<4;++i) join_worker(workers[i]);
    assert(encore_plugin_reload(module,argv[1],&error)==ENCORE_PLUGIN_OK);
    assert(call(binding,0)==before+1000);
    /* A live output frame in another thread times out without replacing roots. */
    atomic_store(&workers_started,0); test_thread held_thread=start_worker(hold_worker);
    while(!atomic_load(&workers_started)) test_yield();
    assert(encore_plugin_reload(module,argv[2],&error)==ENCORE_PLUGIN_BUSY);
    atomic_store(&release_held_call,true); join_worker(held_thread);
    assert(call(binding,0)==before+1000);
    encore_plugin_binding_release(binding);
    assert(encore_plugin_close(module, &error) == ENCORE_PLUGIN_OK);
    assert(encore_plugin_bind(module, "counter", "counter-contract-v1", &binding, &error) == ENCORE_PLUGIN_CLOSED);
    encore_plugin_module_release(module);
    /* A call frame is sufficient to keep both its module and binding alive. */
    assert(encore_plugin_load(argv[1], &options, &module, &error) == ENCORE_PLUGIN_OK);
    assert(encore_plugin_bind(module, "counter", "counter-contract-v1", &binding, &error) == ENCORE_PLUGIN_OK);
    encore_plugin_call last_owner;
    assert(encore_plugin_call_begin(binding, &last_owner) == ENCORE_PLUGIN_OK);
    encore_plugin_binding_release(binding);
    encore_plugin_module_release(module);
    encore_plugin_value final_argument = {.kind=ENCORE_PLUGIN_U64,.bits=9};
    assert(encore_plugin_call_dispatch(&last_owner, 0, &final_argument, 1) == ENCORE_PLUGIN_OK);
    assert(last_owner.value.kind == ENCORE_PLUGIN_U64 && last_owner.value.bits == 9);
    encore_plugin_call_clear(&last_owner);
    encore_plugin_call_clear(&last_owner); /* Clearing an empty frame is harmless. */
    puts("native plugin loading, ABI checks, state migration and rollback passed");
#ifdef _WIN32
    for(int i=0;i<argc;++i) free(utf8[i]); free(utf8);
#endif
    return 0;
}
