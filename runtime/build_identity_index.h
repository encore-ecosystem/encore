#ifndef ENCORE_BUILD_IDENTITY_INDEX_H
#define ENCORE_BUILD_IDENTITY_INDEX_H

#include "build_identity.h"

typedef struct encore_identity_name {
    const char *text;
    size_t length;
} encore_identity_name;

typedef struct encore_identity_slot {
    const char *text;
    size_t length;
    uint64_t hash;
    bool present;
} encore_identity_slot;

typedef struct encore_identity_index {
    encore_identity_slot *slots;
    char *keys;
    size_t capacity;
} encore_identity_index;

static inline uint64_t encore_identity_hash(const char *text, size_t length) {
    uint64_t hash = UINT64_C(14695981039346656037);
    for (size_t i = 0; i < length; ++i) {
        hash ^= (unsigned char)text[i];
        hash *= UINT64_C(1099511628211);
    }
    return hash;
}

static inline encore_identity_slot *encore_identity_find(encore_identity_index *index,
    const char *text, size_t length, uint64_t hash) {
    size_t slot = (size_t)hash & (index->capacity - 1);
    for (;;) {
        encore_identity_slot *entry = &index->slots[slot];
        if (entry->text == NULL || (entry->hash == hash && entry->length == length &&
            memcmp(entry->text, text, length) == 0)) return entry;
        slot = (slot + 1) & (index->capacity - 1);
    }
}

/* A monotone admission filter, not an EHIR parser. Quotes and lexical binders
 * deliberately admit false positives; the existing scoped rewriter decides
 * whether a token may actually change. Non-ASCII/non-word candidates always
 * pass through so their historical byte-boundary behavior remains intact. */
static inline void encore_identity_index_note(encore_identity_index *index,
    const char *text, size_t length) {
    if (index == NULL) return;
    size_t cursor = 0;
    while (cursor < length) {
        if (!encore_build_identity_byte((unsigned char)text[cursor])) {
            ++cursor;
            continue;
        }
        size_t first = cursor++;
        while (cursor < length && encore_build_identity_byte((unsigned char)text[cursor])) ++cursor;
        size_t size = cursor - first;
        encore_identity_slot *entry = encore_identity_find(index, text + first, size,
            encore_identity_hash(text + first, size));
        if (entry->text != NULL) entry->present = true;
    }
}

static inline void encore_identity_index_free(encore_identity_index *index) {
    if (index == NULL) return;
    free(index->slots);
    free(index->keys);
    free(index);
}

static inline encore_identity_index *encore_identity_index_new(const char *text, size_t length,
    const encore_identity_name *names, size_t count) {
    if (count == 0 || count > (SIZE_MAX - 1) / 2) return NULL;
    size_t capacity = 2, bytes = 0;
    while (capacity < count * 2 + 1) {
        if (capacity > SIZE_MAX / 2) return NULL;
        capacity *= 2;
    }
    for (size_t i = 0; i < count; ++i) {
        if (names[i].length >= SIZE_MAX - bytes) return NULL;
        bytes += names[i].length + 1;
    }
    if (capacity > SIZE_MAX / sizeof(encore_identity_slot)) return NULL;
    encore_identity_index *index = calloc(1, sizeof(*index));
    if (index == NULL) return NULL;
    index->capacity = capacity;
    index->slots = calloc(capacity, sizeof(*index->slots));
    index->keys = malloc(bytes);
    if (index->slots == NULL || index->keys == NULL) {
        encore_identity_index_free(index);
        return NULL;
    }
    size_t copied = 0;
    for (size_t i = 0; i < count; ++i) {
        uint64_t hash = encore_identity_hash(names[i].text, names[i].length);
        encore_identity_slot *entry = encore_identity_find(index, names[i].text, names[i].length, hash);
        if (entry->text != NULL) continue;
        char *key = index->keys + copied;
        memcpy(key, names[i].text, names[i].length);
        key[names[i].length] = '\0';
        copied += names[i].length + 1;
        *entry = (encore_identity_slot){key, names[i].length, hash, names[i].length == 0};
        for (size_t byte = 0; byte < names[i].length; ++byte) {
            if (!encore_build_identity_byte((unsigned char)key[byte])) entry->present = true;
        }
    }
    encore_identity_index_note(index, text, length);
    return index;
}

static inline bool encore_identity_index_contains(encore_identity_index *index,
    const char *name, size_t length) {
    if (index == NULL) return true;
    encore_identity_slot *entry = encore_identity_find(index, name, length,
        encore_identity_hash(name, length));
    return entry->text == NULL || entry->present;
}
#endif
