#include "../../packages/platform/sync_mutex.h"
#include "../../packages/platform/owned_waker.h"
#include <stdio.h>
static void drop(size_t p) { free((void *)(uintptr_t)p); }
static size_t boxed(void) {
  return encore_sync_box_new((size_t)(uintptr_t)malloc(4),
                             (size_t)(uintptr_t)drop);
}
static void *worker(void *arg) {
  size_t m = (size_t)(uintptr_t)arg;
  size_t w = encore_async_waker_new(), g;
  while (!(g = encore_sync_mutex_acquire(m))) {
    size_t reg = encore_sync_mutex_register(m, w);
    if (reg && reg != SIZE_MAX)
      encore_async_waker_wait(w);
    encore_sync_release(reg);
  }
  if (g >= SIZE_MAX - 1)
    abort();
  size_t old = encore_sync_guard_replace(g, 0);
  if (!old)
    abort();
  encore_sync_release(old);
  encore_sync_release(g);
  encore_async_waker_release(w);
  return NULL;
}
int main(void) {
  size_t b = boxed(), m = encore_sync_mutex_new(b);
  encore_sync_release(b);
  size_t g = encore_sync_mutex_acquire(m);
  if (!g || encore_sync_mutex_acquire(m) != SIZE_MAX - 1)
    return 1;
  pthread_t thread;
  pthread_create(&thread, NULL, worker, (void *)(uintptr_t)m);
  encore_sync_guard_close(g);
  if (encore_sync_guard_active(g))
    return 2;
  pthread_join(thread, NULL);
  encore_sync_release(g);
  encore_sync_release(m);
  if (encore_sync_live_objects() || encore_async_events)
    return 3;
  puts("guard ownership, wake on unlock and stale guard rejection: passed");
  return 0;
}
