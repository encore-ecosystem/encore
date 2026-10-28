#ifndef ENCORE_PLUGIN_ABI_H
#define ENCORE_PLUGIN_ABI_H

/* Public plugin ABI v1. No Encore runtime layout crosses this boundary.
 * All memory in an output arena belongs to its caller. Objects must be
 * destroyed through their issuing module while that module remains loaded. */
#include <stddef.h>
#include <stdint.h>

#define ENCORE_PLUGIN_ABI_V1 UINT32_C(1)
#define ENCORE_PLUGIN_MAGIC UINT64_C(0x3147554c50514e45)
#ifdef _WIN32
#define ENCORE_PLUGIN_EXPORT __declspec(dllexport)
#define ENCORE_PLUGIN_TARGET "windows"
#elif defined(__APPLE__)
#define ENCORE_PLUGIN_EXPORT __attribute__((visibility("default")))
#define ENCORE_PLUGIN_TARGET "macos"
#else
#define ENCORE_PLUGIN_EXPORT __attribute__((visibility("default")))
#define ENCORE_PLUGIN_TARGET "linux"
#endif

#ifdef __cplusplus
extern "C" {
#endif

typedef uint32_t encore_plugin_status;
enum {
    ENCORE_PLUGIN_OK = 0, ENCORE_PLUGIN_LOAD_FAILED, ENCORE_PLUGIN_ABI_MISMATCH,
    ENCORE_PLUGIN_MISSING_EXPORT, ENCORE_PLUGIN_CLOSED, ENCORE_PLUGIN_BUSY,
    ENCORE_PLUGIN_WRONG_GENERATION, ENCORE_PLUGIN_INVALID_VALUE,
    ENCORE_PLUGIN_FACTORY_FAILED, ENCORE_PLUGIN_STATE_FAILED, ENCORE_PLUGIN_LIMIT
};

typedef struct encore_plugin_bytes {
    const uint8_t *data;
    size_t length;
} encore_plugin_bytes;

typedef enum encore_plugin_value_kind {
    ENCORE_PLUGIN_UNIT = 0, ENCORE_PLUGIN_BOOL, ENCORE_PLUGIN_U64,
    ENCORE_PLUGIN_I64, ENCORE_PLUGIN_F64, ENCORE_PLUGIN_STRING,
    ENCORE_PLUGIN_BYTES, ENCORE_PLUGIN_LIST, ENCORE_PLUGIN_RECORD,
    ENCORE_PLUGIN_VARIANT, ENCORE_PLUGIN_RESOURCE
} encore_plugin_value_kind;

/* Scalars use bits; aggregates use data (an array of values) and length.
 * Variant discriminants use auxiliary. Resource data points at an object.
 * The exact application schema is checked when binding the interface. */
typedef struct encore_plugin_value {
    uint32_t kind;
    uint32_t auxiliary;
    uint64_t bits;
    const void *data;
    size_t length;
} encore_plugin_value;

struct encore_plugin_object;
typedef struct encore_plugin_arena {
    void *context;
    void *(*allocate)(void *context, size_t bytes, size_t alignment);
    /* Takes object ownership only on success. The result is a host handle. */
    encore_plugin_status (*resource)(void *context, struct encore_plugin_object object, encore_plugin_value *out);
    /* Zero selects the v1 default (128); valid configured limits are 1..256. */
    uint32_t max_value_depth;
} encore_plugin_arena;

typedef struct encore_plugin_error {
    uint32_t code;
    encore_plugin_bytes message;
} encore_plugin_error;

typedef struct encore_plugin_snapshot {
    uint32_t version;
    encore_plugin_bytes data;
} encore_plugin_snapshot;

struct encore_plugin_interface;
typedef struct encore_plugin_object {
    void *data;
    const struct encore_plugin_interface *interface;
    void (*destroy)(void *data);
} encore_plugin_object;

typedef encore_plugin_status (*encore_plugin_invoke_fn)(void *context, void *object,
    const encore_plugin_value *arguments, size_t argument_count,
    encore_plugin_arena *output_arena, encore_plugin_value *output,
    encore_plugin_error *error);

typedef struct encore_plugin_method {
    const char *name;
    const char *fingerprint;
    encore_plugin_invoke_fn invoke;
    void *context;
} encore_plugin_method;

typedef struct encore_plugin_interface {
    uint32_t size;
    const char *name;
    const char *fingerprint;
    size_t method_count;
    const encore_plugin_method *methods;
} encore_plugin_interface;

typedef encore_plugin_status (*encore_plugin_create_fn)(void *, encore_plugin_object *, encore_plugin_error *);
typedef encore_plugin_status (*encore_plugin_save_fn)(void *, void *, encore_plugin_arena *, encore_plugin_snapshot *, encore_plugin_error *);
typedef encore_plugin_status (*encore_plugin_restore_fn)(void *, encore_plugin_snapshot, encore_plugin_object *, encore_plugin_error *);
#define ENCORE_PLUGIN_STATELESS UINT32_C(1)
typedef struct encore_plugin_export {
    const char *name;
    const encore_plugin_interface *interface;
    uint32_t flags;
    encore_plugin_create_fn create;
    encore_plugin_save_fn save;
    encore_plugin_restore_fn restore;
    void *context;
} encore_plugin_export;

typedef struct encore_plugin_descriptor {
    uint64_t magic;
    uint32_t abi;
    uint32_t size;
    uint32_t pointer_bits;
    const char *target_os;
    const char *project_name;
    const char *project_version;
    size_t export_count;
    const encore_plugin_export *exports;
    void (*deinitialize)(void);
} encore_plugin_descriptor;

typedef const encore_plugin_descriptor *(*encore_plugin_entry_fn)(void);
#ifdef __cplusplus
}
#endif
#endif
