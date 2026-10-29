#include <stddef.h>
#include <stdatomic.h>
#if defined(_WIN32)
#include <process.h>
#else
#include <unistd.h>
#endif
size_t ehir_compiler_process_id(void) {
#if defined(_WIN32)
    return (size_t)_getpid();
#else
    return (size_t)getpid();
#endif
}

static _Atomic size_t ehir_stage_sequence = 0;
size_t ehir_compiler_next_stage_id(void) {
    return atomic_fetch_add_explicit(&ehir_stage_sequence, 1, memory_order_relaxed);
}
