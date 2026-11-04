#ifndef ENCORE_SYNC_CHANNEL_H
#define ENCORE_SYNC_CHANNEL_H
#include "sync_runtime.h"
/* Type-erased payloads keep their monomorphized Encore destructor. A box may
 * be committed once, and taking its payload transfers ownership exactly once.
 */
typedef struct {
  encore_sync_header header;
  encore_sync_mutex mutex;
  size_t payload;
  void (*drop_payload)(size_t);
  uint32_t state;
} encore_sync_box;
static void encore_sync_box_destroy(encore_sync_header *h) {
  encore_sync_box *b = (encore_sync_box *)h;
  if (b->payload != 0)
    b->drop_payload(b->payload);
  encore_sync_mutex_destroy(&b->mutex);
  free(b);
}
size_t encore_sync_box_new(size_t payload, size_t dropper) {
  if (payload == 0 || dropper == 0)
    return 0;
  encore_sync_box *b = calloc(1, sizeof(*b));
  if (b == NULL)
    return 0;
  if (!encore_sync_mutex_init(&b->mutex)) {
    free(b);
    return 0;
  }
  encore_sync_header_init(&b->header, ENCORE_SYNC_BOX, encore_sync_box_destroy);
  b->payload = payload;
  b->drop_payload = (void (*)(size_t))(uintptr_t)dropper;
  return (size_t)(uintptr_t)b;
}
static size_t encore_sync_box_take_state(size_t token, uint32_t expected) {
  encore_sync_box *b = (encore_sync_box *)(uintptr_t)token;
  if (b == NULL)
    return 0;
  encore_sync_mutex_lock(&b->mutex);
  size_t value = b->state == expected ? b->payload : 0;
  if (value != 0) {
    b->payload = 0;
    b->state = 2;
  }
  encore_sync_mutex_unlock(&b->mutex);
  return value;
}
size_t encore_sync_box_take(size_t token) {
  return encore_sync_box_take_state(token, 0);
}
size_t encore_sync_box_take_received(size_t token) {
  return encore_sync_box_take_state(token, 3);
}
/* Only immutable Frozen[T] exposes borrowed copies. */
size_t encore_sync_box_peek(size_t token) {
  encore_sync_box *b = (encore_sync_box *)(uintptr_t)token;
  return b == NULL ? 0 : b->payload;
}
typedef struct {
  encore_sync_header header;
  encore_sync_mutex mutex;
  size_t capacity, count, first;
  encore_sync_box **items;
  bool send_closed, receive_closed;
  encore_sync_waiter *send_waiters, *receive_waiters;
} encore_sync_queue;
typedef struct {
  encore_sync_header header;
  encore_sync_queue *queue;
} encore_sync_endpoint;
static void encore_sync_queue_destroy(encore_sync_header *h) {
  encore_sync_queue *q = (encore_sync_queue *)h;
  for (size_t i = 0; i < q->count; ++i)
    encore_sync_release(
        (size_t)(uintptr_t)q->items[(q->first + i) % q->capacity]);
  free(q->items);
  encore_sync_mutex_destroy(&q->mutex);
  free(q);
}
size_t encore_sync_queue_new(size_t capacity) {
  if (capacity == 0 || capacity > SIZE_MAX / sizeof(encore_sync_box *))
    return 0;
  encore_sync_queue *q = calloc(1, sizeof(*q));
  if (q == NULL)
    return 0;
  q->items = calloc(capacity, sizeof(*q->items));
  if (q->items == NULL || !encore_sync_mutex_init(&q->mutex)) {
    free(q->items);
    free(q);
    return 0;
  }
  encore_sync_header_init(&q->header, ENCORE_SYNC_QUEUE,
                          encore_sync_queue_destroy);
  q->capacity = capacity;
  return (size_t)(uintptr_t)q;
}
static void encore_sync_endpoint_close_impl(encore_sync_endpoint *e) {
  encore_sync_queue *q = e->queue;
  encore_sync_mutex_lock(&q->mutex);
  if (e->header.kind == ENCORE_SYNC_SENDER)
    q->send_closed = true;
  else
    q->receive_closed = true;
  encore_sync_notify(&q->send_waiters);
  encore_sync_notify(&q->receive_waiters);
  encore_sync_mutex_unlock(&q->mutex);
  /* Remove under lock, run user destructors outside it. No sender can append
   * after receive_closed, and other closers safely share draining. */
  if (e->header.kind == ENCORE_SYNC_RECEIVER) {
    for (;;) {
      encore_sync_mutex_lock(&q->mutex);
      encore_sync_box *b = NULL;
      if (q->count != 0) {
        b = q->items[q->first];
        q->items[q->first] = NULL;
        q->first = (q->first + 1) % q->capacity;
        --q->count;
      }
      encore_sync_mutex_unlock(&q->mutex);
      if (b == NULL)
        break;
      encore_sync_release((size_t)(uintptr_t)b);
    }
  }
}
void encore_sync_endpoint_close(size_t token) {
  encore_sync_endpoint *e = (encore_sync_endpoint *)(uintptr_t)token;
  if (e != NULL)
    encore_sync_endpoint_close_impl(e);
}
static void encore_sync_endpoint_destroy(encore_sync_header *h) {
  encore_sync_endpoint *e = (encore_sync_endpoint *)h;
  encore_sync_endpoint_close_impl(e);
  encore_sync_release((size_t)(uintptr_t)e->queue);
  free(e);
}
size_t encore_sync_endpoint_new(size_t queue, bool sender) {
  encore_sync_queue *q = (encore_sync_queue *)(uintptr_t)queue;
  if (q == NULL)
    return 0;
  encore_sync_endpoint *e = calloc(1, sizeof(*e));
  if (e == NULL)
    return 0;
  encore_sync_header_init(&e->header,
                          sender ? ENCORE_SYNC_SENDER : ENCORE_SYNC_RECEIVER,
                          encore_sync_endpoint_destroy);
  e->queue = q;
  encore_sync_retain(queue);
  return (size_t)(uintptr_t)e;
}
/* Status: success, full/empty, closed, cancelled, already committed. */
uint32_t encore_sync_queue_send(size_t endpoint, size_t boxed, size_t cancel) {
  encore_sync_endpoint *e = (encore_sync_endpoint *)(uintptr_t)endpoint;
  encore_sync_box *b = (encore_sync_box *)(uintptr_t)boxed;
  if (e == NULL || b == NULL || e->header.kind != ENCORE_SYNC_SENDER)
    return 2;
  encore_sync_queue *q = e->queue;
  encore_sync_mutex_lock(&q->mutex);
  encore_sync_mutex_lock(&b->mutex);
  uint32_t result = b->state != 0
                        ? 4
                        : (q->receive_closed || q->send_closed
                               ? 2
                               : (cancel != 0 && encore_sync_cancelled(cancel)
                                      ? 3
                                      : (q->count == q->capacity ? 1 : 0)));
  if (result == 0) {
    b->state = 1;
    encore_sync_retain(boxed);
    q->items[(q->first + q->count) % q->capacity] = b;
    ++q->count;
    encore_sync_notify(&q->receive_waiters);
  }
  encore_sync_mutex_unlock(&b->mutex);
  encore_sync_mutex_unlock(&q->mutex);
  return result;
}
/* A received box owns its payload and is returned with one reference. */
size_t encore_sync_queue_receive(size_t endpoint) {
  encore_sync_endpoint *e = (encore_sync_endpoint *)(uintptr_t)endpoint;
  if (e == NULL || e->header.kind != ENCORE_SYNC_RECEIVER)
    return 0;
  encore_sync_queue *q = e->queue;
  encore_sync_mutex_lock(&q->mutex);
  encore_sync_box *b = NULL;
  if (q->count != 0 && !q->receive_closed) {
    b = q->items[q->first];
    q->items[q->first] = NULL;
    q->first = (q->first + 1) % q->capacity;
    --q->count;
    encore_sync_mutex_lock(&b->mutex);
    b->state = 3;
    encore_sync_mutex_unlock(&b->mutex);
    encore_sync_notify(&q->send_waiters);
  }
  encore_sync_mutex_unlock(&q->mutex);
  return (size_t)(uintptr_t)b;
}
bool encore_sync_queue_closed(size_t endpoint) {
  encore_sync_endpoint *e = (encore_sync_endpoint *)(uintptr_t)endpoint;
  if (e == NULL)
    return true;
  encore_sync_queue *q = e->queue;
  encore_sync_mutex_lock(&q->mutex);
  bool closed = q->receive_closed ||
                (q->send_closed &&
                 (e->header.kind == ENCORE_SYNC_SENDER || q->count == 0));
  encore_sync_mutex_unlock(&q->mutex);
  return closed;
}
size_t encore_sync_queue_register(size_t endpoint, size_t waker) {
  encore_sync_endpoint *e = (encore_sync_endpoint *)(uintptr_t)endpoint;
  if (e == NULL)
    return 0;
  encore_sync_queue *q = e->queue;
  bool sender = e->header.kind == ENCORE_SYNC_SENDER;
  encore_sync_mutex_lock(&q->mutex);
  bool ready = q->receive_closed || q->send_closed ||
               (sender ? q->count < q->capacity : q->count != 0);
  if (ready) {
    encore_sync_mutex_unlock(&q->mutex);
    return 0;
  }
  encore_sync_waiter *w = encore_sync_waiter_new(
      &e->header, &q->mutex, sender ? &q->send_waiters : &q->receive_waiters,
      waker);
  encore_sync_mutex_unlock(&q->mutex);
  return w == NULL ? SIZE_MAX : (size_t)(uintptr_t)w;
}
#endif
