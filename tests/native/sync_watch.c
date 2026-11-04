#include "../../packages/platform/sync_watch.h"
#include "../../packages/platform/owned_waker.h"
#include <stdio.h>
static void drop(size_t p) { free((void *)(uintptr_t)p); }
static size_t box(int value) {
  int *p = malloc(sizeof(*p));
  *p = value;
  return encore_sync_box_new((size_t)(uintptr_t)p, (size_t)(uintptr_t)drop);
}
static void *publish_many(void *raw) {
  size_t writer = (size_t)(uintptr_t)raw;
  for (int i = 0; i < 1000; ++i) {
    size_t value = box(i);
    if (encore_sync_watch_publish(writer, value))
      abort();
    encore_sync_release(value);
  }
  return NULL;
}
int main(void) {
  size_t b = box(0), w = encore_sync_watch_new(b),
         writer = encore_sync_watch_endpoint_new(w, true),
         reader = encore_sync_watch_endpoint_new(w, false);
  encore_sync_release(b);
  encore_sync_release(w);
  size_t old = encore_sync_watch_snapshot(reader, 0, true),
         event = encore_async_waker_new(),
         reg = encore_sync_watch_register(reader, 0, event);
  for (int i = 1; i < 1000; i++) {
    b = box(i);
    if (encore_sync_watch_publish(writer, b))
      return 1;
    encore_sync_release(b);
  }
  encore_async_waker_wait(event);
  encore_sync_release(reg);
  size_t latest = encore_sync_watch_snapshot(reader, 0, false);
  if (encore_sync_watch_read_version(old) != 0 ||
      encore_sync_watch_read_version(latest) != 999)
    return 2;
  b = encore_sync_watch_read_box(old);
  if (*(int *)(uintptr_t)encore_sync_box_peek(b) != 0)
    return 3;
  encore_sync_release(b);
  encore_sync_release(old);
  encore_sync_release(latest);
  pthread_t left, right;
  pthread_create(&left, NULL, publish_many, (void *)(uintptr_t)writer);
  pthread_create(&right, NULL, publish_many, (void *)(uintptr_t)writer);
  pthread_join(left, NULL);
  pthread_join(right, NULL);
  size_t concurrent = encore_sync_watch_snapshot(reader, 0, true);
  if (encore_sync_watch_read_version(concurrent) != 2999)
    return 6;
  encore_sync_release(concurrent);
  encore_sync_watch *state =
      ((encore_sync_watch_endpoint *)(uintptr_t)writer)->watch;
  state->version = UINT64_MAX;
  b = box(42);
  if (encore_sync_watch_publish(writer, b) != 2)
    return 7;
  encore_sync_release(b);
  encore_sync_release(writer);
  if (!encore_sync_watch_closed(reader) ||
      encore_sync_watch_register(reader, 999, event))
    return 4;
  encore_sync_release(reader);
  encore_async_waker_release(event);
  if (encore_sync_live_objects() || encore_async_events)
    return 5;
  puts("watch coalescing, stable snapshots, versions and writer close: passed");
  return 0;
}
