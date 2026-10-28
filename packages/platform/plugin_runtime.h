#ifndef ENCORE_PLUGIN_RUNTIME_H
#define ENCORE_PLUGIN_RUNTIME_H
#include "plugin_abi.h"
#include <stdbool.h>
#include <stdalign.h>

typedef struct encore_plugin_module encore_plugin_module;
typedef struct encore_plugin_binding encore_plugin_binding;
typedef struct encore_plugin_generation encore_plugin_generation;
typedef struct encore_plugin_allocation encore_plugin_allocation;
typedef struct encore_plugin_resource_lease encore_plugin_resource_lease;

typedef struct encore_plugin_options {
    size_t max_transfer_bytes;
    uint32_t max_value_depth;
    uint32_t max_retired_generations;
    uint32_t quiesce_timeout_ms;
} encore_plugin_options;

typedef struct encore_plugin_diagnostic {
    encore_plugin_status code;
    char message[512];
} encore_plugin_diagnostic;

/* A stack-allocated call owns its output arena and pins executing code until
 * clear. Scalar calls use no heap allocations. Do not copy initialized calls. */
typedef struct encore_plugin_call {
    encore_plugin_value value;
    encore_plugin_diagnostic error;
    encore_plugin_arena arena;
    encore_plugin_allocation *allocations;
    encore_plugin_resource_lease *resources;
    size_t bytes;
    size_t inline_used;
    bool encoding_result;
    encore_plugin_binding *binding;
    encore_plugin_generation *generation;
    alignas(max_align_t) unsigned char inline_data[512];
} encore_plugin_call;

encore_plugin_options encore_plugin_default_options(void);
encore_plugin_status encore_plugin_load(const char *, const encore_plugin_options *,
    encore_plugin_module **, encore_plugin_diagnostic *);
encore_plugin_status encore_plugin_bind(encore_plugin_module *, const char *, const char *,
    encore_plugin_binding **, encore_plugin_diagnostic *);
encore_plugin_status encore_plugin_call_begin(encore_plugin_binding *, encore_plugin_call *);
encore_plugin_status encore_plugin_call_dispatch(encore_plugin_call *, size_t, const encore_plugin_value *, size_t);
encore_plugin_status encore_plugin_invoke(encore_plugin_binding *, size_t,
    const encore_plugin_value *, size_t, encore_plugin_call *);
void encore_plugin_call_clear(encore_plugin_call *);
encore_plugin_status encore_plugin_reload(encore_plugin_module *, const char *, encore_plugin_diagnostic *);
encore_plugin_status encore_plugin_close(encore_plugin_module *, encore_plugin_diagnostic *);
void encore_plugin_module_retain(encore_plugin_module *);
void encore_plugin_module_release(encore_plugin_module *);
void encore_plugin_binding_retain(encore_plugin_binding *);
void encore_plugin_binding_release(encore_plugin_binding *);
encore_plugin_status encore_plugin_take_resource(encore_plugin_call *, encore_plugin_value, encore_plugin_binding **);
encore_plugin_status encore_plugin_resource_value(encore_plugin_binding *, encore_plugin_value *);
size_t encore_plugin_retired_count(encore_plugin_module *);
#endif
