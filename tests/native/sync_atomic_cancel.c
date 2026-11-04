#include "../../packages/platform/owned_waker.h"
#include "../../packages/platform/sync_runtime.h"
#include <stdio.h>
uint64_t encore_clock_ns(uint8_t kind) {
  (void)kind;
  return 0;
}
static void *cancel_parent(void *argument) {
  encore_sync_cancel_request((size_t)(uintptr_t)argument);
  return NULL;
}
static void *increment(void *argument) {
  for (size_t i = 0; i < 100000; i++)
    encore_sync_atomic_fetch((size_t)(uintptr_t)argument, 1, 0);
  return NULL;
}
int main(void) {
  size_t value = encore_sync_atomic_new(0);
  pthread_t workers[4];
  for (size_t i = 0; i < 4; i++)
    pthread_create(&workers[i], NULL, increment, (void *)(uintptr_t)value);
  for (size_t i = 0; i < 4; i++)
    pthread_join(workers[i], NULL);
  if (encore_sync_atomic_load(value) != 400000)
    return 1;
  if (encore_sync_atomic_compare_exchange(value, 400000, 42) != 400000 ||
      encore_sync_atomic_load(value) != 42)
    return 2;
  encore_sync_release(value);
  for (size_t i = 0; i < 1000; i++) {
    size_t parent = encore_sync_cancel_new(0),
           child = encore_sync_cancel_new(parent),
           other = encore_sync_cancel_new(parent);
    pthread_t thread;
    pthread_create(&thread, NULL, cancel_parent, (void *)(uintptr_t)parent);
    if (!encore_sync_cancel_wait(child))
      return 3;
    pthread_join(thread, NULL);
    if (!encore_sync_cancelled(child) || !encore_sync_cancelled(other))
      return 4;
    encore_sync_release(parent);
    encore_sync_release(child);
    encore_sync_release(other);
  }
  size_t parent = encore_sync_cancel_new(0),
         child = encore_sync_cancel_new(parent);
  encore_sync_cancel_request(child);
  if (encore_sync_cancelled(parent))
    return 5;
  encore_sync_release(child);
  encore_sync_release(parent);
  size_t tail = encore_sync_cancel_new(0);
  for (size_t i = 0; i < 100000; i++) {
    size_t next = encore_sync_cancel_new(tail);
    encore_sync_release(tail);
    tail = next;
  }
  encore_sync_release(tail);
  if (encore_async_events != NULL || encore_sync_live_objects() != 0)
    return 6;
  puts("atomics and hierarchical cancellation races: passed");
  return 0;
}
