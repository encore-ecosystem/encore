/* Native backends register process-lifetime cleanup hooks. An executor invokes
 * them before freeing its waker, after its root future has returned Ready. */
typedef void (*encore_async_cleanup_fn)(size_t);
static _Atomic(encore_async_cleanup_fn) encore_async_cleanup_hooks[16];

bool encore_async_register_waker_cleanup(encore_async_cleanup_fn hook) {
    if (hook == NULL) return false;
    for (size_t i = 0; i < 16; ++i) {
        encore_async_cleanup_fn current = atomic_load_explicit(&encore_async_cleanup_hooks[i], memory_order_acquire);
        if (current == hook) return true;
        if (current == NULL && atomic_compare_exchange_strong_explicit(
                &encore_async_cleanup_hooks[i], &current, hook,
                memory_order_acq_rel, memory_order_acquire)) return true;
        if (current == hook) return true;
    }
    return false;
}

static void encore_async_cleanup_waker(size_t token) {
    for (size_t i = 0; i < 16; ++i) {
        encore_async_cleanup_fn hook = atomic_load_explicit(&encore_async_cleanup_hooks[i], memory_order_acquire);
        if (hook != NULL) hook(token);
    }
}
