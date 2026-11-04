#include "../../packages/platform/sync_signal.h"
#include "../../packages/platform/owned_waker.h"
#include <stdio.h>
uint64_t encore_clock_ns(uint8_t kind) {
  (void)kind;
  struct timespec t;
  clock_gettime(CLOCK_MONOTONIC, &t);
  return (uint64_t)t.tv_sec * 1000000000 + t.tv_nsec;
}
int main(void) {
  for (size_t i = 0; i < 100; i++) {
    size_t s = encore_sync_signal_new();
    if (!s || encore_sync_signal_support() != 2 || encore_sync_signal_new())
      return 1;
    size_t w = encore_async_waker_new(), r = encore_sync_signal_register(s, w);
    raise(SIGINT);
    if (r && r != SIZE_MAX)
      encore_async_waker_wait(w);
    encore_sync_release(r);
    if (encore_sync_signal_next(s) != 1)
      return 2;
    r = encore_sync_signal_register(s, w);
    raise(SIGTERM);
    if (r && r != SIZE_MAX)
      encore_async_waker_wait(w);
    encore_sync_release(r);
    if (encore_sync_signal_next(s) != 2)
      return 3;
    encore_sync_signal_close(s);
    if (encore_sync_signal_next(s) != 3)
      return 4;
    encore_sync_signal_close(s);
    encore_sync_release(s);
    encore_async_waker_release(w);
    struct sigaction a;
    sigaction(SIGINT, NULL, &a);
    if (a.sa_handler != SIG_DFL)
      return 5;
  }
  if (encore_sync_live_objects() || encore_async_events)
    return 6;
  puts("SIGINT/SIGTERM delivery, exclusivity, restoration and repeated close: "
       "passed");
  return 0;
}
