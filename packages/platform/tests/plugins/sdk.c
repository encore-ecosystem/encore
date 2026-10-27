/* Exercise the real SDK bridge, including concurrent lazy adapter registration. */
#include "../../runtime.c"
#include <assert.h>
extern void encore_str_drop(encore_str);
#ifdef _WIN32
static DWORD WINAPI resource_worker(void *unused);
#else
static void *resource_worker(void *unused);
#endif
static atomic_uint initializations, destructions;
static encore_str resource_key;
static void drop_payload(uintptr_t payload) {
    free((void *)payload);
    atomic_fetch_add(&destructions, 1);
}
static uint32_t read_payload(uintptr_t payload, uintptr_t args, size_t count,
    uintptr_t arena, uintptr_t output, uintptr_t error) {
    (void)args; (void)arena; (void)error;
    assert(count == 0);
    *(encore_plugin_value *)output = (encore_plugin_value){.kind=ENCORE_PLUGIN_U64, .bits=*(uint64_t *)payload};
    return ENCORE_PLUGIN_OK;
}
static uintptr_t initialize_adapter(uintptr_t descriptor) {
    assert(atomic_fetch_add(&initializations, 1) == 0);
    ep_sdk_drop_fn drop = drop_payload;
    ep_sdk_invoke_fn invoke = read_payload;
    uintptr_t drop_address, invoke_address;
    memcpy(&drop_address, &drop, sizeof(drop_address));
    memcpy(&invoke_address, &invoke, sizeof(invoke_address));
    encore_str contract = encore_from_cstr_copy("sdk-resource-v1");
    encore_str name = encore_from_cstr_copy("value");
    uintptr_t type = encore_plugin_descriptor_resource(descriptor, resource_key, contract, contract, 1, drop_address);
    assert(type && encore_plugin_descriptor_resource_method(type, 0, name, contract, invoke_address));
    assert(encore_plugin_descriptor_resource_ready(type));
    encore_str_drop(name); encore_str_drop(contract);
    return type;
}
#ifdef _WIN32
static DWORD WINAPI resource_worker(void *unused) {
#else
static void *resource_worker(void *unused) {
#endif
    (void)unused;
    uintptr_t (*initialize)(uintptr_t) = initialize_adapter;
    uintptr_t address;
    memcpy(&address, &initialize, sizeof(address));
    for (unsigned i = 0; i < 250; ++i) {
        uint64_t *payload = malloc(sizeof(*payload)); assert(payload); *payload = 42;
        uintptr_t resource = encore_plugin_native_resource_registered((uintptr_t)payload, resource_key, address);
        assert(resource);
        encore_plugin_handle_retain(resource);
        encore_plugin_handle_release(resource);
        alignas(max_align_t) unsigned char storage[2048];
        uintptr_t frame = encore_plugin_frame_begin((uintptr_t)storage, sizeof(storage), resource); assert(frame);
        uintptr_t args = encore_plugin_generated_arguments(0, 0, encore_plugin_frame_arena(frame)); assert(args);
        assert(encore_plugin_frame_dispatch(frame, 0, args) == ENCORE_PLUGIN_OK);
        const encore_plugin_value *result = (const void *)encore_plugin_frame_output(frame);
        assert(result->kind == ENCORE_PLUGIN_U64 && result->bits == 42);
        encore_plugin_frame_clear(frame);
        encore_plugin_handle_release(resource);
    }
    return 0;
}
int main(void) {
    encore_str name = encore_from_cstr_copy("sdk-test");
    encore_str version = encore_from_cstr_copy("1.0.0");
    uintptr_t descriptor = encore_plugin_descriptor_new(name, version, 0); assert(descriptor);
    assert(encore_plugin_descriptor_commit(descriptor));
    encore_str_drop(name); encore_str_drop(version);
    resource_key = encore_from_cstr_copy("sdk-resource-v1|Counter");
    enum { THREADS = 8 };
#ifdef _WIN32
    HANDLE threads[THREADS];
    for (unsigned i = 0; i < THREADS; ++i) { threads[i] = CreateThread(NULL, 0, resource_worker, NULL, 0, NULL); assert(threads[i]); }
    for (unsigned i = 0; i < THREADS; ++i) { assert(WaitForSingleObject(threads[i], INFINITE) == WAIT_OBJECT_0); assert(CloseHandle(threads[i])); }
#else
    pthread_t threads[THREADS];
    for (unsigned i = 0; i < THREADS; ++i) assert(pthread_create(&threads[i], NULL, resource_worker, NULL) == 0);
    for (unsigned i = 0; i < THREADS; ++i) assert(pthread_join(threads[i], NULL) == 0);
#endif
    assert(atomic_load(&initializations) == 1 && atomic_load(&destructions) == THREADS * 250);
    encore_str_drop(resource_key);
    ep_sdk_descriptor_deinitialize();
    assert(ep_sdk_resources == NULL && atomic_load(&ep_sdk_descriptor) == NULL);
    ep_sdk_descriptor_deinitialize();
    puts("SDK registration, concurrent calls and exact payload cleanup passed");
    return 0;
}
