#ifndef ENCORE_OWNED_WAKER_H
#define ENCORE_OWNED_WAKER_H
#include <stdatomic.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#ifdef _WIN32
#include <windows.h>
#else
#include <pthread.h>
#endif
#include "async_waker_hooks.h"

typedef struct encore_async_event {
  size_t id, owners, operations;
  bool retired, cleanup_done, signaled, closed;
  struct encore_async_event *next;
#ifdef _WIN32
  CRITICAL_SECTION lock;
  CONDITION_VARIABLE condition;
#else
  pthread_mutex_t lock;
  pthread_cond_t condition;
#endif
} encore_async_event;
static encore_async_event *encore_async_events;
static size_t encore_async_next_event = 1;
#ifdef _WIN32
static SRWLOCK encore_async_registry = SRWLOCK_INIT;
static void encore_async_registry_lock(void) {
  AcquireSRWLockExclusive(&encore_async_registry);
}
static void encore_async_registry_unlock(void) {
  ReleaseSRWLockExclusive(&encore_async_registry);
}
static void encore_async_event_lock(encore_async_event *event) {
  EnterCriticalSection(&event->lock);
}
static void encore_async_event_unlock(encore_async_event *event) {
  LeaveCriticalSection(&event->lock);
}
static void encore_async_event_notify(encore_async_event *event) {
  WakeAllConditionVariable(&event->condition);
}
#else
static pthread_mutex_t encore_async_registry = PTHREAD_MUTEX_INITIALIZER;
static void encore_async_registry_lock(void) {
  pthread_mutex_lock(&encore_async_registry);
}
static void encore_async_registry_unlock(void) {
  pthread_mutex_unlock(&encore_async_registry);
}
static void encore_async_event_lock(encore_async_event *event) {
  pthread_mutex_lock(&event->lock);
}
static void encore_async_event_unlock(encore_async_event *event) {
  pthread_mutex_unlock(&event->lock);
}
static void encore_async_event_notify(encore_async_event *event) {
  pthread_cond_broadcast(&event->condition);
}
#endif
static void encore_async_event_free(encore_async_event *event) {
#ifdef _WIN32
  DeleteCriticalSection(&event->lock);
#else
  pthread_cond_destroy(&event->condition);
  pthread_mutex_destroy(&event->lock);
#endif
  free(event);
}
/* Operation pins are distinct from owning Wakers. A producer may wake while
 * holding an IO lock; its last pin must never invoke an IO cleanup callback. */
static encore_async_event *encore_async_event_enter(size_t token) {
  if (token == 0)
    return NULL;
  encore_async_registry_lock();
  encore_async_event *event = encore_async_events;
  while (event != NULL && event->id != token)
    event = event->next;
  if (event != NULL)
    ++event->operations;
  encore_async_registry_unlock();
  return event;
}
static void encore_async_event_leave(encore_async_event *event) {
  encore_async_registry_lock();
  --event->operations;
  bool destroy =
      event->retired && event->cleanup_done && event->operations == 0;
  encore_async_registry_unlock();
  if (destroy)
    encore_async_event_free(event);
}
size_t encore_async_waker_new(void) {
  encore_async_event *event = calloc(1, sizeof(*event));
  if (event == NULL)
    return 0;
#ifdef _WIN32
  InitializeCriticalSection(&event->lock);
  InitializeConditionVariable(&event->condition);
#else
  if (pthread_mutex_init(&event->lock, NULL) != 0) {
    free(event);
    return 0;
  }
  if (pthread_cond_init(&event->condition, NULL) != 0) {
    pthread_mutex_destroy(&event->lock);
    free(event);
    return 0;
  }
#endif
  encore_async_registry_lock();
  if (encore_async_next_event == SIZE_MAX) {
    encore_async_registry_unlock();
    encore_async_event_free(event);
    return 0;
  }
  event->id = encore_async_next_event++;
  event->owners = 1;
  event->next = encore_async_events;
  encore_async_events = event;
  encore_async_registry_unlock();
  return event->id;
}
bool encore_async_waker_retain(size_t token) {
  if (token == 0)
    return true; /* Explicit noop context. */
  encore_async_registry_lock();
  encore_async_event *event = encore_async_events;
  while (event != NULL && event->id != token)
    event = event->next;
  bool retained = event != NULL && event->owners != SIZE_MAX;
  if (retained)
    ++event->owners;
  encore_async_registry_unlock();
  return retained;
}
void encore_async_waker_retain_owned(size_t token) {
  (void)encore_async_waker_retain(token);
}
void encore_async_waker_release(size_t token) {
  if (token == 0)
    return;
  encore_async_registry_lock();
  encore_async_event **slot = &encore_async_events;
  while (*slot != NULL && (*slot)->id != token)
    slot = &(*slot)->next;
  encore_async_event *event = *slot;
  if (event == NULL || --event->owners != 0) {
    encore_async_registry_unlock();
    return;
  }
  *slot = event->next;
  event->retired = true;
  encore_async_registry_unlock();
  encore_async_event_lock(event);
  event->closed = true;
  encore_async_event_notify(event);
  encore_async_event_unlock(event);
  encore_async_cleanup_waker(token);
  encore_async_registry_lock();
  event->cleanup_done = true;
  bool destroy = event->operations == 0;
  encore_async_registry_unlock();
  if (destroy)
    encore_async_event_free(event);
}
void encore_async_waker_wake(size_t token) {
  encore_async_event *event = encore_async_event_enter(token);
  if (event == NULL)
    return;
  encore_async_event_lock(event);
  if (!event->closed) {
    event->signaled = true;
    encore_async_event_notify(event);
  }
  encore_async_event_unlock(event);
  encore_async_event_leave(event);
}
void encore_async_waker_wait(size_t token) {
  encore_async_event *event = encore_async_event_enter(token);
  if (event == NULL)
    return;
  encore_async_event_lock(event);
  while (!event->signaled && !event->closed) {
#ifdef _WIN32
    SleepConditionVariableCS(&event->condition, &event->lock, INFINITE);
#else
    pthread_cond_wait(&event->condition, &event->lock);
#endif
  }
  event->signaled = false;
  encore_async_event_unlock(event);
  encore_async_event_leave(event);
}
void encore_async_waker_drop(size_t token) {
  encore_async_waker_release(token);
}
#endif
