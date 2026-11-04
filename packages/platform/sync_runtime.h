#ifndef ENCORE_SYNC_RUNTIME_H
#define ENCORE_SYNC_RUNTIME_H
#include <stdatomic.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#ifdef _WIN32
#include <windows.h>
typedef CRITICAL_SECTION encore_sync_mutex;
typedef CONDITION_VARIABLE encore_sync_condition;
static bool encore_sync_mutex_init(encore_sync_mutex *m) {
  InitializeCriticalSection(m);
  return true;
}
static void encore_sync_mutex_lock(encore_sync_mutex *m) {
  EnterCriticalSection(m);
}
static void encore_sync_mutex_unlock(encore_sync_mutex *m) {
  LeaveCriticalSection(m);
}
static void encore_sync_mutex_destroy(encore_sync_mutex *m) {
  DeleteCriticalSection(m);
}
static bool encore_sync_condition_init(encore_sync_condition *c) {
  InitializeConditionVariable(c);
  return true;
}
static void encore_sync_condition_notify(encore_sync_condition *c) {
  WakeAllConditionVariable(c);
}
static void encore_sync_condition_destroy(encore_sync_condition *c) { (void)c; }
#else
#include <errno.h>
#include <pthread.h>
#include <time.h>
typedef pthread_mutex_t encore_sync_mutex;
typedef pthread_cond_t encore_sync_condition;
static bool encore_sync_mutex_init(encore_sync_mutex *m) {
  return pthread_mutex_init(m, NULL) == 0;
}
static void encore_sync_mutex_lock(encore_sync_mutex *m) {
  pthread_mutex_lock(m);
}
static void encore_sync_mutex_unlock(encore_sync_mutex *m) {
  pthread_mutex_unlock(m);
}
static void encore_sync_mutex_destroy(encore_sync_mutex *m) {
  pthread_mutex_destroy(m);
}
static bool encore_sync_condition_init(encore_sync_condition *c) {
#if defined(__APPLE__)
  return pthread_cond_init(c, NULL) == 0;
#else
  pthread_condattr_t attr;
  if (pthread_condattr_init(&attr) != 0)
    return false;
  int status = pthread_condattr_setclock(&attr, CLOCK_MONOTONIC);
  if (status == 0)
    status = pthread_cond_init(c, &attr);
  pthread_condattr_destroy(&attr);
  return status == 0;
#endif
}
static void encore_sync_condition_notify(encore_sync_condition *c) {
  pthread_cond_broadcast(c);
}
static void encore_sync_condition_destroy(encore_sync_condition *c) {
  pthread_cond_destroy(c);
}
#endif
extern size_t encore_async_waker_new(void);
extern bool encore_async_waker_retain(size_t);
extern void encore_async_waker_release(size_t);
extern void encore_async_waker_wake(size_t);
extern void encore_async_waker_wait(size_t);
extern uint64_t encore_clock_ns(uint8_t);

typedef struct encore_sync_header encore_sync_header;
struct encore_sync_header {
  atomic_size_t references;
  uint32_t kind;
  void (*destroy)(encore_sync_header *);
};
enum {
  ENCORE_SYNC_ATOMIC = 1,
  ENCORE_SYNC_CANCEL,
  ENCORE_SYNC_WAITER,
  ENCORE_SYNC_WAIT_GROUP,
  ENCORE_SYNC_BOX,
  ENCORE_SYNC_QUEUE,
  ENCORE_SYNC_SENDER,
  ENCORE_SYNC_RECEIVER,
  ENCORE_SYNC_MUTEX,
  ENCORE_SYNC_GUARD,
  ENCORE_SYNC_WATCH,
  ENCORE_SYNC_WATCH_WRITER,
  ENCORE_SYNC_WATCH_READER,
  ENCORE_SYNC_CLOCK,
  ENCORE_SYNC_TIMER,
  ENCORE_SYNC_SIGNAL,
  ENCORE_SYNC_WATCH_SNAPSHOT,
  ENCORE_SYNC_HTTP_LEASE,
  ENCORE_SYNC_GROUP
};
static atomic_size_t encore_sync_live_count;
size_t encore_sync_live_objects(void) {
  return atomic_load(&encore_sync_live_count);
}
static void encore_sync_header_init(encore_sync_header *h, uint32_t kind,
                                    void (*destroy)(encore_sync_header *)) {
  atomic_init(&h->references, 1);
  h->kind = kind;
  h->destroy = destroy;
  atomic_fetch_add(&encore_sync_live_count, 1);
}
void encore_sync_retain(size_t token) {
  encore_sync_header *h = (encore_sync_header *)(uintptr_t)token;
  if (h != NULL)
    atomic_fetch_add_explicit(&h->references, 1, memory_order_relaxed);
}
void encore_sync_release(size_t token) {
  encore_sync_header *h = (encore_sync_header *)(uintptr_t)token;
  if (h != NULL &&
      atomic_fetch_sub_explicit(&h->references, 1, memory_order_acq_rel) == 1) {
    atomic_fetch_sub(&encore_sync_live_count, 1);
    h->destroy(h);
  }
}
static void encore_sync_plain_destroy(encore_sync_header *h) { free(h); }
typedef struct {
  encore_sync_header header;
  _Atomic uint64_t value;
} encore_sync_atomic;
size_t encore_sync_atomic_new(uint64_t value) {
  encore_sync_atomic *a = calloc(1, sizeof(*a));
  if (a == NULL)
    return 0;
  encore_sync_header_init(&a->header, ENCORE_SYNC_ATOMIC,
                          encore_sync_plain_destroy);
  atomic_init(&a->value, value);
  return (size_t)(uintptr_t)a;
}
static encore_sync_atomic *encore_sync_atomic_at(size_t token) {
  encore_sync_atomic *a = (encore_sync_atomic *)(uintptr_t)token;
  return a != NULL && a->header.kind == ENCORE_SYNC_ATOMIC ? a : NULL;
}
uint64_t encore_sync_atomic_load(size_t token) {
  encore_sync_atomic *a = encore_sync_atomic_at(token);
  return a == NULL ? 0 : atomic_load(&a->value);
}
void encore_sync_atomic_store(size_t token, uint64_t value) {
  encore_sync_atomic *a = encore_sync_atomic_at(token);
  if (a != NULL)
    atomic_store(&a->value, value);
}
uint64_t encore_sync_atomic_compare_exchange(size_t token, uint64_t expected,
                                             uint64_t desired) {
  encore_sync_atomic *a = encore_sync_atomic_at(token);
  if (a != NULL)
    atomic_compare_exchange_strong(&a->value, &expected, desired);
  return expected;
}
uint64_t encore_sync_atomic_fetch(size_t token, uint64_t value,
                                  uint32_t operation) {
  encore_sync_atomic *a = encore_sync_atomic_at(token);
  if (a == NULL)
    return 0;
  switch (operation) {
  case 0:
    return atomic_fetch_add(&a->value, value);
  case 1:
    return atomic_fetch_sub(&a->value, value);
  case 2:
    return atomic_fetch_and(&a->value, value);
  case 3:
    return atomic_fetch_or(&a->value, value);
  case 4:
    return atomic_fetch_xor(&a->value, value);
  case 5:
    return atomic_exchange(&a->value, value);
  default:
    return 0;
  }
}

typedef struct encore_sync_waiter encore_sync_waiter;
struct encore_sync_waiter {
  encore_sync_header header;
  encore_sync_header *owner;
  encore_sync_mutex *mutex;
  encore_sync_waiter **head;
  encore_sync_waiter *next;
  size_t waker;
  bool linked;
};
static void encore_sync_waiter_destroy(encore_sync_header *h) {
  encore_sync_waiter *w = (encore_sync_waiter *)h;
  encore_sync_mutex_lock(w->mutex);
  if (w->linked) {
    encore_sync_waiter **slot = w->head;
    while (*slot != NULL && *slot != w)
      slot = &(*slot)->next;
    if (*slot == w)
      *slot = w->next;
    w->linked = false;
  }
  encore_sync_mutex_unlock(w->mutex);
  encore_async_waker_release(w->waker);
  encore_sync_release((size_t)(uintptr_t)w->owner);
  free(w);
}
/* Caller holds the owner's mutex. The registration owns both the owner and
 * event, and its destructor always unlinks under that same mutex. */
static encore_sync_waiter *encore_sync_waiter_new(encore_sync_header *owner,
                                                  encore_sync_mutex *mutex,
                                                  encore_sync_waiter **head,
                                                  size_t waker) {
  encore_sync_waiter *w = calloc(1, sizeof(*w));
  if (w == NULL)
    return NULL;
  if (!encore_async_waker_retain(waker)) {
    free(w);
    return NULL;
  }
  encore_sync_retain((size_t)(uintptr_t)owner);
  encore_sync_header_init(&w->header, ENCORE_SYNC_WAITER,
                          encore_sync_waiter_destroy);
  w->owner = owner;
  w->mutex = mutex;
  w->head = head;
  w->waker = waker;
  w->linked = true;
  w->next = *head;
  *head = w;
  return w;
}
static void encore_sync_notify(encore_sync_waiter **head) {
  encore_sync_waiter *w = *head;
  *head = NULL;
  while (w != NULL) {
    encore_sync_waiter *next = w->next;
    w->linked = false;
    encore_async_waker_wake(w->waker);
    w = next;
  }
}

typedef struct encore_sync_cancel {
  encore_sync_header header;
  encore_sync_mutex mutex;
  atomic_bool cancelled;
  struct encore_sync_cancel *parent;
  encore_sync_waiter *waiters;
} encore_sync_cancel;
static void encore_sync_cancel_destroy(encore_sync_header *h) {
  encore_sync_cancel *c = (encore_sync_cancel *)h;
  for (;;) {
    encore_sync_cancel *parent = c->parent;
    encore_sync_mutex_destroy(&c->mutex);
    free(c);
    if (parent == NULL ||
        atomic_fetch_sub_explicit(&parent->header.references, 1,
                                  memory_order_acq_rel) != 1)
      break;
    atomic_fetch_sub(&encore_sync_live_count, 1);
    c = parent;
  }
}
size_t encore_sync_cancel_new(size_t parent) {
  encore_sync_cancel *p = (encore_sync_cancel *)(uintptr_t)parent;
  if (p != NULL && p->header.kind != ENCORE_SYNC_CANCEL)
    return 0;
  encore_sync_cancel *c = calloc(1, sizeof(*c));
  if (c == NULL)
    return 0;
  if (!encore_sync_mutex_init(&c->mutex)) {
    free(c);
    return 0;
  }
  encore_sync_header_init(&c->header, ENCORE_SYNC_CANCEL,
                          encore_sync_cancel_destroy);
  atomic_init(&c->cancelled, false);
  c->parent = p;
  encore_sync_retain(parent);
  return (size_t)(uintptr_t)c;
}
bool encore_sync_cancelled(size_t token) {
  encore_sync_cancel *c = (encore_sync_cancel *)(uintptr_t)token;
  while (c != NULL) {
    if (c->header.kind != ENCORE_SYNC_CANCEL)
      return false;
    if (atomic_load(&c->cancelled))
      return true;
    c = c->parent;
  }
  return false;
}
void encore_sync_cancel_request(size_t token) {
  encore_sync_cancel *c = (encore_sync_cancel *)(uintptr_t)token;
  if (c == NULL || c->header.kind != ENCORE_SYNC_CANCEL ||
      atomic_exchange(&c->cancelled, true))
    return;
  encore_sync_mutex_lock(&c->mutex);
  encore_sync_notify(&c->waiters);
  encore_sync_mutex_unlock(&c->mutex);
}
typedef struct {
  encore_sync_header header;
  size_t count;
  encore_sync_waiter **items;
} encore_sync_wait_group;
static void encore_sync_wait_group_destroy(encore_sync_header *h) {
  encore_sync_wait_group *g = (encore_sync_wait_group *)h;
  for (size_t i = 0; i < g->count; ++i)
    encore_sync_release((size_t)(uintptr_t)g->items[i]);
  free(g->items);
  free(g);
}
/* 0 means ready; SIZE_MAX means allocation failure. Other values are owned
 * registrations. Ancestors are immutable and retained by their children. */
size_t encore_sync_cancel_register(size_t token, size_t waker) {
  if (encore_sync_cancelled(token))
    return 0;
  size_t count = 0;
  for (encore_sync_cancel *c = (encore_sync_cancel *)(uintptr_t)token;
       c != NULL; c = c->parent) {
    if (c->header.kind != ENCORE_SYNC_CANCEL ||
        count == SIZE_MAX / sizeof(encore_sync_waiter *))
      return SIZE_MAX;
    ++count;
  }
  encore_sync_wait_group *g = calloc(1, sizeof(*g));
  if (g == NULL)
    return SIZE_MAX;
  g->items = calloc(count == 0 ? 1 : count, sizeof(*g->items));
  if (g->items == NULL) {
    free(g);
    return SIZE_MAX;
  }
  encore_sync_header_init(&g->header, ENCORE_SYNC_WAIT_GROUP,
                          encore_sync_wait_group_destroy);
  for (encore_sync_cancel *c = (encore_sync_cancel *)(uintptr_t)token;
       c != NULL; c = c->parent) {
    encore_sync_mutex_lock(&c->mutex);
    if (atomic_load(&c->cancelled)) {
      encore_sync_mutex_unlock(&c->mutex);
      encore_sync_release((size_t)(uintptr_t)g);
      return 0;
    }
    encore_sync_waiter *w =
        encore_sync_waiter_new(&c->header, &c->mutex, &c->waiters, waker);
    encore_sync_mutex_unlock(&c->mutex);
    if (w == NULL) {
      encore_sync_release((size_t)(uintptr_t)g);
      return SIZE_MAX;
    }
    g->items[g->count++] = w;
  }
  if (encore_sync_cancelled(token)) {
    encore_sync_release((size_t)(uintptr_t)g);
    return 0;
  }
  return (size_t)(uintptr_t)g;
}
bool encore_sync_cancel_wait(size_t token) {
  while (!encore_sync_cancelled(token)) {
    size_t waker = encore_async_waker_new();
    if (waker == 0)
      return false;
    size_t registration = encore_sync_cancel_register(token, waker);
    if (registration != 0 && registration != SIZE_MAX)
      encore_async_waker_wait(waker);
    if (registration != SIZE_MAX)
      encore_sync_release(registration);
    encore_async_waker_release(waker);
    if (registration == SIZE_MAX)
      return false;
  }
  return true;
}
#endif
