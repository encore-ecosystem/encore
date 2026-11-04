#ifndef ENCORE_SYNC_MUTEX_H
#define ENCORE_SYNC_MUTEX_H
#include "sync_channel.h"
typedef struct {
  encore_sync_header header;
  encore_sync_mutex mutex;
  encore_sync_box *slot;
  bool locked;
  uint64_t generation;
  encore_sync_waiter *waiters;
#ifdef _WIN32
  DWORD owner;
#else
  pthread_t owner;
#endif
} encore_sync_guarded;
typedef struct {
  encore_sync_header header;
  encore_sync_guarded *state;
  uint64_t generation;
  bool active;
} encore_sync_guard;
static bool encore_sync_guard_thread(encore_sync_guarded *m) {
#ifdef _WIN32
  return m->owner == GetCurrentThreadId();
#else
  return pthread_equal(m->owner, pthread_self());
#endif
}
static bool encore_sync_guard_valid(encore_sync_guard *g) {
  return g->active && g->state->locked &&
         g->generation == g->state->generation &&
         encore_sync_guard_thread(g->state);
}
static void encore_sync_guarded_destroy(encore_sync_header *h) {
  encore_sync_guarded *m = (encore_sync_guarded *)h;
  encore_sync_release((size_t)(uintptr_t)m->slot);
  encore_sync_mutex_destroy(&m->mutex);
  free(m);
}
size_t encore_sync_mutex_new(size_t boxed) {
  encore_sync_guarded *m = calloc(1, sizeof(*m));
  if (m == NULL)
    return 0;
  if (!encore_sync_mutex_init(&m->mutex)) {
    free(m);
    return 0;
  }
  encore_sync_header_init(&m->header, ENCORE_SYNC_MUTEX,
                          encore_sync_guarded_destroy);
  m->slot = (encore_sync_box *)(uintptr_t)boxed;
  encore_sync_retain(boxed);
  return (size_t)(uintptr_t)m;
}
void encore_sync_guard_close(size_t token) {
  encore_sync_guard *g = (encore_sync_guard *)(uintptr_t)token;
  if (g == NULL)
    return;
  encore_sync_guarded *m = g->state;
  encore_sync_mutex_lock(&m->mutex);
  if (encore_sync_guard_valid(g)) {
    g->active = false;
    m->locked = false;
    encore_sync_notify(&m->waiters);
  }
  encore_sync_mutex_unlock(&m->mutex);
}
static void encore_sync_guard_destroy(encore_sync_header *h) {
  encore_sync_guard *g = (encore_sync_guard *)h;
  encore_sync_guard_close((size_t)(uintptr_t)g);
  encore_sync_release((size_t)(uintptr_t)g->state);
  free(g);
}
/* 0=busy; SIZE_MAX=allocation/generation exhaustion; SIZE_MAX-1=reentrant. */
size_t encore_sync_mutex_acquire(size_t token) {
  encore_sync_guarded *m = (encore_sync_guarded *)(uintptr_t)token;
  if (m == NULL)
    return SIZE_MAX;
  encore_sync_mutex_lock(&m->mutex);
  if (m->locked) {
    bool own = encore_sync_guard_thread(m);
    encore_sync_mutex_unlock(&m->mutex);
    return own ? SIZE_MAX - 1 : 0;
  }
  if (m->generation == UINT64_MAX) {
    encore_sync_mutex_unlock(&m->mutex);
    return SIZE_MAX;
  }
  encore_sync_guard *g = calloc(1, sizeof(*g));
  if (g == NULL) {
    encore_sync_mutex_unlock(&m->mutex);
    return SIZE_MAX;
  }
  encore_sync_header_init(&g->header, ENCORE_SYNC_GUARD,
                          encore_sync_guard_destroy);
  m->locked = true;
  ++m->generation;
#ifdef _WIN32
  m->owner = GetCurrentThreadId();
#else
  m->owner = pthread_self();
#endif
  g->state = m;
  g->generation = m->generation;
  g->active = true;
  encore_sync_retain(token);
  encore_sync_mutex_unlock(&m->mutex);
  return (size_t)(uintptr_t)g;
}
size_t encore_sync_mutex_register(size_t token, size_t waker) {
  encore_sync_guarded *m = (encore_sync_guarded *)(uintptr_t)token;
  if (m == NULL)
    return 0;
  encore_sync_mutex_lock(&m->mutex);
  if (!m->locked) {
    encore_sync_mutex_unlock(&m->mutex);
    return 0;
  }
  encore_sync_waiter *w =
      encore_sync_waiter_new(&m->header, &m->mutex, &m->waiters, waker);
  encore_sync_mutex_unlock(&m->mutex);
  return w == NULL ? SIZE_MAX : (size_t)(uintptr_t)w;
}
bool encore_sync_guard_active(size_t token) {
  encore_sync_guard *g = (encore_sync_guard *)(uintptr_t)token;
  if (g == NULL)
    return false;
  encore_sync_mutex_lock(&g->state->mutex);
  bool valid = encore_sync_guard_valid(g);
  encore_sync_mutex_unlock(&g->state->mutex);
  return valid;
}
size_t encore_sync_guard_replace(size_t token, size_t boxed) {
  encore_sync_guard *g = (encore_sync_guard *)(uintptr_t)token;
  if (g == NULL)
    return 0;
  encore_sync_guarded *m = g->state;
  encore_sync_mutex_lock(&m->mutex);
  encore_sync_box *old = NULL;
  if (encore_sync_guard_valid(g)) {
    old = m->slot;
    m->slot = (encore_sync_box *)(uintptr_t)boxed;
    encore_sync_retain(boxed);
  }
  encore_sync_mutex_unlock(&m->mutex);
  return (size_t)(uintptr_t)old;
}
#endif
