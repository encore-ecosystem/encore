#include "../../packages/platform/sync_channel.h"
#include "../../packages/platform/owned_waker.h"
#include <stdio.h>
static atomic_size_t dropped;
static void drop_value(size_t p) {
  free((void *)(uintptr_t)p);
  atomic_fetch_add(&dropped, 1);
}
static size_t box(size_t n) {
  size_t *p = malloc(sizeof(*p));
  *p = n;
  return encore_sync_box_new((size_t)(uintptr_t)p,
                             (size_t)(uintptr_t)drop_value);
}
static void *produce(void *arg) {
  size_t sender = (size_t)(uintptr_t)arg;
  for (size_t i = 0; i < 1000; i++) {
    size_t b = box(i), w = encore_async_waker_new();
    while (encore_sync_queue_send(sender, b, 0) == 1) {
      size_t reg = encore_sync_queue_register(sender, w);
      if (reg && reg != SIZE_MAX)
        encore_async_waker_wait(w);
      encore_sync_release(reg);
    }
    encore_async_waker_release(w);
    encore_sync_release(b);
  }
  encore_sync_release(sender);
  return NULL;
}
int main(void) {
  for (size_t repeat = 0; repeat < 10; repeat++) {
    size_t q = encore_sync_queue_new(3), s = encore_sync_endpoint_new(q, true),
           r = encore_sync_endpoint_new(q, false);
    encore_sync_release(q);
    pthread_t ts[4];
    for (size_t i = 0; i < 4; i++) {
      encore_sync_retain(s);
      pthread_create(&ts[i], NULL, produce, (void *)(uintptr_t)s);
    }
    size_t sum = 0, w = encore_async_waker_new();
    for (size_t i = 0; i < 4000; i++) {
      size_t b;
      while (!(b = encore_sync_queue_receive(r))) {
        size_t reg = encore_sync_queue_register(r, w);
        if (reg && reg != SIZE_MAX)
          encore_async_waker_wait(w);
        encore_sync_release(reg);
      }
      size_t p = encore_sync_box_take_received(b);
      if (!p || encore_sync_box_take(b))
        return 1;
      sum += *(size_t *)(uintptr_t)p;
      drop_value(p);
      encore_sync_release(b);
    }
    if (sum != 4 * 999 * 500)
      return 2;
    for (size_t i = 0; i < 4; i++)
      pthread_join(ts[i], NULL);
    size_t b = box(42);
    if (encore_sync_queue_send(s, b, 0))
      return 3;
    if (encore_sync_queue_send(s, b, 0) != 4)
      return 4;
    size_t received = encore_sync_queue_receive(r);
    if (received != b || encore_sync_queue_send(s, b, 0) != 4)
      return 5;
    if (encore_sync_box_take(b))
      return 10;
    size_t payload = encore_sync_box_take_received(received);
    drop_value(payload);
    encore_sync_release(received);
    encore_sync_release(b);
    b = box(7);
    encore_sync_queue_send(s, b, 0);
    encore_sync_release(b);
    encore_sync_release(r);
    if (!encore_sync_queue_closed(s))
      return 6;
    b = box(9);
    if (encore_sync_queue_send(s, b, 0) != 2)
      return 7;
    encore_sync_release(b);
    encore_sync_release(s);
    encore_async_waker_release(w);
  }
  if (encore_sync_live_objects() != 0 || encore_async_events != NULL)
    return 8;
  if (atomic_load(&dropped) != 40030)
    return 9;
  puts("bounded MPSC, exact transfer, backpressure and close: passed");
  return 0;
}
