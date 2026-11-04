/* Compile this executable against the actual runtime header, including ASan. */
#include "../../packages/platform/owned_waker.h"
#include <stdio.h>
#ifndef _WIN32
#include <sched.h>
static pthread_mutex_t producer_lock = PTHREAD_MUTEX_INITIALIZER;
static atomic_bool producer_ready;
static atomic_bool producer_go;
static atomic_size_t cleanups;
static void cleanup(size_t token) {
  (void)token;
  pthread_mutex_lock(&producer_lock);
  atomic_fetch_add(&cleanups, 1);
  pthread_mutex_unlock(&producer_lock);
}
static void *produce(void *argument) {
  size_t token = (size_t)(uintptr_t)argument;
  pthread_mutex_lock(&producer_lock);
  atomic_store(&producer_ready, true);
  while (!atomic_load(&producer_go))
    sched_yield();
  for (size_t index = 0; index < 1000; ++index)
    encore_async_waker_wake(token);
  pthread_mutex_unlock(&producer_lock);
  return NULL;
}
static void *wait_once(void *argument) {
  encore_async_waker_wait((size_t)(uintptr_t)argument);
  return NULL;
}
#endif
int main(void) {
  size_t first = encore_async_waker_new();
  if (first == 0 || !encore_async_waker_retain(first))
    return 1;
  encore_async_waker_drop(first);
  encore_async_waker_wake(first);
  encore_async_waker_wait(first);
  encore_async_waker_release(first);
  if (encore_async_waker_retain(first))
    return 2;
  encore_async_waker_wake(first); /* Retired IDs are harmless. */
  size_t next = encore_async_waker_new();
  if (next <= first)
    return 3;
#ifndef _WIN32
  pthread_t waiter;
  if (pthread_create(&waiter, NULL, wait_once, (void *)(uintptr_t)next))
    return 4;
  encore_async_waker_release(next);
  pthread_join(waiter, NULL);
  if (!encore_async_register_waker_cleanup(cleanup))
    return 5;
  for (size_t iteration = 0; iteration < 1000; ++iteration) {
    size_t token = encore_async_waker_new();
    atomic_store(&producer_ready, false);
    atomic_store(&producer_go, false);
    pthread_t producer;
    if (pthread_create(&producer, NULL, produce, (void *)(uintptr_t)token))
      return 6;
    while (!atomic_load(&producer_ready))
      sched_yield();
    atomic_store(&producer_go, true);
    encore_async_waker_release(token);
    pthread_join(producer, NULL);
  }
  if (atomic_load(&cleanups) != 1000)
    return 7;
#else
  encore_async_waker_release(next);
#endif
  if (encore_async_events != NULL)
    return 8;
  puts("owned Waker lifetime and wake/release races: passed");
  return 0;
}
