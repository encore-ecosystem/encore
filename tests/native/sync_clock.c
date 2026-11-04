#include "../../packages/platform/owned_waker.h"
#include "../../packages/platform/sync_time.h"
#include <stdio.h>
uint64_t encore_clock_ns(uint8_t kind) {
  (void)kind;
  struct timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return (uint64_t)ts.tv_sec * 1000000000 + (uint64_t)ts.tv_nsec;
}
int main(void) {
  size_t clock = encore_sync_clock_new(true, 100),
         first = encore_sync_timer_new(clock, 200),
         second = encore_sync_timer_new(clock, 200);
  if (((encore_sync_clock *)(uintptr_t)clock)->timers !=
      (encore_sync_timer *)(uintptr_t)first)
    return 1;
  if (encore_sync_clock_advance(clock, 99) || encore_sync_timer_status(first))
    return 2;
  size_t waker = encore_async_waker_new(),
         reg = encore_sync_timer_register(first, waker);
  if (encore_sync_clock_advance(clock, 1) ||
      encore_sync_timer_status(first) != 1 ||
      encore_sync_timer_status(second) != 1)
    return 3;
  encore_async_waker_wait(waker);
  encore_sync_release(reg);
  encore_async_waker_release(waker);
  size_t future = encore_sync_timer_new(clock, 300);
  encore_sync_clock_close(clock);
  if (encore_sync_timer_status(future) != 3)
    return 4;
  encore_sync_release(future);
  encore_sync_release(first);
  encore_sync_release(second);
  encore_sync_release(clock);
  clock = encore_sync_clock_new(false, 0);
  size_t timer = encore_sync_timer_new(clock, encore_clock_ns(1) + 2000000);
  waker = encore_async_waker_new();
  reg = encore_sync_timer_register(timer, waker);
  if (reg && reg != SIZE_MAX)
    encore_async_waker_wait(waker);
  if (encore_sync_timer_status(timer) != 1)
    return 5;
  encore_sync_release(reg);
  encore_async_waker_release(waker);
  encore_sync_release(timer);
  encore_sync_release(clock);
  if (encore_async_events != NULL)
    return 6;
  puts("virtual/system timers, tie order and close: passed");
  return 0;
}
