#ifndef ENCORE_SYNC_WATCH_H
#define ENCORE_SYNC_WATCH_H
#include "sync_channel.h"
typedef struct {
  encore_sync_header header;
  encore_sync_mutex mutex;
  encore_sync_box *latest;
  uint64_t version;
  bool closed;
  encore_sync_waiter *waiters;
} encore_sync_watch;
typedef struct {
  encore_sync_header header;
  encore_sync_watch *watch;
} encore_sync_watch_endpoint;
typedef struct {
  encore_sync_header header;
  encore_sync_box *boxed;
  uint64_t version;
} encore_sync_watch_read;
static void encore_sync_watch_destroy(encore_sync_header *h) {
  encore_sync_watch *w = (encore_sync_watch *)h;
  encore_sync_release((size_t)(uintptr_t)w->latest);
  encore_sync_mutex_destroy(&w->mutex);
  free(w);
}
size_t encore_sync_watch_new(size_t boxed) {
  if (!boxed)
    return 0;
  encore_sync_watch *w = calloc(1, sizeof(*w));
  if (!w)
    return 0;
  if (!encore_sync_mutex_init(&w->mutex)) {
    free(w);
    return 0;
  }
  encore_sync_header_init(&w->header, ENCORE_SYNC_WATCH,
                          encore_sync_watch_destroy);
  w->latest = (encore_sync_box *)(uintptr_t)boxed;
  encore_sync_retain(boxed);
  return (size_t)(uintptr_t)w;
}
void encore_sync_watch_close(size_t endpoint) {
  encore_sync_watch_endpoint *e =
      (encore_sync_watch_endpoint *)(uintptr_t)endpoint;
  if (!e)
    return;
  encore_sync_mutex_lock(&e->watch->mutex);
  e->watch->closed = true;
  encore_sync_notify(&e->watch->waiters);
  encore_sync_mutex_unlock(&e->watch->mutex);
}
static void encore_sync_watch_endpoint_destroy(encore_sync_header *h) {
  encore_sync_watch_endpoint *e = (encore_sync_watch_endpoint *)h;
  if (h->kind == ENCORE_SYNC_WATCH_WRITER)
    encore_sync_watch_close((size_t)(uintptr_t)e);
  encore_sync_release((size_t)(uintptr_t)e->watch);
  free(e);
}
size_t encore_sync_watch_endpoint_new(size_t token, bool writer) {
  encore_sync_watch *w = (encore_sync_watch *)(uintptr_t)token;
  if (!w)
    return 0;
  encore_sync_watch_endpoint *e = calloc(1, sizeof(*e));
  if (!e)
    return 0;
  encore_sync_header_init(
      &e->header, writer ? ENCORE_SYNC_WATCH_WRITER : ENCORE_SYNC_WATCH_READER,
      encore_sync_watch_endpoint_destroy);
  e->watch = w;
  encore_sync_retain(token);
  return (size_t)(uintptr_t)e;
}
/* Closed/overflow never discard the supplied snapshot. */
uint32_t encore_sync_watch_publish(size_t endpoint, size_t boxed) {
  encore_sync_watch_endpoint *e =
      (encore_sync_watch_endpoint *)(uintptr_t)endpoint;
  if (!e || e->header.kind != ENCORE_SYNC_WATCH_WRITER || !boxed)
    return 1;
  encore_sync_watch *w = e->watch;
  encore_sync_mutex_lock(&w->mutex);
  uint32_t status = w->closed ? 1 : (w->version == UINT64_MAX ? 2 : 0);
  encore_sync_box *old = NULL;
  if (!status) {
    old = w->latest;
    w->latest = (encore_sync_box *)(uintptr_t)boxed;
    encore_sync_retain(boxed);
    ++w->version;
    encore_sync_notify(&w->waiters);
  }
  encore_sync_mutex_unlock(&w->mutex);
  encore_sync_release((size_t)(uintptr_t)old);
  return status;
}
static void encore_sync_watch_read_destroy(encore_sync_header *h) {
  encore_sync_watch_read *r = (encore_sync_watch_read *)h;
  encore_sync_release((size_t)(uintptr_t)r->boxed);
  free(r);
}
size_t encore_sync_watch_snapshot(size_t endpoint, uint64_t after,
                                  bool current) {
  encore_sync_watch_endpoint *e =
      (encore_sync_watch_endpoint *)(uintptr_t)endpoint;
  if (!e)
    return 0;
  encore_sync_watch *w = e->watch;
  encore_sync_mutex_lock(&w->mutex);
  if (!current && w->version == after) {
    encore_sync_mutex_unlock(&w->mutex);
    return 0;
  }
  encore_sync_watch_read *r = calloc(1, sizeof(*r));
  if (!r) {
    encore_sync_mutex_unlock(&w->mutex);
    return SIZE_MAX;
  }
  encore_sync_header_init(&r->header, ENCORE_SYNC_WATCH_SNAPSHOT,
                          encore_sync_watch_read_destroy);
  r->boxed = w->latest;
  r->version = w->version;
  encore_sync_retain((size_t)(uintptr_t)r->boxed);
  encore_sync_mutex_unlock(&w->mutex);
  return (size_t)(uintptr_t)r;
}
uint64_t encore_sync_watch_read_version(size_t token) {
  encore_sync_watch_read *r = (encore_sync_watch_read *)(uintptr_t)token;
  return r ? r->version : 0;
}
size_t encore_sync_watch_read_box(size_t token) {
  encore_sync_watch_read *r = (encore_sync_watch_read *)(uintptr_t)token;
  if (!r)
    return 0;
  encore_sync_retain((size_t)(uintptr_t)r->boxed);
  return (size_t)(uintptr_t)r->boxed;
}
bool encore_sync_watch_closed(size_t endpoint) {
  encore_sync_watch_endpoint *e =
      (encore_sync_watch_endpoint *)(uintptr_t)endpoint;
  if (!e)
    return true;
  encore_sync_mutex_lock(&e->watch->mutex);
  bool closed = e->watch->closed;
  encore_sync_mutex_unlock(&e->watch->mutex);
  return closed;
}
size_t encore_sync_watch_register(size_t endpoint, uint64_t after,
                                  size_t waker) {
  encore_sync_watch_endpoint *e =
      (encore_sync_watch_endpoint *)(uintptr_t)endpoint;
  if (!e)
    return 0;
  encore_sync_watch *w = e->watch;
  encore_sync_mutex_lock(&w->mutex);
  if (w->closed || w->version != after) {
    encore_sync_mutex_unlock(&w->mutex);
    return 0;
  }
  encore_sync_waiter *waiter =
      encore_sync_waiter_new(&e->header, &w->mutex, &w->waiters, waker);
  encore_sync_mutex_unlock(&w->mutex);
  return waiter ? (size_t)(uintptr_t)waiter : SIZE_MAX;
}
#endif
