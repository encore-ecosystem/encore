#ifndef ENCORE_PLUGIN_SDK_H
#define ENCORE_PLUGIN_SDK_H
/* Internal, module-local Encore adapters. Only plugin_abi.h is public ABI. */
#include "plugin_runtime.c"

typedef struct ep_sdk_handle {
    _Atomic size_t references;
    unsigned kind;
    union { encore_plugin_module *module; encore_plugin_binding *binding; } value;
} ep_sdk_handle;
static _Thread_local encore_plugin_diagnostic ep_sdk_error;
static uintptr_t ep_sdk_wrap(unsigned kind, void *value) {
    ep_sdk_handle *handle = calloc(1, sizeof(*handle));
    if (handle == NULL) { ep_error(&ep_sdk_error, ENCORE_PLUGIN_LIMIT, "cannot allocate plugin handle"); return 0; }
    atomic_init(&handle->references, 1); handle->kind = kind;
    if (kind == 1) handle->value.module = value; else handle->value.binding = value;
    return (uintptr_t)handle;
}
void encore_plugin_handle_retain(uintptr_t token) {
    if (token) atomic_fetch_add_explicit(&((ep_sdk_handle *)token)->references, 1, memory_order_relaxed);
}
void encore_plugin_handle_release(uintptr_t token) {
    ep_sdk_handle *handle = (void *)token;
    if (!handle || atomic_fetch_sub_explicit(&handle->references, 1, memory_order_acq_rel) != 1) return;
    if (handle->kind == 1) encore_plugin_module_release(handle->value.module);
    else encore_plugin_binding_release(handle->value.binding);
    free(handle);
}
uint32_t encore_plugin_native_error_code(void) { return ep_sdk_error.code; }
encore_str encore_plugin_native_error_message(void) { return encore_from_cstr_copy(ep_sdk_error.message); }
static char *ep_sdk_text(encore_str value) {
    if (memchr(encore_str_data(value), 0, encore_str_size(value))) {
        ep_error(&ep_sdk_error, ENCORE_PLUGIN_INVALID_VALUE, "plugin name or path contains NUL"); return NULL;
    }
    return encore_to_cstr(value);
}
uintptr_t encore_plugin_native_load(encore_str path, size_t bytes, uint32_t depth, uint32_t retired, uint32_t wait_ms) {
    char *text = ep_sdk_text(path); if (!text) return 0;
    encore_plugin_module *module = NULL;
    encore_plugin_options options = {bytes, depth, retired, wait_ms};
    encore_plugin_status status = encore_plugin_load(text, &options, &module, &ep_sdk_error); free(text);
    if (status != ENCORE_PLUGIN_OK) return 0;
    uintptr_t out = ep_sdk_wrap(1, module); if (!out) encore_plugin_module_release(module); return out;
}
uintptr_t encore_plugin_native_bind(uintptr_t token, encore_str name, encore_str fingerprint) {
    ep_sdk_handle *handle = (void *)token;
    if (!handle || handle->kind != 1) { ep_error(&ep_sdk_error, ENCORE_PLUGIN_CLOSED, "missing module"); return 0; }
    char *n = ep_sdk_text(name); if (!n) return 0;
    char *f = ep_sdk_text(fingerprint); if (!f) { free(n); return 0; }
    encore_plugin_binding *binding = NULL;
    encore_plugin_status status = encore_plugin_bind(handle->value.module, n, f, &binding, &ep_sdk_error);
    free(n); free(f); if (status != ENCORE_PLUGIN_OK) return 0;
    uintptr_t out = ep_sdk_wrap(2, binding); if (!out) encore_plugin_binding_release(binding); return out;
}
uint32_t encore_plugin_native_reload(uintptr_t token, encore_str path) {
    ep_sdk_handle *handle = (void *)token;
    if (!handle || handle->kind != 1) return ep_error(&ep_sdk_error, ENCORE_PLUGIN_CLOSED, "missing module");
    char *text = ep_sdk_text(path); if (!text) return ep_sdk_error.code;
    encore_plugin_status out = encore_plugin_reload(handle->value.module, text, &ep_sdk_error); free(text); return out;
}
uint32_t encore_plugin_native_close(uintptr_t token) {
    ep_sdk_handle *handle = (void *)token;
    return !handle || handle->kind != 1 ? ep_error(&ep_sdk_error, ENCORE_PLUGIN_CLOSED, "missing module") :
        encore_plugin_close(handle->value.module, &ep_sdk_error);
}
_Static_assert(sizeof(encore_plugin_call) + alignof(encore_plugin_call) <= 2048, "SDK stack call frame overflow");
uintptr_t encore_plugin_frame_begin(uintptr_t storage, size_t bytes, uintptr_t token) {
    ep_sdk_handle *handle = (void *)token;
    uintptr_t aligned = (storage + alignof(encore_plugin_call) - 1) & ~(uintptr_t)(alignof(encore_plugin_call) - 1);
    if (!handle || handle->kind != 2 || aligned < storage || aligned - storage > bytes ||
        bytes - (aligned - storage) < sizeof(encore_plugin_call)) {
        ep_error(&ep_sdk_error, ENCORE_PLUGIN_INVALID_VALUE, "invalid plugin call frame"); return 0;
    }
    encore_plugin_call *call = (void *)aligned;
    if (encore_plugin_call_begin(handle->value.binding, call) != ENCORE_PLUGIN_OK) {
        ep_sdk_error = call->error; encore_plugin_call_clear(call); return 0;
    }
    return aligned;
}
uintptr_t encore_plugin_frame_arena(uintptr_t frame) { return (uintptr_t)&((encore_plugin_call *)frame)->arena; }
uintptr_t encore_plugin_frame_output(uintptr_t frame) { return (uintptr_t)&((encore_plugin_call *)frame)->value; }
uint32_t encore_plugin_frame_dispatch(uintptr_t frame, size_t method, uintptr_t args) {
    encore_plugin_call *call = (void *)frame; const encore_plugin_value *value = (void *)args;
    if (!value || (value->kind != ENCORE_PLUGIN_RECORD && value->kind != ENCORE_PLUGIN_UNIT)) return ep_error(&ep_sdk_error, ENCORE_PLUGIN_INVALID_VALUE, "plugin arguments must be a tuple");
    encore_plugin_status status = encore_plugin_call_dispatch(call, method, value->data, value->length);
    if (status != ENCORE_PLUGIN_OK) ep_sdk_error = call->error; return status;
}
void encore_plugin_frame_clear(uintptr_t frame) { encore_plugin_call_clear((void *)frame); }
uint32_t encore_plugin_wire_max_depth(uintptr_t arena_token) {
    const encore_plugin_arena *arena = (const void *)arena_token;
    return arena->max_value_depth ? arena->max_value_depth : 128;
}
uintptr_t encore_plugin_wire_new(uintptr_t arena_token, uint32_t kind, uint32_t auxiliary, size_t count) {
    encore_plugin_arena *arena = (void *)arena_token;
    encore_plugin_value *value = arena->allocate(arena->context, sizeof(*value), alignof(encore_plugin_value));
    if (!value) return 0;
    *value = (encore_plugin_value){.kind = kind, .auxiliary = auxiliary};
    if (count) {
        if (count > SIZE_MAX / sizeof(*value)) return 0;
        value->data = arena->allocate(arena->context, count * sizeof(*value), alignof(encore_plugin_value));
        if (!value->data) return 0;
        memset((void *)value->data, 0, count * sizeof(*value)); value->length = count;
    }
    return (uintptr_t)value;
}
uintptr_t encore_plugin_wire_child(uintptr_t value, size_t index) {
    encore_plugin_value *v = (void *)value;
    return v && index < v->length ? (uintptr_t)((const encore_plugin_value *)v->data + index) : 0;
}
void encore_plugin_wire_assign(uintptr_t destination, uintptr_t source) { *(encore_plugin_value *)destination = *(encore_plugin_value *)source; }
uint32_t encore_plugin_wire_kind(uintptr_t value) { return ((encore_plugin_value *)value)->kind; }
uint32_t encore_plugin_wire_tag(uintptr_t value) { return ((encore_plugin_value *)value)->auxiliary; }
size_t encore_plugin_wire_count(uintptr_t value) { return ((encore_plugin_value *)value)->length; }
uint64_t encore_plugin_wire_bits(uintptr_t value) { return ((encore_plugin_value *)value)->bits; }
void encore_plugin_wire_set_bits(uintptr_t value, uint64_t bits) { ((encore_plugin_value *)value)->bits = bits; }
uint64_t encore_plugin_wire_f64_bits(double value) { uint64_t bits; memcpy(&bits, &value, sizeof(bits)); return bits; }
double encore_plugin_wire_f64(uint64_t bits) { double value; memcpy(&value, &bits, sizeof(value)); return value; }
bool encore_plugin_wire_string(uintptr_t value, uintptr_t arena_token, encore_str text) {
    encore_plugin_value *v = (void *)value; encore_plugin_arena *arena = (void *)arena_token;
    size_t bytes = encore_str_size(text);
    void *copy = bytes ? arena->allocate(arena->context, bytes, 1) : NULL;
    if (bytes && !copy) return false;
    if (bytes) memcpy(copy, encore_str_data(text), bytes);
    v->data = copy; v->length = bytes; return true;
}
encore_str encore_plugin_wire_read_string(uintptr_t value) {
    encore_plugin_value *v = (void *)value;
    if (!v->length) return encore_empty_str();
    char *copy = malloc(v->length + 1);
    if (!copy) abort();
    memcpy(copy, v->data, v->length); copy[v->length] = 0;
    return encore_from_owned_buffer(copy, v->length);
}
/* Builders used only by compiler-generated plugin adapters. They translate
 * pointer-sized Encore FFI arguments to the exact public C callback types. */
typedef uint32_t (*ep_sdk_factory_fn)(uintptr_t, uintptr_t);
typedef uint32_t (*ep_sdk_invoke_fn)(uintptr_t, uintptr_t, size_t, uintptr_t, uintptr_t, uintptr_t);
typedef void (*ep_sdk_drop_fn)(uintptr_t);
typedef uint32_t (*ep_sdk_save_fn)(uintptr_t, uintptr_t, uintptr_t, uintptr_t);
typedef uint32_t (*ep_sdk_restore_fn)(uintptr_t, uintptr_t, uintptr_t);
typedef struct ep_sdk_export {
    encore_plugin_interface interface;
    encore_plugin_method *methods;
    ep_sdk_factory_fn create;
    ep_sdk_drop_fn drop;
    ep_sdk_save_fn save;
    ep_sdk_restore_fn restore;
    char *resource_key;
    bool resource_ready;
    struct ep_sdk_export *next_resource;
} ep_sdk_export;
typedef struct ep_sdk_private_descriptor {
    encore_plugin_descriptor public;
    ep_sdk_export *resources;
} ep_sdk_private_descriptor;
typedef struct ep_sdk_object {
    _Atomic size_t references;
    uintptr_t payload;
    ep_sdk_export *type;
} ep_sdk_object;
static _Atomic(encore_plugin_descriptor *) ep_sdk_descriptor;
static _Thread_local char ep_sdk_callback_error[512];
static encore_plugin_module *ep_sdk_resources;
uint32_t encore_plugin_generated_error(uintptr_t destination, uint32_t code, encore_str message) {
    encore_plugin_error *error = (void *)destination;
    size_t size = encore_str_size(message);
    if (size >= sizeof(ep_sdk_callback_error)) size = sizeof(ep_sdk_callback_error) - 1;
    memcpy(ep_sdk_callback_error, encore_str_data(message), size); ep_sdk_callback_error[size] = 0;
    if (error) *error = (encore_plugin_error){code, {(const uint8_t *)ep_sdk_callback_error, size}};
    return code;
}
void encore_plugin_generated_payload(uintptr_t destination, uintptr_t payload) { *(uintptr_t *)destination = payload; }
static void ep_sdk_object_release(void *pointer) {
    ep_sdk_object *object = pointer;
    if (!object || atomic_fetch_sub_explicit(&object->references, 1, memory_order_acq_rel) != 1) return;
    object->type->drop(object->payload); free(object);
}
static encore_plugin_status ep_sdk_created(ep_sdk_export *type, uintptr_t payload, encore_plugin_object *out) {
    ep_sdk_object *object = calloc(1, sizeof(*object));
    if (!object) { type->drop(payload); return ENCORE_PLUGIN_LIMIT; }
    atomic_init(&object->references, 1); object->payload = payload; object->type = type;
    *out = (encore_plugin_object){object, &type->interface, ep_sdk_object_release}; return ENCORE_PLUGIN_OK;
}
static encore_plugin_status ep_sdk_create(void *context, encore_plugin_object *out, encore_plugin_error *error) {
    ep_sdk_export *type = context; uintptr_t payload = 0;
    uint32_t status = type->create((uintptr_t)&payload, (uintptr_t)error);
    return status == ENCORE_PLUGIN_OK ? ep_sdk_created(type, payload, out) : status;
}
static encore_plugin_status ep_sdk_invoke(void *context, void *object, const encore_plugin_value *args,
    size_t count, encore_plugin_arena *arena, encore_plugin_value *out, encore_plugin_error *error) {
    ep_sdk_invoke_fn function; memcpy(&function, &context, sizeof(function));
    return function(((ep_sdk_object *)object)->payload, (uintptr_t)args, count, (uintptr_t)arena, (uintptr_t)out, (uintptr_t)error);
}
static encore_plugin_status ep_sdk_save(void *context, void *object, encore_plugin_arena *arena,
    encore_plugin_snapshot *out, encore_plugin_error *error) {
    return ((ep_sdk_export *)context)->save(((ep_sdk_object *)object)->payload, (uintptr_t)arena, (uintptr_t)out, (uintptr_t)error);
}
static encore_plugin_status ep_sdk_restore(void *context, encore_plugin_snapshot state,
    encore_plugin_object *out, encore_plugin_error *error) {
    ep_sdk_export *type = context; uintptr_t payload = 0;
    uint32_t status = type->restore((uintptr_t)&state, (uintptr_t)&payload, (uintptr_t)error);
    if (status == ENCORE_PLUGIN_FACTORY_FAILED) { status = ENCORE_PLUGIN_STATE_FAILED; if (error) error->code = status; }
    return status == ENCORE_PLUGIN_OK ? ep_sdk_created(type, payload, out) : status;
}
static void ep_sdk_export_free(ep_sdk_export *type) {
    if (!type) return;
    for (size_t j = 0; j < type->interface.method_count; ++j) {
        free((void *)type->methods[j].name); free((void *)type->methods[j].fingerprint);
    }
    free(type->methods); free((void *)type->interface.name); free((void *)type->interface.fingerprint);
    free(type->resource_key); free(type);
}
static void ep_sdk_descriptor_free(encore_plugin_descriptor *descriptor) {
    if (!descriptor) return;
    for (size_t i = 0; i < descriptor->export_count; ++i) {
        encore_plugin_export *export = (encore_plugin_export *)descriptor->exports + i;
        ep_sdk_export_free(export->context); free((void *)export->name);
    }
    ep_sdk_export *resource = ((ep_sdk_private_descriptor *)descriptor)->resources;
    while (resource) { ep_sdk_export *next = resource->next_resource; ep_sdk_export_free(resource); resource = next; }
    free((void *)descriptor->exports); free((void *)descriptor->project_name); free((void *)descriptor->project_version); free(descriptor);
}
extern void encore_static_shutdown(void);
static void ep_sdk_descriptor_deinitialize(void) {
    encore_static_shutdown();
    /* All provider-owned resources must have been dropped with the roots and
     * returned resources. Background native threads cannot outlive unloading. */
    if (ep_sdk_resources) {
        assert(ep_sdk_resources->bindings == NULL);
        encore_plugin_module_release(ep_sdk_resources); ep_sdk_resources = NULL;
    }
    ep_sdk_descriptor_free(atomic_exchange_explicit(&ep_sdk_descriptor, NULL, memory_order_acq_rel));
}
uintptr_t encore_plugin_descriptor_cached(void) { return (uintptr_t)atomic_load_explicit(&ep_sdk_descriptor, memory_order_acquire); }
uintptr_t encore_plugin_descriptor_new(encore_str name, encore_str version, size_t count) {
    encore_plugin_descriptor *descriptor = (void *)calloc(1, sizeof(ep_sdk_private_descriptor));
    encore_plugin_export *exports = count ? calloc(count, sizeof(*exports)) : NULL;
    if (!descriptor || (count && !exports)) { free(descriptor); free(exports); return 0; }
    *descriptor = (encore_plugin_descriptor){ENCORE_PLUGIN_MAGIC, ENCORE_PLUGIN_ABI_V1, sizeof(*descriptor),
        sizeof(void *) * 8, ENCORE_PLUGIN_TARGET, encore_to_cstr(name), encore_to_cstr(version), count, exports, ep_sdk_descriptor_deinitialize};
    return (uintptr_t)descriptor;
}
bool encore_plugin_descriptor_export(uintptr_t token, size_t index, encore_str name, encore_str interface_name,
    encore_str fingerprint, size_t count, uintptr_t create, uintptr_t drop, uintptr_t save, uintptr_t restore) {
    encore_plugin_descriptor *descriptor = (void *)token;
    if (!descriptor || index >= descriptor->export_count || count > 4096) return false;
    ep_sdk_export *type = calloc(1, sizeof(*type));
    encore_plugin_method *methods = count ? calloc(count, sizeof(*methods)) : NULL;
    if (!type || (count && !methods)) { free(type); free(methods); return false; }
    type->methods = methods;
    type->interface = (encore_plugin_interface){sizeof(encore_plugin_interface), encore_to_cstr(interface_name), encore_to_cstr(fingerprint), count, methods};
    memcpy(&type->create, &create, sizeof(create)); memcpy(&type->drop, &drop, sizeof(drop));
    memcpy(&type->save, &save, sizeof(save)); memcpy(&type->restore, &restore, sizeof(restore));
    ((encore_plugin_export *)descriptor->exports)[index] = (encore_plugin_export){encore_to_cstr(name), &type->interface,
        save ? 0 : ENCORE_PLUGIN_STATELESS, ep_sdk_create, save ? ep_sdk_save : NULL, restore ? ep_sdk_restore : NULL, type};
    return true;
}
bool encore_plugin_descriptor_method(uintptr_t token, size_t export_index, size_t index,
    encore_str name, encore_str fingerprint, uintptr_t function) {
    encore_plugin_descriptor *descriptor = (void *)token;
    if (!descriptor || export_index >= descriptor->export_count || !descriptor->exports[export_index].context) return false;
    ep_sdk_export *type = descriptor->exports[export_index].context;
    if (index >= type->interface.method_count) return false;
    void *context; memcpy(&context, &function, sizeof(function));
    type->methods[index] = (encore_plugin_method){encore_to_cstr(name), encore_to_cstr(fingerprint), ep_sdk_invoke, context};
    return true;
}
uintptr_t encore_plugin_descriptor_commit(uintptr_t token) {
    encore_plugin_descriptor *descriptor = (void *)token;
    /* The module loader also runs this hook when a host rejects the ABI and
     * cannot safely interpret the descriptor's deinitialize field. Normal
     * manager teardown has already emptied the descriptor before dlclose. */
    if (atexit(ep_sdk_descriptor_deinitialize) != 0) { ep_sdk_descriptor_free(descriptor); return 0; }
    encore_plugin_descriptor *expected = NULL;
    if (!atomic_compare_exchange_strong_explicit(&ep_sdk_descriptor, &expected, descriptor, memory_order_release, memory_order_acquire)) {
        ep_sdk_descriptor_free(descriptor); return (uintptr_t)expected;
    }
    return token;
}
void encore_plugin_descriptor_abort(uintptr_t token) { ep_sdk_descriptor_free((void *)token); }
uintptr_t encore_plugin_generated_arguments(uintptr_t args, size_t count, uintptr_t arena_token) {
    uintptr_t token = encore_plugin_wire_new(arena_token, count ? ENCORE_PLUGIN_RECORD : ENCORE_PLUGIN_UNIT, 0, 0);
    if (token) { encore_plugin_value *value = (void *)token; value->data = (void *)args; value->length = count; }
    return token;
}
uintptr_t encore_plugin_snapshot_allocate(uintptr_t snapshot, uintptr_t arena_token, uint32_t version, size_t bytes) {
    encore_plugin_arena *arena = (void *)arena_token;
    void *data = bytes ? arena->allocate(arena->context, bytes, 1) : NULL;
    if (bytes && !data) return 0;
    *(encore_plugin_snapshot *)snapshot = (encore_plugin_snapshot){version, {data, bytes}}; return (uintptr_t)data;
}
void encore_plugin_snapshot_set(uintptr_t data, size_t index, uint8_t value) { ((uint8_t *)data)[index] = value; }
uint32_t encore_plugin_snapshot_version(uintptr_t snapshot) { return ((encore_plugin_snapshot *)snapshot)->version; }
size_t encore_plugin_snapshot_size(uintptr_t snapshot) { return ((encore_plugin_snapshot *)snapshot)->data.length; }
uint8_t encore_plugin_snapshot_byte(uintptr_t snapshot, size_t index) { return ((encore_plugin_snapshot *)snapshot)->data.data[index]; }

/* Resource interfaces are private descriptor data, not additional root exports. */
bool encore_plugin_descriptor_resource_type(uintptr_t token, size_t index, encore_str key) {
    encore_plugin_descriptor *descriptor = (void *)token;
    if (!descriptor || index >= descriptor->export_count) return false;
    ep_sdk_export *type = descriptor->exports[index].context;
    if (!type || type->resource_key) return false;
    type->resource_key = encore_to_cstr(key); return type->resource_key != NULL;
}
uintptr_t encore_plugin_descriptor_resource(uintptr_t token, encore_str key, encore_str name,
    encore_str fingerprint, size_t count, uintptr_t drop) {
    encore_plugin_descriptor *descriptor = (void *)token;
    if (!descriptor || count > 4096) return 0;
    ep_sdk_export *type = calloc(1, sizeof(*type));
    encore_plugin_method *methods = count ? calloc(count, sizeof(*methods)) : NULL;
    if (!type || (count && !methods)) { free(type); free(methods); return 0; }
    type->methods = methods;
    type->interface = (encore_plugin_interface){sizeof(encore_plugin_interface), encore_to_cstr(name), encore_to_cstr(fingerprint), count, methods};
    type->resource_key = encore_to_cstr(key); memcpy(&type->drop, &drop, sizeof(drop));
    ep_sdk_private_descriptor *private = (void *)descriptor;
    type->next_resource = private->resources; private->resources = type; return (uintptr_t)type;
}
bool encore_plugin_descriptor_resource_method(uintptr_t token, size_t index,
    encore_str name, encore_str fingerprint, uintptr_t function) {
    ep_sdk_export *type = (void *)token;
    if (!type || index >= type->interface.method_count) return false;
    void *context; memcpy(&context, &function, sizeof(function));
    type->methods[index] = (encore_plugin_method){encore_to_cstr(name), encore_to_cstr(fingerprint), ep_sdk_invoke, context}; return true;
}
#ifdef _WIN32
static SRWLOCK ep_sdk_resource_init_lock = SRWLOCK_INIT;
static void ep_sdk_resource_init_enter(void) { AcquireSRWLockExclusive(&ep_sdk_resource_init_lock); }
static void ep_sdk_resource_init_leave(void) { ReleaseSRWLockExclusive(&ep_sdk_resource_init_lock); }
#else
static pthread_mutex_t ep_sdk_resource_init_lock = PTHREAD_MUTEX_INITIALIZER;
static void ep_sdk_resource_init_enter(void) { if (pthread_mutex_lock(&ep_sdk_resource_init_lock)) abort(); }
static void ep_sdk_resource_init_leave(void) { if (pthread_mutex_unlock(&ep_sdk_resource_init_lock)) abort(); }
#endif
static encore_plugin_module *ep_sdk_resource_module(void) {
    ep_sdk_resource_init_enter();
    if (!ep_sdk_resources) {
        encore_plugin_module *module = calloc(1, sizeof(*module));
        encore_plugin_generation *generation = calloc(1, sizeof(*generation));
        if (!module || !generation) { free(module); free(generation); ep_sdk_resource_init_leave(); return NULL; }
        ep_mutex_init(&module->mutex); ep_mutex_init(&module->reload_mutex); ep_condition_init(&module->idle);
        ep_mutex_init(&generation->execution); generation->module = module; generation->references = 1;
        module->current = generation; module->references = 1; module->options = encore_plugin_default_options();
        ep_sdk_resources = module;
    }
    encore_plugin_module *module = ep_sdk_resources; ep_sdk_resource_init_leave(); return module;
}
/* Takes object ownership on success; the caller retains it on allocation failure. */
static uintptr_t ep_sdk_local_binding(ep_sdk_object *object) {
    encore_plugin_module *module = ep_sdk_resource_module();
    encore_plugin_binding *binding = module ? calloc(1, sizeof(*binding)) : NULL;
    ep_sdk_handle *handle = binding ? calloc(1, sizeof(*handle)) : NULL;
    if (!binding || !handle) { free(binding); free(handle); ep_error(&ep_sdk_error, ENCORE_PLUGIN_LIMIT, "cannot allocate local resource"); return 0; }
    ep_lock(&module->mutex);
    encore_plugin_generation *generation = module->current;
    *binding = (encore_plugin_binding){module, generation, NULL, {object, &object->type->interface, ep_sdk_object_release}, 1, true, module->bindings};
    module->bindings = binding; ++module->references; ++generation->references;
    ep_unlock(&module->mutex);
    atomic_init(&handle->references, 1); handle->kind = 2; handle->value.binding = binding; return (uintptr_t)handle;
}
uintptr_t encore_plugin_native_resource(uintptr_t payload, encore_str key) {
    encore_plugin_descriptor *descriptor = atomic_load_explicit(&ep_sdk_descriptor, memory_order_acquire);
    char *text = ep_sdk_text(key); if (!text) return 0;
    ep_sdk_export *type = NULL;
    ep_sdk_resource_init_enter();
    if (descriptor) {
        for (size_t i = 0; i < descriptor->export_count; ++i) {
            ep_sdk_export *candidate = descriptor->exports[i].context;
            if (candidate->resource_key && !strcmp(candidate->resource_key, text)) { type = candidate; break; }
        }
        if (!type) for (ep_sdk_export *candidate = ((ep_sdk_private_descriptor *)descriptor)->resources; candidate; candidate = candidate->next_resource)
            if (candidate->resource_ready && !strcmp(candidate->resource_key, text)) { type = candidate; break; }
    }
    ep_sdk_resource_init_leave();
    free(text);
    if (!type) { ep_error(&ep_sdk_error, ENCORE_PLUGIN_ABI_MISMATCH, "resource implementation is not registered by this plugin"); return 0; }
    ep_sdk_object *object = calloc(1, sizeof(*object));
    if (!object) { ep_error(&ep_sdk_error, ENCORE_PLUGIN_LIMIT, "cannot allocate resource object"); return 0; }
    atomic_init(&object->references, 1); object->payload = payload; object->type = type;
    uintptr_t result = ep_sdk_local_binding(object); if (!result) free(object); return result;
}
uintptr_t encore_plugin_wire_take_resource(uintptr_t frame, uintptr_t value_token, encore_str fingerprint) {
    encore_plugin_value *value = (void *)value_token;
    if (!value || value->kind != ENCORE_PLUGIN_RESOURCE) { ep_error(&ep_sdk_error, ENCORE_PLUGIN_INVALID_VALUE, "expected resource"); return 0; }
    char *contract = ep_sdk_text(fingerprint); if (!contract) return 0;
    if (!frame) {
        const encore_plugin_object *object = value->data;
        if (value->auxiliary != 0 || !object || object->destroy != ep_sdk_object_release ||
            !ep_object_valid(*object, object->interface) || strcmp(contract, object->interface->fingerprint)) {
            free(contract); ep_error(&ep_sdk_error, ENCORE_PLUGIN_ABI_MISMATCH, "resource belongs to a different provider"); return 0;
        }
        free(contract); ep_sdk_object *shared = object->data;
        atomic_fetch_add_explicit(&shared->references, 1, memory_order_relaxed);
        uintptr_t result = ep_sdk_local_binding(shared); if (!result) ep_sdk_object_release(shared); return result;
    }
    encore_plugin_binding *binding = NULL;
    encore_plugin_status status = encore_plugin_take_resource((void *)frame, *value, &binding);
    if (status != ENCORE_PLUGIN_OK) { free(contract); ep_error(&ep_sdk_error, status, "invalid resource result"); return 0; }
    if (strcmp(contract, binding->object.interface->fingerprint)) {
        free(contract); encore_plugin_binding_release(binding); ep_error(&ep_sdk_error, ENCORE_PLUGIN_ABI_MISMATCH, "resource interface differs"); return 0;
    }
    free(contract); uintptr_t out = ep_sdk_wrap(2, binding); if (!out) encore_plugin_binding_release(binding); return out;
}
uint32_t encore_plugin_wire_resource(uintptr_t token, uintptr_t value, uintptr_t arena_token) {
    ep_sdk_handle *handle = (void *)token;
    if (!handle || handle->kind != 2 || !handle->value.binding->resource) return ENCORE_PLUGIN_INVALID_VALUE;
    encore_plugin_binding *binding = handle->value.binding;
    if (binding->generation->library != NULL) return encore_plugin_resource_value(binding, (void *)value);
    encore_plugin_arena *arena = (void *)arena_token;
    if (!arena || !arena->resource) return ENCORE_PLUGIN_INVALID_VALUE;
    if (arena->resource == ep_adopt_resource) {
        encore_plugin_call *call = arena->context;
        if (!call->encoding_result && call->generation == binding->generation)
            return encore_plugin_resource_value(binding, (void *)value);
    }
    ep_sdk_object *object = binding->object.data;
    atomic_fetch_add_explicit(&object->references, 1, memory_order_relaxed);
    encore_plugin_status status = arena->resource(arena->context, binding->object, (void *)value);
    if (status != ENCORE_PLUGIN_OK) ep_sdk_object_release(object); return status;
}

bool encore_plugin_wire_bytes(uintptr_t value, uintptr_t arena_token, const uint8_t *bytes, size_t length) {
    encore_plugin_value *v = (void *)value; encore_plugin_arena *arena = (void *)arena_token;
    if (length && !bytes) return false;
    void *data = length ? arena->allocate(arena->context, length, 1) : NULL;
    if (length && !data) return false;
    if (length) memcpy(data, bytes, length);
    v->kind = ENCORE_PLUGIN_BYTES; v->data = data; v->length = length; return true;
}
bool encore_plugin_wire_read_bytes(uintptr_t value, uint8_t *bytes, size_t length) {
    encore_plugin_value *v = (void *)value;
    if (!v || v->kind != ENCORE_PLUGIN_BYTES || v->length != length || (length && !bytes)) return false;
    if (length) memcpy(bytes, v->data, length); return true;
}

bool encore_plugin_descriptor_resource_ready(uintptr_t token) {
    ep_sdk_export *type = (void *)token;
    if (!type || !ep_interface_valid(&type->interface)) return false;
    type->resource_ready = true; return true;
}
uintptr_t encore_plugin_native_resource_registered(uintptr_t payload, encore_str key, uintptr_t initialize) {
    encore_plugin_descriptor *descriptor = atomic_load_explicit(&ep_sdk_descriptor, memory_order_acquire);
    if (!descriptor || !initialize) { ep_error(&ep_sdk_error, ENCORE_PLUGIN_CLOSED, "resources can only be created inside a loaded plugin"); return 0; }
    char *text = ep_sdk_text(key); if (!text) return 0;
    ep_sdk_resource_init_enter(); bool found = false;
    for (ep_sdk_export *type = ((ep_sdk_private_descriptor *)descriptor)->resources; type; type = type->next_resource) {
        if (type->resource_ready && !strcmp(type->resource_key, text)) { found = true; break; }
    }
    free(text);
    if (!found) {
        uintptr_t (*create)(uintptr_t); memcpy(&create, &initialize, sizeof(create));
        uintptr_t type = create((uintptr_t)descriptor);
        if (!type || !((ep_sdk_export *)type)->resource_ready) {
            ep_sdk_resource_init_leave(); ep_error(&ep_sdk_error, ENCORE_PLUGIN_LIMIT, "cannot initialize resource adapters"); return 0;
        }
    }
    ep_sdk_resource_init_leave(); return encore_plugin_native_resource(payload, key);
}
#endif
