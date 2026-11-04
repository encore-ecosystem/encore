#ifndef ENCORE_SYNC_TIME_H
#define ENCORE_SYNC_TIME_H
#include "sync_runtime.h"

typedef struct encore_sync_clock encore_sync_clock;
typedef struct encore_sync_timer {
  encore_sync_header header;
  encore_sync_clock *clock;
  uint64_t deadline;
  uint32_t status; /* pending, elapsed, cancelled, clock closed */
  bool linked;
  struct encore_sync_timer *next;
  encore_sync_waiter *waiters;
} encore_sync_timer;
struct encore_sync_clock {
  encore_sync_header header;
  encore_sync_mutex mutex;
  encore_sync_condition condition;
  uint64_t domain, virtual_now;
  bool virtual_time, closed, started, joining, joined;
  encore_sync_timer *timers;
#ifdef _WIN32
  HANDLE thread;
#else
  pthread_t thread;
#endif
};
static _Atomic uint64_t encore_sync_next_clock = 1;
static uint64_t encore_sync_clock_read(encore_sync_clock *c) {
  return c->virtual_time ? c->virtual_now : encore_clock_ns(1);
}
static void encore_sync_condition_wait(encore_sync_condition *condition,
                                       encore_sync_mutex *mutex,
                                       uint64_t deadline, bool infinite) {
#ifdef _WIN32
  DWORD delay = INFINITE;
  if (!infinite) {
    uint64_t now = encore_clock_ns(1),
             delta = deadline > now ? deadline - now : 0;
    uint64_t ms = delta / 1000000 + (delta % 1000000 != 0);
    delay = ms >= INFINITE ? INFINITE - 1 : (DWORD)ms;
  }
  SleepConditionVariableCS(condition, mutex, delay);
#else
  if (infinite) {
    pthread_cond_wait(condition, mutex);
    return;
  }
#if defined(__APPLE__)
  uint64_t now = encore_clock_ns(1),
           delta = deadline > now ? deadline - now : 0;
  struct timespec timeout = {(time_t)(delta / 1000000000),
                             (long)(delta % 1000000000)};
  pthread_cond_timedwait_relative_np(condition, mutex, &timeout);
#else
  struct timespec timeout = {(time_t)(deadline / 1000000000),
                             (long)(deadline % 1000000000)};
  pthread_cond_timedwait(condition, mutex, &timeout);
#endif
#endif
}
static void encore_sync_clock_fire(encore_sync_clock *c) {
  uint64_t now = encore_sync_clock_read(c);
  while (c->timers != NULL && c->timers->deadline <= now) {
    encore_sync_timer *t = c->timers;
    c->timers = t->next;
    t->next = NULL;
    t->linked = false;
    t->status = 1;
    encore_sync_notify(&t->waiters);
  }
}
#ifdef _WIN32
static DWORD WINAPI encore_sync_clock_worker(void *argument) {
#else
static void *encore_sync_clock_worker(void *argument) {
#endif
  encore_sync_clock *c = argument;
  encore_sync_mutex_lock(&c->mutex);
  while (!c->closed) {
    encore_sync_clock_fire(c);
    if (c->closed)
      break;
    encore_sync_condition_wait(&c->condition, &c->mutex,
                               c->timers == NULL ? 0 : c->timers->deadline,
                               c->timers == NULL);
  }
  encore_sync_mutex_unlock(&c->mutex);
#ifdef _WIN32
  return 0;
#else
  return NULL;
#endif
}
void encore_sync_clock_close(size_t token) {
  encore_sync_clock *c = (encore_sync_clock *)(uintptr_t)token;
  if (c == NULL || c->header.kind != ENCORE_SYNC_CLOCK)
    return;
  encore_sync_mutex_lock(&c->mutex);
  if (!c->closed) {
    c->closed = true;
    encore_sync_timer *t = c->timers;
    c->timers = NULL;
    while (t != NULL) {
      encore_sync_timer *next = t->next;
      t->next = NULL;
      t->linked = false;
      t->status = 3;
      encore_sync_notify(&t->waiters);
      t = next;
    }
    encore_sync_condition_notify(&c->condition);
  }
  bool join_here = c->started && !c->joining;
  if (join_here)
    c->joining = true;
  encore_sync_mutex_unlock(&c->mutex);
  if (join_here) {
#ifdef _WIN32
    WaitForSingleObject(c->thread, INFINITE);
    CloseHandle(c->thread);
#else
    pthread_join(c->thread, NULL);
#endif
    encore_sync_mutex_lock(&c->mutex);
    c->joined = true;
    encore_sync_condition_notify(&c->condition);
    encore_sync_mutex_unlock(&c->mutex);
  } else {
    encore_sync_mutex_lock(&c->mutex);
    while (c->started && !c->joined)
      encore_sync_condition_wait(&c->condition, &c->mutex, 0, true);
    encore_sync_mutex_unlock(&c->mutex);
  }
}
static void encore_sync_clock_destroy(encore_sync_header *h) {
  encore_sync_clock *c = (encore_sync_clock *)h;
  encore_sync_clock_close((size_t)(uintptr_t)c);
  encore_sync_condition_destroy(&c->condition);
  encore_sync_mutex_destroy(&c->mutex);
  free(c);
}
size_t encore_sync_clock_new(bool virtual_time, uint64_t initial) {
  encore_sync_clock *c = calloc(1, sizeof(*c));
  if (c == NULL)
    return 0;
  if (!encore_sync_mutex_init(&c->mutex)) {
    free(c);
    return 0;
  }
  if (!encore_sync_condition_init(&c->condition)) {
    encore_sync_mutex_destroy(&c->mutex);
    free(c);
    return 0;
  }
  uint64_t id = atomic_load(&encore_sync_next_clock);
  while (id != UINT64_MAX &&
         !atomic_compare_exchange_weak(&encore_sync_next_clock, &id, id + 1)) {
  }
  if (id == UINT64_MAX) {
    encore_sync_condition_destroy(&c->condition);
    encore_sync_mutex_destroy(&c->mutex);
    free(c);
    return 0;
  }
  encore_sync_header_init(&c->header, ENCORE_SYNC_CLOCK,
                          encore_sync_clock_destroy);
  c->domain = id;
  c->virtual_time = virtual_time;
  c->virtual_now = initial;
  return (size_t)(uintptr_t)c;
}
uint64_t encore_sync_clock_domain(size_t token) {
  encore_sync_clock *c = (encore_sync_clock *)(uintptr_t)token;
  return c == NULL ? 0 : c->domain;
}
uint64_t encore_sync_clock_now(size_t token) {
  encore_sync_clock *c = (encore_sync_clock *)(uintptr_t)token;
  if (c == NULL)
    return 0;
  encore_sync_mutex_lock(&c->mutex);
  uint64_t value = encore_sync_clock_read(c);
  encore_sync_mutex_unlock(&c->mutex);
  return value;
}
uint32_t encore_sync_clock_advance(size_t token, uint64_t delta) {
  encore_sync_clock *c = (encore_sync_clock *)(uintptr_t)token;
  if (c == NULL || c->header.kind != ENCORE_SYNC_CLOCK || !c->virtual_time)
    return 1;
  encore_sync_mutex_lock(&c->mutex);
  uint32_t status =
      c->closed ? 3 : (delta > UINT64_MAX - c->virtual_now ? 2 : 0);
  if (status == 0) {
    c->virtual_now += delta;
    encore_sync_clock_fire(c);
  }
  encore_sync_mutex_unlock(&c->mutex);
  return status;
}
static void encore_sync_timer_unlink(encore_sync_timer *t) {
  if (!t->linked)
    return;
  encore_sync_timer **slot = &t->clock->timers;
  while (*slot != NULL && *slot != t)
    slot = &(*slot)->next;
  if (*slot == t)
    *slot = t->next;
  t->linked = false;
  t->next = NULL;
}
static void encore_sync_timer_destroy(encore_sync_header *h) {
  encore_sync_timer *t = (encore_sync_timer *)h;
  encore_sync_clock *c = t->clock;
  encore_sync_mutex_lock(&c->mutex);
  encore_sync_timer_unlink(t);
  encore_sync_condition_notify(&c->condition);
  encore_sync_mutex_unlock(&c->mutex);
  free(t);
  encore_sync_release((size_t)(uintptr_t)c);
}
size_t encore_sync_timer_new(size_t clock, uint64_t deadline) {
  encore_sync_clock *c = (encore_sync_clock *)(uintptr_t)clock;
  if (c == NULL || c->header.kind != ENCORE_SYNC_CLOCK)
    return 0;
  encore_sync_timer *t = calloc(1, sizeof(*t));
  if (t == NULL)
    return 0;
  encore_sync_header_init(&t->header, ENCORE_SYNC_TIMER,
                          encore_sync_timer_destroy);
  t->clock = c;
  t->deadline = deadline;
  encore_sync_retain(clock);
  encore_sync_mutex_lock(&c->mutex);
  if (c->closed)
    t->status = 3;
  else if (deadline <= encore_sync_clock_read(c))
    t->status = 1;
  else {
    encore_sync_timer **slot = &c->timers;
    while (*slot != NULL && (*slot)->deadline <= deadline)
      slot = &(*slot)->next;
    t->next = *slot;
    *slot = t;
    t->linked = true;
    if (!c->virtual_time && !c->started) {
#ifdef _WIN32
      c->thread = CreateThread(NULL, 0, encore_sync_clock_worker, c, 0, NULL);
      c->started = c->thread != NULL;
#else
      c->started =
          pthread_create(&c->thread, NULL, encore_sync_clock_worker, c) == 0;
#endif
      if (!c->started) {
        encore_sync_timer_unlink(t);
        encore_sync_mutex_unlock(&c->mutex);
        encore_sync_release((size_t)(uintptr_t)t);
        return 0;
      }
    }
    encore_sync_condition_notify(&c->condition);
  }
  encore_sync_mutex_unlock(&c->mutex);
  return (size_t)(uintptr_t)t;
}
uint32_t encore_sync_timer_status(size_t token) {
  encore_sync_timer *t = (encore_sync_timer *)(uintptr_t)token;
  if (t == NULL)
    return 2;
  encore_sync_mutex_lock(&t->clock->mutex);
  uint32_t status = t->status;
  encore_sync_mutex_unlock(&t->clock->mutex);
  return status;
}
void encore_sync_timer_cancel(size_t token) {
  encore_sync_timer *t = (encore_sync_timer *)(uintptr_t)token;
  if (t == NULL || t->header.kind != ENCORE_SYNC_TIMER)
    return;
  encore_sync_mutex_lock(&t->clock->mutex);
  if (t->status == 0) {
    encore_sync_timer_unlink(t);
    t->status = 2;
    encore_sync_notify(&t->waiters);
    encore_sync_condition_notify(&t->clock->condition);
  }
  encore_sync_mutex_unlock(&t->clock->mutex);
}
size_t encore_sync_timer_register(size_t token, size_t waker) {
  encore_sync_timer *t = (encore_sync_timer *)(uintptr_t)token;
  if (t == NULL || t->header.kind != ENCORE_SYNC_TIMER)
    return 0;
  encore_sync_mutex_lock(&t->clock->mutex);
  if (t->status != 0) {
    encore_sync_mutex_unlock(&t->clock->mutex);
    return 0;
  }
  encore_sync_waiter *w =
      encore_sync_waiter_new(&t->header, &t->clock->mutex, &t->waiters, waker);
  encore_sync_mutex_unlock(&t->clock->mutex);
  return w == NULL ? SIZE_MAX : (size_t)(uintptr_t)w;
}
#endif
