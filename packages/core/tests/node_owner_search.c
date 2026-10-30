/* Exact owner reachability and the shallow, widely shared EHIR type case. */
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static size_t allocation_calls;
static void *count_malloc(size_t size) { allocation_calls++; return malloc(size); }
static void *count_calloc(size_t count, size_t size) { allocation_calls++; return calloc(count, size); }
static void *count_realloc(void *old, size_t size) { allocation_calls++; return realloc(old, size); }
#define malloc count_malloc
#define calloc count_calloc
#define realloc count_realloc
#ifndef NODE_RUNTIME_SOURCE
#define NODE_RUNTIME_SOURCE "../node_runtime.c"
#endif
#include NODE_RUNTIME_SOURCE
#undef malloc
#undef calloc
#undef realloc

static uint32_t random_state = UINT32_C(0x10203040);
static uint32_t next_random(void) {
    random_state ^= random_state << 13;
    random_state ^= random_state >> 17;
    random_state ^= random_state << 5;
    return random_state;
}

/* Independent, allocation-free transitive closure over the input adjacency. */
static bool reachable_root(encore_node_header *nodes, size_t count, size_t root) {
    bool reached[96] = {false};
    if (nodes[root].state != ENCORE_NODE_ALIVE) return false;
    reached[root] = true;
    bool changed = true;
    while (changed) {
        changed = false;
        for (size_t child = 0; child < count; ++child) {
            if (!reached[child] || nodes[child].state != ENCORE_NODE_ALIVE) continue;
            for (size_t edge = 0; edge < nodes[child].incoming_owner_count; ++edge) {
                encore_node_header *owner = nodes[child].incoming_owners[edge];
                if (owner->state != ENCORE_NODE_ALIVE) continue;
                size_t position = (size_t)(owner - nodes);
                if (!reached[position]) { reached[position] = true; changed = true; }
            }
        }
    }
    for (size_t index = 0; index < count; ++index) {
        if (index != root && reached[index] && nodes[index].refs > nodes[index].incoming_edges) return true;
    }
    return false;
}

static void check_reachability(void) {
    enum { COUNT = 96 };
    encore_node_header nodes[COUNT];
    void *owners[COUNT][COUNT];
    for (size_t graph = 0; graph < 160; ++graph) {
        memset(nodes, 0, sizeof(nodes));
        for (size_t child = 0; child < COUNT; ++child) {
            encore_node_initialize_header(&nodes[child], NULL, 1, ENCORE_NODE_HEAP);
            nodes[child].incoming_owners = owners[child];
            for (size_t owner = 0; owner < COUNT; ++owner) {
                /* Include long chains, dense sharing, self edges and cycles. */
                bool edge = graph < 2 ? owner == child + 1 : (next_random() % 9 == 0);
                if (edge) owners[child][nodes[child].incoming_owner_count++] = &nodes[owner];
            }
            nodes[child].incoming_edges = nodes[child].incoming_owner_count;
            bool external = graph == 0 ? child == COUNT - 1 : graph > 1 && next_random() % 7 == 0;
            nodes[child].refs = nodes[child].incoming_edges + (external ? 1 : 0);
            if (graph > 3 && next_random() % 13 == 0) nodes[child].state = ENCORE_NODE_FINALIZING;
        }
        for (size_t root = 0; root < COUNT; ++root) {
            assert(encore_node_has_external_ancestor(&nodes[root]) == reachable_root(nodes, COUNT, root));
        }
    }
}

static void connect(void *owner, void *target) {
    encore_node_retain(target);
    encore_node_add_edge(owner, target);
}

static void check_wide_shared_type(bool benchmark) {
    enum { WIDTH = 4096, RELEASES = 10000 };
    void *root = encore_node_alloc_heap(1);
    void *leaf = encore_node_alloc_heap(1);
    void *owners[WIDTH];
    assert(root != NULL && leaf != NULL);
    for (size_t index = 0; index < WIDTH; ++index) {
        owners[index] = encore_node_alloc_heap(1);
        assert(owners[index] != NULL);
        connect(root, owners[index]);
        connect(owners[index], leaf);
        assert(!encore_node_release(owners[index]));
    }
    size_t before = allocation_calls;
    size_t scans = encore_node_debug_ern_scan_count();
    assert(!encore_node_release(leaf));
    for (size_t index = 0; index < RELEASES; ++index) {
        encore_node_retain(leaf);
        assert(!encore_node_release(leaf));
    }
    size_t allocations = allocation_calls - before;
    assert(encore_node_debug_ern_scan_count() == scans);
    /* Wide fan-in is shallow: no fallback queue or hash table is necessary. */
    if (!benchmark) assert(allocations == 0);
    printf("{\"owners\":%d,\"releases\":%d,\"search_allocations\":%zu}\n", WIDTH, RELEASES + 1, allocations);
    encore_node_retain(leaf);
    assert(encore_node_release(root));
    for (size_t index = 0; index < WIDTH; ++index) {
        assert(encore_node_release(owners[index]));
        assert(!encore_node_release(leaf));
        encore_node_free_released(owners[index]);
    }
    encore_node_free_released(root);
    assert(encore_node_release(leaf));
    encore_node_free_released(leaf);
    assert(encore_node_debug_live_count() == 0);
}

int main(int argc, char **argv) {
    check_reachability();
    check_wide_shared_type(argc == 2 && strcmp(argv[1], "benchmark") == 0);
    return 0;
}
