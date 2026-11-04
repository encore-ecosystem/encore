#ifndef ENCORE_SYNC_HTTP_H
#define ENCORE_SYNC_HTTP_H
#include "sync_runtime.h"
extern void encore_http_async_abandon(size_t);
extern void encore_http_async_runtime_stop(size_t);
extern void encore_http_async_runtime_destroy(size_t);
typedef struct {
  encore_sync_header header;
  size_t id;
  uint32_t action;
} encore_sync_http_lease;
static void encore_sync_http_lease_destroy(encore_sync_header *h) {
  encore_sync_http_lease *r = (encore_sync_http_lease *)h;
  if (r->action == 0)
    encore_http_async_abandon(r->id);
  else if (r->action == 1)
    encore_http_async_runtime_stop(r->id);
  else
    encore_http_async_runtime_destroy(r->id);
  free(r);
}
size_t encore_sync_http_lease_new(size_t id, uint32_t action) {
  if (!id || action > 2)
    return 0;
  encore_sync_http_lease *r = calloc(1, sizeof(*r));
  if (!r)
    return 0;
  encore_sync_header_init(&r->header, ENCORE_SYNC_HTTP_LEASE,
                          encore_sync_http_lease_destroy);
  r->id = id;
  r->action = action;
  return (size_t)(uintptr_t)r;
}
#endif
