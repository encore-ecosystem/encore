/* Native module ownership is independent of every module's Encore heap. */
#ifndef _WIN32
#ifndef _POSIX_C_SOURCE
#define _POSIX_C_SOURCE 200809L
#endif
#endif
#include "plugin_runtime.h"
#include <assert.h>
#include <errno.h>
#include <inttypes.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef _WIN32
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
typedef CRITICAL_SECTION ep_mutex;
typedef CONDITION_VARIABLE ep_condition;
typedef HMODULE ep_library;
static void ep_mutex_init(ep_mutex *m) { InitializeCriticalSection(m); }
static void ep_mutex_drop(ep_mutex *m) { DeleteCriticalSection(m); }
static void ep_lock(ep_mutex *m) { EnterCriticalSection(m); }
static void ep_unlock(ep_mutex *m) { LeaveCriticalSection(m); }
static bool ep_trylock(ep_mutex *m) { return TryEnterCriticalSection(m) != 0; }
static void ep_condition_init(ep_condition *c) { InitializeConditionVariable(c); }
static void ep_condition_drop(ep_condition *c) { (void)c; }
static void ep_signal(ep_condition *c) { WakeAllConditionVariable(c); }
static bool ep_wait(ep_condition *c, ep_mutex *m, uint32_t ms) { return SleepConditionVariableCS(c, m, ms) != 0; }
static uint64_t ep_now(void) { return GetTickCount64(); }
static wchar_t *ep_wide(const char *text) {
    int length = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text, -1, NULL, 0);
    if (length <= 0 || (size_t)length > SIZE_MAX / sizeof(wchar_t)) return NULL;
    wchar_t *out = malloc((size_t)length * sizeof(*out));
    if (out != NULL && !MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text, -1, out, length)) { free(out); return NULL; }
    return out;
}
#else
#include <dlfcn.h>
#include <pthread.h>
#include <time.h>
#include <unistd.h>
typedef pthread_mutex_t ep_mutex;
typedef pthread_cond_t ep_condition;
typedef void *ep_library;
static void ep_mutex_init(ep_mutex *m) {
    pthread_mutexattr_t attr;
    pthread_mutexattr_init(&attr); pthread_mutexattr_settype(&attr, PTHREAD_MUTEX_RECURSIVE);
    pthread_mutex_init(m, &attr); pthread_mutexattr_destroy(&attr);
}
static void ep_mutex_drop(ep_mutex *m) { pthread_mutex_destroy(m); }
static void ep_lock(ep_mutex *m) { pthread_mutex_lock(m); }
static void ep_unlock(ep_mutex *m) { pthread_mutex_unlock(m); }
static bool ep_trylock(ep_mutex *m) { return pthread_mutex_trylock(m) == 0; }
static void ep_condition_init(ep_condition *c) { pthread_cond_init(c, NULL); }
static void ep_condition_drop(ep_condition *c) { pthread_cond_destroy(c); }
static void ep_signal(ep_condition *c) { pthread_cond_broadcast(c); }
static bool ep_wait(ep_condition *c, ep_mutex *m, uint32_t ms) {
    struct timespec until; clock_gettime(CLOCK_REALTIME, &until);
    until.tv_sec += (time_t)(ms / 1000); until.tv_nsec += (long)(ms % 1000) * 1000000;
    if (until.tv_nsec >= 1000000000) { ++until.tv_sec; until.tv_nsec -= 1000000000; }
    return pthread_cond_timedwait(c, m, &until) == 0;
}
static uint64_t ep_now(void) {
    struct timespec now; clock_gettime(CLOCK_MONOTONIC, &now);
    return (uint64_t)now.tv_sec * 1000 + (uint64_t)now.tv_nsec / 1000000;
}
#endif

static _Thread_local unsigned ep_call_depth;

struct encore_plugin_generation {
    encore_plugin_module *module;
    ep_library library;
    char *copy_path;
    const encore_plugin_descriptor *descriptor;
    size_t references;
    size_t active;
    ep_mutex execution;
    encore_plugin_generation *next;
};
struct encore_plugin_module {
    ep_mutex mutex;
    ep_mutex reload_mutex;
    ep_condition idle;
    size_t references;
    bool closed;
    bool quiescing;
    encore_plugin_options options;
    encore_plugin_generation *current;
    encore_plugin_generation *retired;
    encore_plugin_binding *bindings;
};
struct encore_plugin_binding {
    encore_plugin_module *module;
    encore_plugin_generation *generation;
    const encore_plugin_export *export;
    encore_plugin_object object;
    size_t references;
    bool resource;
    encore_plugin_binding *next;
};
struct encore_plugin_allocation {
    encore_plugin_allocation *next;
    max_align_t alignment;
    unsigned char data[];
};

struct encore_plugin_resource_lease {
    encore_plugin_binding *binding;
    encore_plugin_resource_lease *next;
};

static encore_plugin_status ep_error(encore_plugin_diagnostic *out,
    encore_plugin_status code, const char *message) {
    if (out != NULL) { out->code = code; snprintf(out->message, sizeof(out->message), "%s", message); }
    return code;
}
static void ep_plugin_error(encore_plugin_diagnostic *out, encore_plugin_status status,
    encore_plugin_error error, const char *fallback) {
    ep_error(out, status, fallback);
    if (out != NULL && error.message.data != NULL && error.message.length != 0) {
        size_t size = error.message.length;
        if (size >= sizeof(out->message)) size = sizeof(out->message) - 1;
        memcpy(out->message, error.message.data, size); out->message[size] = 0;
    }
}
encore_plugin_options encore_plugin_default_options(void) {
    return (encore_plugin_options){64 * 1024 * 1024, 128, 2, 5000};
}
static bool ep_name(const char *text) {
    if (text == NULL || text[0] == 0) return false;
    for (size_t i = 0; i < 4096; ++i) if (text[i] == 0) return true;
    return false;
}
static bool ep_interface_valid(const encore_plugin_interface *api) {
    if (api == NULL || api->size != sizeof(*api) || !ep_name(api->name) || !ep_name(api->fingerprint) ||
        api->method_count > 4096 || (api->method_count != 0 && api->methods == NULL)) return false;
    for (size_t i = 0; i < api->method_count; ++i) {
        const encore_plugin_method *method = &api->methods[i];
        if (!ep_name(method->name) || !ep_name(method->fingerprint) || method->invoke == NULL) return false;
        for (size_t j = 0; j < i; ++j) if (strcmp(method->name, api->methods[j].name) == 0) return false;
    }
    return true;
}
static bool ep_interfaces_match(const encore_plugin_interface *a, const encore_plugin_interface *b) {
    if (!ep_interface_valid(a) || !ep_interface_valid(b) || strcmp(a->name, b->name) ||
        strcmp(a->fingerprint, b->fingerprint) || a->method_count != b->method_count) return false;
    for (size_t i = 0; i < a->method_count; ++i)
        if (strcmp(a->methods[i].name, b->methods[i].name) || strcmp(a->methods[i].fingerprint, b->methods[i].fingerprint)) return false;
    return true;
}
static bool ep_descriptor_valid(const encore_plugin_descriptor *d) {
    if (d == NULL || d->magic != ENCORE_PLUGIN_MAGIC || d->abi != ENCORE_PLUGIN_ABI_V1 ||
        d->size != sizeof(*d) || d->pointer_bits != sizeof(void *) * 8 ||
        d->target_os == NULL || strcmp(d->target_os, ENCORE_PLUGIN_TARGET) ||
        !ep_name(d->project_name) || !ep_name(d->project_version) ||
        d->export_count == 0 || d->export_count > 1024 || d->exports == NULL) return false;
    for (size_t i = 0; i < d->export_count; ++i) {
        const encore_plugin_export *e = &d->exports[i];
        if (!ep_name(e->name) || !ep_interface_valid(e->interface) || e->create == NULL ||
            (e->flags & ~ENCORE_PLUGIN_STATELESS) != 0 ||
            (!(e->flags & ENCORE_PLUGIN_STATELESS) && (e->save == NULL || e->restore == NULL))) return false;
        for (size_t j = 0; j < i; ++j) if (strcmp(e->name, d->exports[j].name) == 0) return false;
    }
    return true;
}
static const encore_plugin_export *ep_export(const encore_plugin_descriptor *d, const char *name) {
    for (size_t i = 0; i < d->export_count; ++i) if (!strcmp(d->exports[i].name, name)) return &d->exports[i];
    return NULL;
}
static void ep_delete_copy(const char *path) {
    if (path == NULL) return;
#ifdef _WIN32
    wchar_t *wide = ep_wide(path); if (wide != NULL) { DeleteFileW(wide); free(wide); }
#else
    unlink(path);
#endif
}
static void ep_generation_free(encore_plugin_generation *g) {
    if (g == NULL) return;
    if (g->library != NULL) {
        if (g->descriptor != NULL && g->descriptor->deinitialize != NULL) {
            ++ep_call_depth; g->descriptor->deinitialize(); --ep_call_depth;
        }
#ifdef _WIN32
        FreeLibrary(g->library);
#else
        dlclose(g->library);
#endif
    }
    ep_delete_copy(g->copy_path); free(g->copy_path); ep_mutex_drop(&g->execution); free(g);
}
static encore_plugin_status ep_copy_load(encore_plugin_generation *g, const char *path,
    encore_plugin_diagnostic *error) {
#ifdef _WIN32
    wchar_t *source = ep_wide(path), directory[MAX_PATH + 1], temporary[MAX_PATH + 1];
    if (source == NULL || !GetTempPathW(MAX_PATH, directory) || !GetTempFileNameW(directory, L"enq", 0, temporary)) {
        free(source); return ep_error(error, ENCORE_PLUGIN_LOAD_FAILED, "cannot create plugin generation");
    }
    bool copied = CopyFileW(source, temporary, FALSE) != 0; free(source);
    if (!copied) { DeleteFileW(temporary); return ep_error(error, ENCORE_PLUGIN_LOAD_FAILED, "cannot copy plugin library"); }
    int bytes = WideCharToMultiByte(CP_UTF8, 0, temporary, -1, NULL, 0, NULL, NULL);
    g->copy_path = bytes > 0 ? malloc((size_t)bytes) : NULL;
    if (g->copy_path == NULL) { DeleteFileW(temporary); return ep_error(error, ENCORE_PLUGIN_LIMIT, "cannot store generation path"); }
    WideCharToMultiByte(CP_UTF8, 0, temporary, -1, g->copy_path, bytes, NULL, NULL);
    g->library = LoadLibraryExW(temporary, NULL, LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
    if (g->library == NULL) return ep_error(error, ENCORE_PLUGIN_LOAD_FAILED, "cannot load plugin library or system dependencies");
    encore_plugin_entry_fn entry = (encore_plugin_entry_fn)(void *)GetProcAddress(g->library, "encore_plugin_entry_v1");
#else
    const char *directory = getenv("TMPDIR"); if (directory == NULL || directory[0] != '/') directory = "/tmp";
    size_t length = strlen(directory);
    if (length > SIZE_MAX - 32) return ep_error(error, ENCORE_PLUGIN_LOAD_FAILED, "plugin temporary path is too long");
    g->copy_path = malloc(length + 32);
    if (g->copy_path == NULL) return ep_error(error, ENCORE_PLUGIN_LIMIT, "cannot store generation path");
    snprintf(g->copy_path, length + 32, "%s/encore-plugin-XXXXXX", directory);
    int fd = mkstemp(g->copy_path);
    if (fd < 0) return ep_error(error, ENCORE_PLUGIN_LOAD_FAILED, "cannot create plugin generation");
    FILE *input = fopen(path, "rb"), *output = fdopen(fd, "wb");
    bool copied = input != NULL && output != NULL;
    if (output == NULL) close(fd);
    if (copied) {
        unsigned char buffer[16384]; size_t count;
        while ((count = fread(buffer, 1, sizeof(buffer), input)) != 0)
            if (fwrite(buffer, 1, count, output) != count) { copied = false; break; }
        if (ferror(input)) copied = false;
    }
    if (input != NULL) fclose(input);
    if (output != NULL && fclose(output) != 0) copied = false;
    if (!copied) return ep_error(error, ENCORE_PLUGIN_LOAD_FAILED, "cannot copy plugin library");
    g->library = dlopen(g->copy_path, RTLD_NOW | RTLD_LOCAL);
    if (g->library == NULL) return ep_error(error, ENCORE_PLUGIN_LOAD_FAILED, dlerror());
    encore_plugin_entry_fn entry = NULL;
    void *symbol = dlsym(g->library, "encore_plugin_entry_v1");
    _Static_assert(sizeof(entry) == sizeof(symbol), "native function pointers must fit dlsym");
    memcpy(&entry, &symbol, sizeof(entry));
#endif
    if (entry == NULL) return ep_error(error, ENCORE_PLUGIN_ABI_MISMATCH, "missing encore_plugin_entry_v1");
    ++ep_call_depth; const encore_plugin_descriptor *descriptor = entry(); --ep_call_depth;
    if (!ep_descriptor_valid(descriptor)) return ep_error(error, ENCORE_PLUGIN_ABI_MISMATCH, "incompatible plugin ABI or malformed descriptor");
    g->descriptor = descriptor;
    return ENCORE_PLUGIN_OK;
}
static encore_plugin_generation *ep_generation_load(encore_plugin_module *module,
    const char *path, encore_plugin_diagnostic *error) {
    encore_plugin_generation *g = calloc(1, sizeof(*g));
    if (g == NULL) { ep_error(error, ENCORE_PLUGIN_LIMIT, "cannot allocate plugin generation"); return NULL; }
    ep_mutex_init(&g->execution); g->module = module; g->references = 1;
    if (ep_copy_load(g, path, error) != ENCORE_PLUGIN_OK) { ep_generation_free(g); return NULL; }
    return g;
}
static void ep_generation_retain(encore_plugin_generation *g) {
    ep_lock(&g->module->mutex); ++g->references; ep_unlock(&g->module->mutex);
}
static void ep_generation_release(encore_plugin_generation *g) {
    encore_plugin_module *module = g->module;
    ep_lock(&module->mutex);
    bool last = --g->references == 0;
    if (last) {
        encore_plugin_generation **link = &module->retired;
        while (*link != NULL && *link != g) link = &(*link)->next;
        if (*link == g) *link = g->next;
    }
    ep_unlock(&module->mutex);
    if (last) ep_generation_free(g);
}
void encore_plugin_module_retain(encore_plugin_module *module) {
    if (module != NULL) { ep_lock(&module->mutex); ++module->references; ep_unlock(&module->mutex); }
}
void encore_plugin_module_release(encore_plugin_module *module) {
    if (module == NULL) return;
    ep_lock(&module->mutex); bool last = --module->references == 0; ep_unlock(&module->mutex);
    if (!last) return;
    assert(module->bindings == NULL && module->retired == NULL);
    if (module->current != NULL) ep_generation_release(module->current);
    ep_condition_drop(&module->idle); ep_mutex_drop(&module->reload_mutex); ep_mutex_drop(&module->mutex); free(module);
}
encore_plugin_status encore_plugin_load(const char *path, const encore_plugin_options *options,
    encore_plugin_module **out, encore_plugin_diagnostic *error) {
    if (out == NULL) return ep_error(error, ENCORE_PLUGIN_INVALID_VALUE, "missing module output");
    *out = NULL;
    if (path == NULL || path[0] == 0) return ep_error(error, ENCORE_PLUGIN_LOAD_FAILED, "missing plugin path");
    encore_plugin_module *module = calloc(1, sizeof(*module));
    if (module == NULL) return ep_error(error, ENCORE_PLUGIN_LIMIT, "cannot allocate plugin module");
    ep_mutex_init(&module->mutex); ep_mutex_init(&module->reload_mutex); ep_condition_init(&module->idle);
    module->references = 1; module->options = options == NULL ? encore_plugin_default_options() : *options;
    if (module->options.max_transfer_bytes == 0 || module->options.max_value_depth == 0 || module->options.max_value_depth > 256) {
        encore_plugin_module_release(module); return ep_error(error, ENCORE_PLUGIN_INVALID_VALUE, "invalid plugin limits");
    }
    module->current = ep_generation_load(module, path, error);
    if (module->current == NULL) { encore_plugin_module_release(module); return error == NULL ? ENCORE_PLUGIN_LOAD_FAILED : error->code; }
    *out = module; return ep_error(error, ENCORE_PLUGIN_OK, "");
}
static bool ep_object_valid(encore_plugin_object object, const encore_plugin_interface *api) {
    return object.data != NULL && object.destroy != NULL && ep_interfaces_match(object.interface, api);
}
static void ep_destroy(encore_plugin_generation *generation, encore_plugin_object object) {
    if (object.data == NULL || object.destroy == NULL) return;
    ep_lock(&generation->execution); ++ep_call_depth; object.destroy(object.data); --ep_call_depth; ep_unlock(&generation->execution);
}
void encore_plugin_binding_retain(encore_plugin_binding *binding) {
    if (binding != NULL) { ep_lock(&binding->module->mutex); ++binding->references; ep_unlock(&binding->module->mutex); }
}
void encore_plugin_binding_release(encore_plugin_binding *binding) {
    if (binding == NULL) return;
    encore_plugin_module *module = binding->module;
    ep_lock(&module->mutex); bool last = --binding->references == 0;
    if (last) {
        encore_plugin_binding **link = &module->bindings;
        while (*link != NULL && *link != binding) link = &(*link)->next;
        assert(*link == binding); *link = binding->next;
    }
    ep_unlock(&module->mutex);
    if (last) {
        ep_destroy(binding->generation, binding->object); ep_generation_release(binding->generation);
        free(binding); encore_plugin_module_release(module);
    }
}
static void ep_finish_active(encore_plugin_generation *generation) {
    encore_plugin_module *module = generation->module;
    ep_lock(&module->mutex); assert(generation->active != 0); --generation->active; ep_signal(&module->idle); ep_unlock(&module->mutex);
}
encore_plugin_status encore_plugin_bind(encore_plugin_module *module, const char *name,
    const char *fingerprint, encore_plugin_binding **out, encore_plugin_diagnostic *error) {
    if (out == NULL || module == NULL || name == NULL || fingerprint == NULL)
        return ep_error(error, ENCORE_PLUGIN_INVALID_VALUE, "invalid binding arguments");
    *out = NULL;
    ep_lock(&module->mutex);
    if (module->closed || module->quiescing) {
        encore_plugin_status status = module->closed ? ENCORE_PLUGIN_CLOSED : ENCORE_PLUGIN_BUSY;
        ep_unlock(&module->mutex); return ep_error(error, status, "module is closed or reloading");
    }
    encore_plugin_generation *g = module->current;
    const encore_plugin_export *e = ep_export(g->descriptor, name);
    if (e == NULL || strcmp(e->interface->fingerprint, fingerprint)) {
        ep_unlock(&module->mutex);
        return ep_error(error, e == NULL ? ENCORE_PLUGIN_MISSING_EXPORT : ENCORE_PLUGIN_ABI_MISMATCH, "missing or incompatible plugin interface");
    }
    ep_generation_retain(g); ++g->active; ++module->references; ep_unlock(&module->mutex);
    encore_plugin_object object = {0}; encore_plugin_error detail = {0};
    ep_lock(&g->execution); ++ep_call_depth; encore_plugin_status status = e->create(e->context, &object, &detail); --ep_call_depth;
    if (status == ENCORE_PLUGIN_OK && !ep_object_valid(object, e->interface)) status = ENCORE_PLUGIN_ABI_MISMATCH;
    if (status != ENCORE_PLUGIN_OK) ep_plugin_error(error, status, detail, "plugin factory failed");
    ep_unlock(&g->execution);
    encore_plugin_binding *binding = status == ENCORE_PLUGIN_OK ? calloc(1, sizeof(*binding)) : NULL;
    if (status == ENCORE_PLUGIN_OK && binding == NULL) status = ep_error(error, ENCORE_PLUGIN_LIMIT, "cannot allocate binding");
    ep_lock(&module->mutex);
    if (status == ENCORE_PLUGIN_OK && (module->closed || module->quiescing)) status = ep_error(error, ENCORE_PLUGIN_BUSY, "module started reloading");
    if (status == ENCORE_PLUGIN_OK) {
        *binding = (encore_plugin_binding){module, g, e, object, 1, false, module->bindings};
        module->bindings = binding; *out = binding;
    }
    ep_unlock(&module->mutex);
    if (status != ENCORE_PLUGIN_OK) { free(binding); ep_destroy(g, object); }
    ep_finish_active(g);
    if (status != ENCORE_PLUGIN_OK) { ep_generation_release(g); encore_plugin_module_release(module); }
    return status;
}

static void *ep_allocate(void *context, size_t bytes, size_t alignment) {
    encore_plugin_call *call = context;
    size_t limit = call->generation->module->options.max_transfer_bytes;
    if (alignment == 0 || alignment > alignof(max_align_t) || (alignment & (alignment - 1)) ||
        bytes > limit || call->bytes > limit - bytes) return NULL;
    size_t aligned = (call->inline_used + alignment - 1) & ~(alignment - 1);
    if (bytes <= sizeof(call->inline_data) && aligned <= sizeof(call->inline_data) - bytes) {
        void *out = call->inline_data + aligned;
        call->inline_used = aligned + bytes; call->bytes += bytes; return out;
    }
    if (bytes > SIZE_MAX - sizeof(encore_plugin_allocation)) return NULL;
    encore_plugin_allocation *allocation = malloc(sizeof(*allocation) + bytes);
    if (allocation == NULL) return NULL;
    allocation->next = call->allocations; call->allocations = allocation; call->bytes += bytes;
    return allocation->data;
}
static encore_plugin_status ep_adopt_resource(void *context, encore_plugin_object object,
    encore_plugin_value *out) {
    encore_plugin_call *call = context;
    encore_plugin_generation *generation = call->generation;
    encore_plugin_module *module = generation->module;
    if (out == NULL || !ep_object_valid(object, object.interface)) return ENCORE_PLUGIN_INVALID_VALUE;
    encore_plugin_resource_lease *lease = ep_allocate(call, sizeof(*lease), alignof(encore_plugin_resource_lease));
    if (lease == NULL) return ENCORE_PLUGIN_LIMIT;
    encore_plugin_binding *binding = calloc(1, sizeof(*binding));
    if (binding == NULL) return ENCORE_PLUGIN_LIMIT;
    ep_lock(&module->mutex);
    *binding = (encore_plugin_binding){module, generation, NULL, object, 1, true, module->bindings};
    module->bindings = binding; ++module->references; ++generation->references;
    ep_unlock(&module->mutex);
    *lease = (encore_plugin_resource_lease){binding, call->resources}; call->resources = lease;
    *out = (encore_plugin_value){.kind = ENCORE_PLUGIN_RESOURCE, .auxiliary = 1,
        .bits = (uint64_t)(uintptr_t)generation, .data = binding};
    return ENCORE_PLUGIN_OK;
}
encore_plugin_status encore_plugin_take_resource(encore_plugin_call *call,
    encore_plugin_value value, encore_plugin_binding **out) {
    if (out == NULL) return ENCORE_PLUGIN_INVALID_VALUE;
    *out = NULL;
    if (call == NULL || call->generation == NULL || value.kind != ENCORE_PLUGIN_RESOURCE || value.auxiliary != 1)
        return ENCORE_PLUGIN_INVALID_VALUE;
    for (encore_plugin_resource_lease *lease = call->resources; lease != NULL; lease = lease->next) {
        if (value.data == lease->binding && value.bits == (uint64_t)(uintptr_t)call->generation) {
            encore_plugin_binding_retain(lease->binding); *out = lease->binding; return ENCORE_PLUGIN_OK;
        }
    }
    return ENCORE_PLUGIN_INVALID_VALUE;
}
encore_plugin_status encore_plugin_resource_value(encore_plugin_binding *binding, encore_plugin_value *out) {
    if (binding == NULL || out == NULL || !binding->resource) return ENCORE_PLUGIN_INVALID_VALUE;
    *out = (encore_plugin_value){.kind = ENCORE_PLUGIN_RESOURCE,
        .bits = (uint64_t)(uintptr_t)binding->generation, .data = &binding->object};
    return ENCORE_PLUGIN_OK;
}
static bool ep_utf8(const uint8_t *p, size_t n) {
    for (size_t i = 0; i < n;) {
        uint32_t value = p[i++];
        if (value < 0x80) continue;
        size_t count; uint32_t minimum;
        if (value >= 0xc2 && value <= 0xdf) { count = 1; minimum = 0x80; value &= 0x1f; }
        else if (value >= 0xe0 && value <= 0xef) { count = 2; minimum = 0x800; value &= 0x0f; }
        else if (value >= 0xf0 && value <= 0xf4) { count = 3; minimum = 0x10000; value &= 7; }
        else return false;
        if (count > n - i) return false;
        for (size_t j = 0; j < count; ++j) {
            if ((p[i] & 0xc0) != 0x80) return false;
            value = value * 64 + (p[i++] & 0x3f);
        }
        if (value < minimum || value > 0x10ffff || (value >= 0xd800 && value <= 0xdfff)) return false;
    }
    return true;
}
static encore_plugin_status ep_validate_value(encore_plugin_value value,
    encore_plugin_generation *generation, size_t *bytes, uint32_t depth) {
    const encore_plugin_options *options = &generation->module->options;
    if (depth > options->max_value_depth) return ENCORE_PLUGIN_LIMIT;
    if (value.kind == ENCORE_PLUGIN_UNIT || value.kind == ENCORE_PLUGIN_U64 ||
        value.kind == ENCORE_PLUGIN_I64 || value.kind == ENCORE_PLUGIN_F64) return ENCORE_PLUGIN_OK;
    if (value.kind == ENCORE_PLUGIN_BOOL) return value.bits <= 1 ? ENCORE_PLUGIN_OK : ENCORE_PLUGIN_INVALID_VALUE;
    if (value.kind == ENCORE_PLUGIN_RESOURCE) {
        if (value.bits != (uint64_t)(uintptr_t)generation) return ENCORE_PLUGIN_WRONG_GENERATION;
        return value.data != NULL ? ENCORE_PLUGIN_OK : ENCORE_PLUGIN_INVALID_VALUE;
    }
    if (value.kind == ENCORE_PLUGIN_STRING || value.kind == ENCORE_PLUGIN_BYTES) {
        if (value.length != 0 && value.data == NULL) return ENCORE_PLUGIN_INVALID_VALUE;
        if (value.length > options->max_transfer_bytes || *bytes > options->max_transfer_bytes - value.length) return ENCORE_PLUGIN_LIMIT;
        *bytes += value.length;
        return value.kind == ENCORE_PLUGIN_STRING && !ep_utf8(value.data, value.length) ? ENCORE_PLUGIN_INVALID_VALUE : ENCORE_PLUGIN_OK;
    }
    if (value.kind == ENCORE_PLUGIN_LIST || value.kind == ENCORE_PLUGIN_RECORD || value.kind == ENCORE_PLUGIN_VARIANT) {
        if (value.length != 0 && value.data == NULL) return ENCORE_PLUGIN_INVALID_VALUE;
        if (value.length > options->max_transfer_bytes / sizeof(encore_plugin_value)) return ENCORE_PLUGIN_LIMIT;
        size_t size = value.length * sizeof(encore_plugin_value);
        if (*bytes > options->max_transfer_bytes - size) return ENCORE_PLUGIN_LIMIT;
        *bytes += size;
        const encore_plugin_value *items = value.data;
        for (size_t i = 0; i < value.length; ++i) {
            encore_plugin_status status = ep_validate_value(items[i], generation, bytes, depth + 1);
            if (status != ENCORE_PLUGIN_OK) return status;
        }
        return ENCORE_PLUGIN_OK;
    }
    return ENCORE_PLUGIN_INVALID_VALUE;
}
void encore_plugin_call_clear(encore_plugin_call *call) {
    if (call == NULL) return;
    for (encore_plugin_resource_lease *lease = call->resources; lease != NULL; lease = lease->next)
        encore_plugin_binding_release(lease->binding);
    encore_plugin_allocation *allocation = call->allocations;
    while (allocation != NULL) { encore_plugin_allocation *next = allocation->next; free(allocation); allocation = next; }
    if (call->generation != NULL) {
        encore_plugin_generation *generation = call->generation;
        encore_plugin_binding *binding = call->binding;
        assert(ep_call_depth != 0); --ep_call_depth;
        ep_finish_active(generation);
        /* The binding keeps the module alive while the call releases its
         * generation. Releasing the last binding first can free that module. */
        ep_generation_release(generation);
        encore_plugin_binding_release(binding);
    }
    memset(call, 0, sizeof(*call));
}
encore_plugin_status encore_plugin_call_begin(encore_plugin_binding *binding, encore_plugin_call *call) {
    if (call == NULL) return ENCORE_PLUGIN_INVALID_VALUE;
    memset(call, 0, sizeof(*call));
    if (binding == NULL) return ep_error(&call->error, ENCORE_PLUGIN_INVALID_VALUE, "invalid call arguments");
    encore_plugin_module *module = binding->module;
    ep_lock(&module->mutex);
    encore_plugin_generation *generation = binding->generation;
    if (module->quiescing && generation == module->current) {
        ep_unlock(&module->mutex); return ep_error(&call->error, ENCORE_PLUGIN_BUSY, "plugin is reloading");
    }
    ++generation->active; ++generation->references; ++binding->references;
    ep_unlock(&module->mutex);
    call->binding = binding; call->generation = generation; ++ep_call_depth;
    call->arena = (encore_plugin_arena){call, ep_allocate, ep_adopt_resource, module->options.max_value_depth};
    return ENCORE_PLUGIN_OK;
}
encore_plugin_status encore_plugin_call_dispatch(encore_plugin_call *call, size_t method,
    const encore_plugin_value *arguments, size_t count) {
    if (call == NULL || call->binding == NULL || call->generation == NULL)
        return ENCORE_PLUGIN_INVALID_VALUE;
    encore_plugin_binding *binding = call->binding;
    encore_plugin_generation *generation = call->generation;
    encore_plugin_module *module = binding->module;
    encore_plugin_object object = binding->object;
    if ((count != 0 && arguments == NULL))
        return ep_error(&call->error, ENCORE_PLUGIN_INVALID_VALUE, "missing plugin arguments");
    if (method >= object.interface->method_count)
        return ep_error(&call->error, ENCORE_PLUGIN_MISSING_EXPORT, "unknown plugin method");
    size_t bytes = 0;
    if (count > module->options.max_transfer_bytes / sizeof(encore_plugin_value))
        return ep_error(&call->error, ENCORE_PLUGIN_LIMIT, "too many plugin arguments");
    bytes = count * sizeof(encore_plugin_value);
    for (size_t i = 0; i < count; ++i) {
        encore_plugin_status status = ep_validate_value(arguments[i], generation, &bytes, 0);
        if (status != ENCORE_PLUGIN_OK) return ep_error(&call->error, status, "invalid plugin argument");
    }
    encore_plugin_error detail = {0};
    ep_lock(&generation->execution);
    call->encoding_result = true;
    encore_plugin_status status = object.interface->methods[method].invoke(object.interface->methods[method].context, object.data,
        arguments, count, &call->arena, &call->value, &detail);
    call->encoding_result = false;
    if (status == ENCORE_PLUGIN_OK) {
        bytes = 0; status = ep_validate_value(call->value, generation, &bytes, 0);
        if (status != ENCORE_PLUGIN_OK) ep_error(&call->error, status, "invalid plugin result");
    } else ep_plugin_error(&call->error, status, detail, "plugin method failed");
    ep_unlock(&generation->execution);
    return status;
}
encore_plugin_status encore_plugin_invoke(encore_plugin_binding *binding, size_t method,
    const encore_plugin_value *arguments, size_t count, encore_plugin_call *call) {
    encore_plugin_status status = encore_plugin_call_begin(binding, call);
    return status == ENCORE_PLUGIN_OK ? encore_plugin_call_dispatch(call, method, arguments, count) : status;
}
size_t encore_plugin_retired_count(encore_plugin_module *module) {
    if (module == NULL) return 0;
    ep_lock(&module->mutex); size_t count = 0;
    for (encore_plugin_generation *g = module->retired; g != NULL; g = g->next) ++count;
    ep_unlock(&module->mutex); return count;
}
encore_plugin_status encore_plugin_close(encore_plugin_module *module, encore_plugin_diagnostic *error) {
    if (module == NULL) return ep_error(error, ENCORE_PLUGIN_INVALID_VALUE, "missing plugin module");
    ep_lock(&module->mutex);
    if (module->closed) { ep_unlock(&module->mutex); return ENCORE_PLUGIN_OK; }
    if (module->quiescing || module->bindings != NULL || module->current->active != 0) {
        ep_unlock(&module->mutex); return ep_error(error, ENCORE_PLUGIN_BUSY, "plugin has live bindings, resources or calls");
    }
    module->closed = true; encore_plugin_generation *g = module->current; module->current = NULL;
    ep_unlock(&module->mutex); ep_generation_release(g); return ep_error(error, ENCORE_PLUGIN_OK, "");
}

typedef struct ep_migration {
    encore_plugin_binding *binding;
    encore_plugin_generation *old_generation;
    encore_plugin_object old_object;
    encore_plugin_object new_object;
    const encore_plugin_export *new_export;
} ep_migration;

encore_plugin_status encore_plugin_reload(encore_plugin_module *module, const char *path,
    encore_plugin_diagnostic *error) {
    if (module == NULL || path == NULL) return ep_error(error, ENCORE_PLUGIN_INVALID_VALUE, "invalid reload arguments");
    if (ep_call_depth != 0 || !ep_trylock(&module->reload_mutex))
        return ep_error(error, ENCORE_PLUGIN_BUSY, "reload from an active call or concurrent reload");
    encore_plugin_generation *candidate = ep_generation_load(module, path, error);
    if (candidate == NULL) { ep_unlock(&module->reload_mutex); return error == NULL ? ENCORE_PLUGIN_LOAD_FAILED : error->code; }
    encore_plugin_status status = ENCORE_PLUGIN_OK;
    ep_migration *migrations = NULL; size_t count = 0, used = 0;
    encore_plugin_generation *old = NULL;
    ep_lock(&module->mutex);
    if (module->closed || module->quiescing) status = ep_error(error, module->closed ? ENCORE_PLUGIN_CLOSED : ENCORE_PLUGIN_BUSY, "plugin is closed or reloading");
    if (status == ENCORE_PLUGIN_OK) {
        old = module->current;
        size_t retired = 0; bool resources = false;
        for (encore_plugin_generation *g = module->retired; g != NULL; g = g->next) ++retired;
        for (encore_plugin_binding *b = module->bindings; b != NULL; b = b->next) {
            if (b->resource) { if (b->generation == old) resources = true; }
            else ++count;
        }
        if (resources && retired >= module->options.max_retired_generations)
            status = ep_error(error, ENCORE_PLUGIN_LIMIT, "retired plugin generation limit reached");
    }
    if (status == ENCORE_PLUGIN_OK && count != 0) {
        if (count > SIZE_MAX / sizeof(*migrations) || (migrations = calloc(count, sizeof(*migrations))) == NULL)
            status = ep_error(error, ENCORE_PLUGIN_LIMIT, "cannot allocate migration plan");
    }
    if (status == ENCORE_PLUGIN_OK) {
        module->quiescing = true;
        uint64_t start = ep_now();
        while (old->active != 0) {
            uint64_t elapsed = ep_now() - start;
            if (elapsed >= module->options.quiesce_timeout_ms) {
                status = ep_error(error, ENCORE_PLUGIN_BUSY, "timed out waiting for active plugin calls"); break;
            }
            ep_wait(&module->idle, &module->mutex, module->options.quiesce_timeout_ms - (uint32_t)elapsed);
        }
    }
    if (status == ENCORE_PLUGIN_OK) {
        /* Bindings may disappear while the condition wait releases the mutex.
         * No new roots may appear after quiescing. Retain every migration root. */
        for (encore_plugin_binding *b = module->bindings; b != NULL; b = b->next) {
            if (b->resource) continue;
            const encore_plugin_export *next = ep_export(candidate->descriptor, b->export->name);
            if (next == NULL || !ep_interfaces_match(b->object.interface, next->interface) ||
                ((b->export->flags ^ next->flags) & ENCORE_PLUGIN_STATELESS)) {
                status = ep_error(error, ENCORE_PLUGIN_ABI_MISMATCH, "reload changes a bound interface or state policy"); break;
            }
            ++b->references;
            migrations[used++] = (ep_migration){b, old, b->object, {0}, next};
        }
    }
    ep_unlock(&module->mutex);
    if (status == ENCORE_PLUGIN_OK) {
        for (size_t i = 0; i < used; ++i) {
            ep_migration *m = &migrations[i]; encore_plugin_error detail = {0};
            ++ep_call_depth;
            if (m->binding->export->flags & ENCORE_PLUGIN_STATELESS) {
                status = m->new_export->create(m->new_export->context, &m->new_object, &detail);
            } else {
                encore_plugin_call snapshot;
                memset(&snapshot, 0, sizeof(snapshot)); snapshot.generation = old;
                snapshot.arena = (encore_plugin_arena){&snapshot, ep_allocate, NULL, module->options.max_value_depth};
                encore_plugin_snapshot state = {0};
                ep_lock(&old->execution);
                status = m->binding->export->save(m->binding->export->context, m->old_object.data, &snapshot.arena, &state, &detail);
                if (status != ENCORE_PLUGIN_OK) ep_plugin_error(error, status, detail, "cannot save plugin state");
                ep_unlock(&old->execution);
                if (status == ENCORE_PLUGIN_OK && (state.data.length > module->options.max_transfer_bytes ||
                    (state.data.length != 0 && state.data.data == NULL))) status = ep_error(error, ENCORE_PLUGIN_LIMIT, "invalid or oversized plugin snapshot");
                if (status == ENCORE_PLUGIN_OK) {
                    status = m->new_export->restore(m->new_export->context, state, &m->new_object, &detail);
                    if (status != ENCORE_PLUGIN_OK) ep_plugin_error(error, status, detail, "cannot restore plugin state");
                }
                /* This is a migration-only arena, not an active invocation. */
                snapshot.generation = NULL; encore_plugin_call_clear(&snapshot);
            }
            --ep_call_depth;
            if (status == ENCORE_PLUGIN_OK && !ep_object_valid(m->new_object, m->new_export->interface))
                status = ep_error(error, ENCORE_PLUGIN_ABI_MISMATCH, "restore returned an incompatible object");
            if (status != ENCORE_PLUGIN_OK) break;
        }
    }
    ep_lock(&module->mutex);
    if (status == ENCORE_PLUGIN_OK) {
        module->current = candidate;
        for (size_t i = 0; i < used; ++i) {
            encore_plugin_binding *b = migrations[i].binding;
            b->generation = candidate; b->export = migrations[i].new_export; b->object = migrations[i].new_object;
            ++candidate->references;
        }
        old->next = module->retired; module->retired = old;
    }
    module->quiescing = false; ep_signal(&module->idle); ep_unlock(&module->mutex);
    for (size_t i = 0; i < used; ++i) {
        ep_migration *m = &migrations[i];
        if (status == ENCORE_PLUGIN_OK) { ep_destroy(old, m->old_object); ep_generation_release(old); }
        else ep_destroy(candidate, m->new_object);
        encore_plugin_binding_release(m->binding);
    }
    free(migrations);
    if (status == ENCORE_PLUGIN_OK) ep_generation_release(old);
    else ep_generation_release(candidate);
    ep_unlock(&module->reload_mutex);
    return status;
}
