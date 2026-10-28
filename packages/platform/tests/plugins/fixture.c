/* Real shared-library fixture for the native plugin manager. */
#include "../../plugin_abi.h"
#include <stdlib.h>
#include <assert.h>
#include <string.h>
#ifndef PLUGIN_REVISION
#define PLUGIN_REVISION 1
#endif
#ifndef PLUGIN_BAD_ABI
#define PLUGIN_BAD_ABI 0
#endif
#ifndef PLUGIN_BAD_SIGNATURE
#define PLUGIN_BAD_SIGNATURE 0
#endif
#ifndef PLUGIN_BAD_STATE
#define PLUGIN_BAD_STATE 0
#endif

typedef struct counter { uint64_t value; } counter;
static encore_plugin_status create(void *context, encore_plugin_object *out, encore_plugin_error *error);
static size_t live_objects;
static void destroy(void *object) { assert(live_objects); --live_objects; free(object); }
static void deinitialize(void) { assert(live_objects == 0); }
static encore_plugin_status increment(void *context, void *object, const encore_plugin_value *args,
    size_t count, encore_plugin_arena *arena, encore_plugin_value *out,
    encore_plugin_error *error) {
    (void)context; (void)arena; (void)error; (void)context;
    if (count != 1 || args[0].kind != ENCORE_PLUGIN_U64) return ENCORE_PLUGIN_INVALID_VALUE;
    counter *self = object;
    self->value += args[0].bits;
    *out = (encore_plugin_value){.kind = ENCORE_PLUGIN_U64,
        .bits = self->value + (PLUGIN_REVISION - 1) * 100};
    return ENCORE_PLUGIN_OK;
}
static encore_plugin_status save(void *context, void *object, encore_plugin_arena *arena,
    encore_plugin_snapshot *out, encore_plugin_error *error) {
    (void)error; (void)context;
    uint64_t *bytes = arena->allocate(arena->context, sizeof(*bytes), _Alignof(uint64_t));
    if (bytes == NULL) return ENCORE_PLUGIN_LIMIT;
    *bytes = ((counter *)object)->value;
    *out = (encore_plugin_snapshot){1, {(const uint8_t *)bytes, sizeof(*bytes)}};
    return ENCORE_PLUGIN_OK;
}
static encore_plugin_status restore(void *context, encore_plugin_snapshot state,
    encore_plugin_object *out, encore_plugin_error *error) {
    (void)context;
    if (PLUGIN_BAD_STATE || state.version != 1 || state.data.length != sizeof(uint64_t))
        return ENCORE_PLUGIN_STATE_FAILED;
    encore_plugin_status status = create(NULL, out, error);
    if (status == ENCORE_PLUGIN_OK) memcpy(&((counter *)out->data)->value, state.data.data, sizeof(uint64_t));
    return status;
}
static encore_plugin_status fork_counter(void *context, void *object, const encore_plugin_value *args,
    size_t count, encore_plugin_arena *arena, encore_plugin_value *out, encore_plugin_error *error) {
    (void)context; (void)args;
    if (count != 0 || arena->resource == NULL) return ENCORE_PLUGIN_INVALID_VALUE;
    encore_plugin_object child = {0};
    encore_plugin_status status = create(NULL, &child, error);
    if (status != ENCORE_PLUGIN_OK) return status;
    ((counter *)child.data)->value = ((counter *)object)->value;
    status = arena->resource(arena->context, child, out);
    if (status != ENCORE_PLUGIN_OK) destroy(child.data);
    return status;
}
static const encore_plugin_method methods[] = {
    {"increment", PLUGIN_BAD_SIGNATURE ? "str->str" : "u64->u64", increment, NULL}, {"fork", "()->Counter", fork_counter, NULL}
};
static const encore_plugin_interface interface = {
    sizeof(encore_plugin_interface), "fixture.Counter", "counter-contract-v1", 2, methods
};
static encore_plugin_status create(void *context, encore_plugin_object *out, encore_plugin_error *error) {
    (void)error; (void)context;
    counter *value = calloc(1, sizeof(*value));
    if (value == NULL) return ENCORE_PLUGIN_LIMIT;
    ++live_objects;
    *out = (encore_plugin_object){value, &interface, destroy};
    return ENCORE_PLUGIN_OK;
}
static const encore_plugin_export exports[] = {{"counter", &interface, 0, create, save, restore, NULL}};
static const encore_plugin_descriptor descriptor = {
    ENCORE_PLUGIN_MAGIC, ENCORE_PLUGIN_ABI_V1 + PLUGIN_BAD_ABI,
    sizeof(encore_plugin_descriptor), sizeof(void *) * 8, ENCORE_PLUGIN_TARGET,
    "fixture", "1.0.0", 1, exports, deinitialize
};
ENCORE_PLUGIN_EXPORT const encore_plugin_descriptor *encore_plugin_entry_v1(void) {
    return &descriptor;
}
