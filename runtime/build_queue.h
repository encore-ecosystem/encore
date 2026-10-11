#ifndef ENCORE_BUILD_QUEUE_H
#define ENCORE_BUILD_QUEUE_H

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include <stdlib.h>
#include <stdatomic.h>

/* The coordinator owns this queue until every worker has been joined. No
 * Encore graph is mutated across threads: only this private native cursor is
 * shared, and the work descriptions remain recursively frozen. */
typedef struct encore_build_queue {
    _Atomic size_t next;
    _Atomic bool cancelled;
    size_t count;
} encore_build_queue;

size_t encore_build_queue_new(size_t count) {
    encore_build_queue *queue = malloc(sizeof(*queue));
    if (queue == NULL) return 0;
    atomic_init(&queue->next, 0);
    atomic_init(&queue->cancelled, false);
    queue->count = count;
    return (size_t)queue;
}

size_t encore_build_queue_next(size_t raw_queue) {
    encore_build_queue *queue = (encore_build_queue *)raw_queue;
    if (queue == NULL) return SIZE_MAX;
    size_t next = atomic_load(&queue->next);
    while (!atomic_load(&queue->cancelled) && next < queue->count) {
        if (atomic_compare_exchange_weak(&queue->next, &next, next + 1))
            return next;
    }
    return SIZE_MAX;
}

void encore_build_queue_cancel(size_t raw_queue) {
    encore_build_queue *queue = (encore_build_queue *)raw_queue;
    if (queue != NULL) atomic_store(&queue->cancelled, true);
}

void encore_build_queue_free(size_t raw_queue) {
    free((encore_build_queue *)raw_queue);
}

#endif
