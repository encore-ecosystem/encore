/* Native contract for generator pre-death hooks, aliases and cyclic graphs. */
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

void *encore_node_alloc_heap(size_t);
void encore_node_retain(void *);
bool encore_node_release(void *);
void encore_node_free_released(void *);
void encore_node_add_edge(void *, void *);
void encore_node_replace_edge(void *, void *, void *);
size_t encore_node_debug_live_count(void);
void encore_generator_register(uintptr_t, uintptr_t);
void encore_generator_enter(uintptr_t);
void encore_generator_leave(uintptr_t);

typedef struct frame { void *child; unsigned closed; } frame;
static unsigned closed_count;
static frame *published;
static bool publish_on_close;
static void release(void *node) {
    if (encore_node_release(node)) encore_node_free_released(node);
}
static void close_frame(uintptr_t payload) {
    frame *value = (frame *)payload;
    assert(value->closed == 0);
    value->closed = 1;
    ++closed_count;
    void *child = value->child;
    value->child = NULL;
    if (child != NULL) {
        encore_node_replace_edge(value, child, NULL);
        release(child);
    }
    if (publish_on_close) {
        encore_node_retain(value);
        published = value;
    }
}
static frame *create(void) {
    frame *value = encore_node_alloc_heap(sizeof(*value));
    assert(value != NULL);
    value->child = NULL; value->closed = 0;
    encore_generator_register((uintptr_t)value, (uintptr_t)close_frame);
    return value;
}
static void connect(frame *owner, void *target) {
    assert(owner->child == NULL);
    encore_node_retain(target);
    encore_node_add_edge(owner, target);
    owner->child = target;
}
int main(int argc, char **argv) {
    if (argc == 2 && strcmp(argv[1], "reenter") == 0) {
        frame *value = create();
        encore_generator_enter((uintptr_t)value);
        encore_generator_enter((uintptr_t)value);
        return 2;
    }
    size_t before = encore_node_debug_live_count();
    frame *value = create();
    encore_node_retain(value);
    release(value);
    assert(closed_count == 0);
    encore_generator_enter((uintptr_t)value);
    encore_generator_leave((uintptr_t)value);
    release(value);
    assert(closed_count == 1);
    assert(encore_node_debug_live_count() == before);

    value = create(); connect(value, value);
    release(value);
    assert(closed_count == 2);
    assert(encore_node_debug_live_count() == before);

    frame *first = create(), *second = create();
    connect(first, second); connect(second, first);
    release(first); release(second);
    assert(closed_count == 4);
    assert(encore_node_debug_live_count() == before);

    void *survivor = encore_node_alloc_heap(1);
    value = create(); connect(value, survivor);
    release(value);
    assert(closed_count == 5);
    assert(encore_node_debug_live_count() == before + 1);
    release(survivor);
    assert(encore_node_debug_live_count() == before);

    publish_on_close = true;
    value = create(); release(value);
    assert(published != NULL && published->closed == 1);
    assert(closed_count == 6);
    publish_on_close = false;
    release(published); published = NULL;
    assert(closed_count == 6);
    assert(encore_node_debug_live_count() == before);
    return 0;
}
