#include <stddef.h>
#include <stdatomic.h>
#if defined(_WIN32)
#include <process.h>
#elif !defined(__linux__)
#include <unistd.h>
#endif
#if defined(__linux__)
#include <stdio.h>
#include <unistd.h>
#endif

/* Every emission worker sets its target before touching layout or ABI code.
 * A process-wide value races even when two otherwise independent modules are
 * emitted for the same target: a host-width default must not leak into a
 * worker, and concurrent cross-target compilations must remain isolated. */
#if defined(_MSC_VER)
#define ENCORE_CODEGEN_THREAD_LOCAL __declspec(thread)
#else
#define ENCORE_CODEGEN_THREAD_LOCAL _Thread_local
#endif

static ENCORE_CODEGEN_THREAD_LOCAL size_t encore_target_pointer_width = sizeof(void *) * 8u;
#if defined(_WIN32)
static ENCORE_CODEGEN_THREAD_LOCAL size_t encore_windows_target = 1u;
#else
static ENCORE_CODEGEN_THREAD_LOCAL size_t encore_windows_target = 0u;
#endif

void encore_llvm_set_target_pointer_width(size_t bits) {
    encore_target_pointer_width = bits == 32u ? 32u : 64u;
}

void encore_llvm_set_windows_target(size_t enabled) {
    encore_windows_target = enabled != 0u;
}

size_t encore_llvm_is_windows_target(void) {
    return encore_windows_target;
}

size_t encore_llvm_target_pointer_width(void) {
    return encore_target_pointer_width;
}

size_t encore_codegen_rss_kb(void) {
#if defined(__linux__)
    FILE *file = fopen("/proc/self/statm", "r");
    unsigned long pages = 0;
    unsigned long resident = 0;
    if (file == NULL) return 0;
    if (fscanf(file, "%lu %lu", &pages, &resident) != 2) resident = 0;
    fclose(file);
    return (size_t)(resident * (unsigned long)sysconf(_SC_PAGESIZE) / 1024ul);
#else
    return 0;
#endif
}

/* Errors belong to an invocation/thread and are returned by the library API. */
typedef struct ehir_str_object ehir_str_object;
typedef struct { ehir_str_object *object; } ehir_str;
extern void encore_str_retain(ehir_str value);
extern void encore_str_drop(ehir_str value);
extern ehir_str encore_empty_str(void);
static ENCORE_CODEGEN_THREAD_LOCAL ehir_str ehir_codegen_error = {NULL};
void ehir_codegen_clear_error(void) {
    encore_str_drop(ehir_codegen_error);
    ehir_codegen_error.object = NULL;
}
void ehir_codegen_record_error(ehir_str message) {
    if (ehir_codegen_error.object != NULL) return;
    encore_str_retain(message);
    ehir_codegen_error = message;
}
ehir_str ehir_codegen_take_error(void) {
    ehir_str result = ehir_codegen_error;
    ehir_codegen_error.object = NULL;
    return result.object == NULL ? encore_empty_str() : result;
}

static _Atomic size_t ehir_llvm_stage_sequence = 0;
size_t ehir_llvm_process_id(void) {
#if defined(_WIN32)
    return (size_t)_getpid();
#else
    return (size_t)getpid();
#endif
}
size_t ehir_llvm_next_stage_id(void) {
    return atomic_fetch_add_explicit(&ehir_llvm_stage_sequence, 1, memory_order_relaxed);
}
