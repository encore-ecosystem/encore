#ifndef ENCORE_SYNC_GROUP_H
#define ENCORE_SYNC_GROUP_H
#include "sync_channel.h"
/* The typed worker bundle stays owned by the group. Only its creating thread
 * may temporarily take it while executing an SDK operation. Final drop closes
 * queues and cancels before its Encore destructor joins the workers. */
typedef struct {
  encore_sync_header header;
  encore_sync_mutex mutex;
  size_t cancellation, receiver, capacity, count, *senders, payload;
  void (*drop_payload)(size_t);
  bool closing, busy;
#ifdef _WIN32
  DWORD owner;
#else
  pthread_t owner;
#endif
} encore_sync_group;
static bool encore_sync_group_owner(encore_sync_group *g) {
#ifdef _WIN32
  return g->owner == GetCurrentThreadId();
#else
  return pthread_equal(g->owner, pthread_self());
#endif
}
void encore_sync_group_close(size_t token) {
  encore_sync_group *g = (encore_sync_group *)(uintptr_t)token;
  if (!g)
    return;
  encore_sync_mutex_lock(&g->mutex);
  bool close = !g->closing;
  g->closing = true;
  encore_sync_mutex_unlock(&g->mutex);
  if (close) {
    encore_sync_cancel_request(g->cancellation);
    for (size_t i = 0; i < g->count; i++)
      encore_sync_endpoint_close(g->senders[i]);
    encore_sync_endpoint_close(g->receiver);
  }
}
static void encore_sync_group_destroy(encore_sync_header *h) {
  encore_sync_group *g = (encore_sync_group *)h;
  encore_sync_group_close((size_t)(uintptr_t)g);
  if (g->payload)
    g->drop_payload(g->payload);
  for (size_t i = 0; i < g->count; i++)
    encore_sync_release(g->senders[i]);
  encore_sync_release(g->receiver);
  encore_sync_release(g->cancellation);
  free(g->senders);
  encore_sync_mutex_destroy(&g->mutex);
  free(g);
}
size_t encore_sync_group_new(size_t cancel, size_t receiver, size_t workers,
                             size_t dropper) {
  if (!cancel || !receiver || !workers || workers > 256 || !dropper)
    return 0;
  encore_sync_group *g = calloc(1, sizeof(*g));
  if (!g)
    return 0;
  g->senders = calloc(workers, sizeof(size_t));
  if (!g->senders || !encore_sync_mutex_init(&g->mutex)) {
    free(g->senders);
    free(g);
    return 0;
  }
  encore_sync_header_init(&g->header, ENCORE_SYNC_GROUP,
                          encore_sync_group_destroy);
  g->cancellation = cancel;
  g->receiver = receiver;
  g->capacity = workers;
  g->drop_payload = (void (*)(size_t))(uintptr_t)dropper;
  encore_sync_retain(cancel);
  encore_sync_retain(receiver);
#ifdef _WIN32
  g->owner = GetCurrentThreadId();
#else
  g->owner = pthread_self();
#endif
  return (size_t)(uintptr_t)g;
}
bool encore_sync_group_add_sender(size_t token, size_t sender) {
  encore_sync_group *g = (encore_sync_group *)(uintptr_t)token;
  if (!g || !sender || !encore_sync_group_owner(g) || g->count == g->capacity ||
      g->payload)
    return false;
  g->senders[g->count++] = sender;
  encore_sync_retain(sender);
  return true;
}
size_t encore_sync_group_take(size_t token) {
  encore_sync_group *g = (encore_sync_group *)(uintptr_t)token;
  if (!g || !encore_sync_group_owner(g))
    return SIZE_MAX;
  encore_sync_mutex_lock(&g->mutex);
  size_t p = g->busy ? SIZE_MAX : g->payload;
  if (p && p != SIZE_MAX) {
    g->payload = 0;
    g->busy = true;
  }
  encore_sync_mutex_unlock(&g->mutex);
  return p;
}
bool encore_sync_group_put(size_t token, size_t payload) {
  encore_sync_group *g = (encore_sync_group *)(uintptr_t)token;
  if (!g || !payload || !encore_sync_group_owner(g))
    return false;
  encore_sync_mutex_lock(&g->mutex);
  bool valid = g->payload == 0;
  if (valid) {
    g->payload = payload;
    g->busy = false;
  }
  encore_sync_mutex_unlock(&g->mutex);
  return valid;
}
/* Wait for capacity on any worker queue or a completion to drain. */
size_t encore_sync_group_register(size_t token, size_t waker,
                                  bool completions_only) {
  encore_sync_group *g = (encore_sync_group *)(uintptr_t)token;
  if (!g)
    return 0;
  size_t count = completions_only ? 1 : g->count + 2;
  encore_sync_wait_group *r = calloc(1, sizeof(*r));
  if (!r)
    return SIZE_MAX;
  r->items = calloc(count, sizeof(*r->items));
  if (!r->items) {
    free(r);
    return SIZE_MAX;
  }
  encore_sync_header_init(&r->header, ENCORE_SYNC_WAIT_GROUP,
                          encore_sync_wait_group_destroy);
  for (size_t i = 0; i < count; i++) {
    size_t reg = (!completions_only && i == count - 1)
                     ? encore_sync_cancel_register(g->cancellation, waker)
                     : encore_sync_queue_register(
                           i == 0 ? g->receiver : g->senders[i - 1], waker);
    if (reg == 0 || reg == SIZE_MAX) {
      encore_sync_release((size_t)(uintptr_t)r);
      return reg;
    }
    r->items[r->count++] = (encore_sync_waiter *)(uintptr_t)reg;
  }
  return (size_t)(uintptr_t)r;
}
#endif
