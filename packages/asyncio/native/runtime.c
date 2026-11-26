#include <stddef.h>
#include <stdint.h>

typedef size_t (*asyncio_poll_fn)(size_t, size_t);
typedef void (*asyncio_drop_fn)(size_t);

#if defined(_MSC_VER)
__declspec(thread) static size_t current_runtime;
#else
static _Thread_local size_t current_runtime;
#endif

size_t encore_asyncio_current(void) {
    return current_runtime;
}

size_t encore_asyncio_set_current(size_t payload) {
    size_t previous = current_runtime;
    current_runtime = payload;
    return previous;
}

size_t encore_asyncio_poll(uintptr_t callback, size_t payload, size_t waker) {
    return ((asyncio_poll_fn)callback)(payload, waker);
}

void encore_asyncio_drop(uintptr_t callback, size_t payload) {
    ((asyncio_drop_fn)callback)(payload);
}
