#include "../../packages/platform/sync_group.h"
#include "../../packages/platform/owned_waker.h"
#include <stdio.h>
typedef struct {
  pthread_t thread;
  size_t receiver, token;
} owned;
static atomic_bool done;
static void *worker(void *arg) {
  owned *o = arg;
  size_t w = encore_async_waker_new();
  while (!encore_sync_cancelled(o->token)) {
    size_t reg = encore_sync_queue_register(o->receiver, w);
    if (reg && reg != SIZE_MAX)
      encore_async_waker_wait(w);
    encore_sync_release(reg);
    if (encore_sync_queue_closed(o->receiver))
      break;
  }
  encore_async_waker_release(w);
  atomic_store(&done, true);
  return NULL;
}
static void drop_bundle(size_t token) {
  owned *o = (owned *)(uintptr_t)token;
  pthread_join(o->thread, NULL);
  if (!atomic_load(&done))
    abort();
  encore_sync_release(o->receiver);
  free(o);
}
static void *wrong_owner(void *arg) {
  if (encore_sync_group_take((size_t)(uintptr_t)arg) != SIZE_MAX)
    abort();
  return NULL;
}
int main(void) {
  size_t cancel = encore_sync_cancel_new(0), q = encore_sync_queue_new(2),
         sender = encore_sync_endpoint_new(q, true),
         receiver = encore_sync_endpoint_new(q, false);
  encore_sync_release(q);
  size_t results = encore_sync_queue_new(2),
         rs = encore_sync_endpoint_new(results, true),
         rr = encore_sync_endpoint_new(results, false);
  encore_sync_release(results);
  size_t g =
      encore_sync_group_new(cancel, rr, 1, (size_t)(uintptr_t)drop_bundle);
  if (!g || !encore_sync_group_add_sender(g, sender))
    return 1;
  owned *o = calloc(1, sizeof(*o));
  o->receiver = receiver;
  o->token = cancel;
  pthread_create(&o->thread, NULL, worker, o);
  if (!encore_sync_group_put(g, (size_t)(uintptr_t)o) ||
      encore_sync_group_put(g, 1))
    return 2;
  pthread_t wrong;
  pthread_create(&wrong, NULL, wrong_owner, (void *)(uintptr_t)g);
  pthread_join(wrong, NULL);
  size_t payload = encore_sync_group_take(g);
  if (payload != (size_t)(uintptr_t)o ||
      encore_sync_group_take(g) != SIZE_MAX ||
      !encore_sync_group_put(g, payload))
    return 3;
  encore_sync_release(sender);
  encore_sync_release(rr);
  encore_sync_release(rs);
  encore_sync_release(g);
  encore_sync_release(cancel);
  if (encore_sync_live_objects() || encore_async_events)
    return 4;
  puts("group drop cancels, closes and joins; bundle access keeps thread "
       "affinity: passed");
  return 0;
}
