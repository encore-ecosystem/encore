/* Immutable declaration index for compiler-generated LLVM text. Bodies remain
 * typed EHIR until lowering; this scanner only finds LLVM symbol references.
 * Each emission owns its traversal state, so an index can be shared by threads. */
#ifndef ENCORE_EHIR_RUNTIME_IR_H
#define ENCORE_EHIR_RUNTIME_IR_H
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
    size_t start, len, key_start, key_len;
    size_t *edges, edge_count;
} ehir_ir_record;
typedef struct {
    char *text;
    size_t len, count, capacity, slots;
    ehir_ir_record *records;
    size_t *table;
} ehir_ir_index;

static bool ehir_ir_space(char c) { return c == ' ' || c == '\t' || c == '\r' || c == '\n'; }
static bool ehir_ir_name_char(char c) {
    return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
           (c >= '0' && c <= '9') || c == '-' || c == '$' || c == '.' || c == '_';
}
static size_t ehir_ir_quoted_end(const char *text, size_t end, size_t position) {
    ++position;
    while (position < end) {
        if (text[position] == '"') return position + 1;
        if (text[position] == '\\' && position + 1 < end) ++position;
        ++position;
    }
    return end;
}
/* Returns the complete spelling, including @/% and any identifier quotes.
 * Quoted string constants and comments never create dependency edges. */
static bool ehir_ir_next(const char *text, size_t end, size_t *cursor, size_t *start, size_t *len) {
    while (*cursor < end) {
        size_t at = (*cursor)++;
        char c = text[at];
        if (c == ';') {
            while (*cursor < end && text[*cursor] != '\n') ++*cursor;
        } else if (c == '"') {
            *cursor = ehir_ir_quoted_end(text, end, at);
        } else if ((c == '@' || c == '%') && *cursor < end) {
            if (text[*cursor] == '"') *cursor = ehir_ir_quoted_end(text, end, *cursor);
            else while (*cursor < end && ehir_ir_name_char(text[*cursor])) ++*cursor;
            if (*cursor > at + 1) { *start = at; *len = *cursor - at; return true; }
        }
    }
    return false;
}
static bool ehir_ir_word(const char *text, size_t end, size_t at, const char *word) {
    size_t len = strlen(word);
    return len <= end - at && memcmp(text + at, word, len) == 0 &&
           (at + len == end || ehir_ir_space(text[at + len]));
}
static bool ehir_ir_header(const char *text, size_t start, size_t end, size_t *key, size_t *len) {
    while (start < end && ehir_ir_space(text[start])) ++start;
    if (start == end || text[start] == ';') return false;
    bool function = ehir_ir_word(text, end, start, "declare") || ehir_ir_word(text, end, start, "define");
    if (!function && text[start] != '@' && text[start] != '%') return false;
    size_t cursor = start;
    if (function) {
        while (ehir_ir_next(text, end, &cursor, key, len)) if (text[*key] == '@') return true;
        return false;
    }
    if (!ehir_ir_next(text, end, &cursor, key, len) || *key != start) return false;
    while (cursor < end && ehir_ir_space(text[cursor])) ++cursor;
    if (cursor == end || text[cursor++] != '=') return false;
    if (text[*key] == '@') return true;
    while (cursor < end && ehir_ir_space(text[cursor])) ++cursor;
    return ehir_ir_word(text, end, cursor, "type");
}
static uint64_t ehir_ir_hash(const char *text, size_t len) {
    uint64_t value = UINT64_C(14695981039346656037);
    for (size_t i = 0; i < len; ++i) { value ^= (unsigned char)text[i]; value *= UINT64_C(1099511628211); }
    return value;
}
static size_t ehir_ir_lookup(const ehir_ir_index *index, const char *key, size_t len) {
    if (index->slots == 0) return SIZE_MAX;
    size_t slot = (size_t)ehir_ir_hash(key, len) & (index->slots - 1);
    while (index->table[slot]) {
        size_t ordinal = index->table[slot] - 1;
        const ehir_ir_record *record = &index->records[ordinal];
        if (record->key_len == len && memcmp(index->text + record->key_start, key, len) == 0) return ordinal;
        slot = (slot + 1) & (index->slots - 1);
    }
    return SIZE_MAX;
}
static void ehir_ir_index_free(ehir_ir_index *index) {
    if (!index) return;
    for (size_t i = 0; i < index->count; ++i) free(index->records[i].edges);
    free(index->records); free(index->table); free(index->text); free(index);
}
static ehir_ir_index *ehir_ir_index_new(const char *text, size_t len) {
    if (len == SIZE_MAX || (len != 0 && text == NULL)) return NULL;
    ehir_ir_index *index = calloc(1, sizeof(*index));
    if (!index) return NULL;
    index->text = malloc(len + 1);
    if (!index->text) { ehir_ir_index_free(index); return NULL; }
    if (len) memcpy(index->text, text, len);
    index->text[len] = 0; index->len = len;
    for (size_t start = 0; start < len;) {
        size_t end = start;
        while (end < len && text[end] != '\n') ++end;
        size_t first = start;
        while (first < end && ehir_ir_space(text[first])) ++first;
        if (first < end && text[first] != ';') {
            size_t key, key_len;
            if (!ehir_ir_header(text, start, end, &key, &key_len) || ehir_ir_word(text, end, first, "define")) {
                ehir_ir_index_free(index); return NULL;
            }
            if (index->count == index->capacity) {
                size_t capacity = index->capacity ? index->capacity * 2 : 64;
                if (capacity < index->capacity || capacity > SIZE_MAX / sizeof(ehir_ir_record)) { ehir_ir_index_free(index); return NULL; }
                ehir_ir_record *records = realloc(index->records, capacity * sizeof(*records));
                if (!records) { ehir_ir_index_free(index); return NULL; }
                index->records = records; index->capacity = capacity;
            }
            index->records[index->count++] = (ehir_ir_record){start, end - start, key, key_len, NULL, 0};
        }
        start = end < len ? end + 1 : end;
    }
    index->slots = 16;
    while (index->count > index->slots / 2) {
        if (index->slots > SIZE_MAX / 2) { ehir_ir_index_free(index); return NULL; }
        index->slots *= 2;
    }
    index->table = calloc(index->slots, sizeof(size_t));
    if (!index->table) { ehir_ir_index_free(index); return NULL; }
    for (size_t i = 0; i < index->count; ++i) {
        ehir_ir_record *record = &index->records[i];
        size_t slot = (size_t)ehir_ir_hash(index->text + record->key_start, record->key_len) & (index->slots - 1);
        while (index->table[slot]) {
            ehir_ir_record *previous = &index->records[index->table[slot] - 1];
            if (previous->key_len == record->key_len && memcmp(index->text + previous->key_start, index->text + record->key_start, record->key_len) == 0) break;
            slot = (slot + 1) & (index->slots - 1);
        }
        if (!index->table[slot]) index->table[slot] = i + 1; /* Existing declaration precedence. */
    }
    for (size_t i = 0; i < index->count; ++i) {
        ehir_ir_record *record = &index->records[i];
        size_t cursor = record->start, key, key_len;
        while (ehir_ir_next(index->text, record->start + record->len, &cursor, &key, &key_len)) {
            size_t edge = ehir_ir_lookup(index, index->text + key, key_len);
            if (edge == SIZE_MAX || edge == i) continue;
            if (record->edge_count >= SIZE_MAX / sizeof(size_t) - 1) { ehir_ir_index_free(index); return NULL; }
            size_t *edges = realloc(record->edges, (record->edge_count + 1) * sizeof(size_t));
            if (!edges) { ehir_ir_index_free(index); return NULL; }
            record->edges = edges; record->edges[record->edge_count++] = edge;
        }
    }
    return index;
}
static char *ehir_ir_emit(const ehir_ir_index *index, const char *body, size_t len, size_t *output_len) {
    if (!index || (len && !body) || !output_len || index->count > SIZE_MAX / sizeof(size_t)) return NULL;
    unsigned char *state = calloc(index->count ? index->count : 1, 1);
    size_t *queue = malloc((index->count ? index->count : 1) * sizeof(size_t));
    if (!state || !queue) { free(state); free(queue); return NULL; }
    /* Definitions and declarations already in the body take precedence. */
    for (size_t start = 0; start < len;) {
        size_t end = start, key, key_len;
        while (end < len && body[end] != '\n') ++end;
        if (ehir_ir_header(body, start, end, &key, &key_len)) {
            size_t found = ehir_ir_lookup(index, body + key, key_len);
            if (found != SIZE_MAX) state[found] = 2;
        }
        start = end < len ? end + 1 : end;
    }
    size_t cursor = 0, key, key_len, count = 0;
    while (ehir_ir_next(body, len, &cursor, &key, &key_len)) {
        size_t found = ehir_ir_lookup(index, body + key, key_len);
        if (found != SIZE_MAX && !state[found]) { state[found] = 1; queue[count++] = found; }
    }
    for (size_t at = 0; at < count; ++at) {
        const ehir_ir_record *record = &index->records[queue[at]];
        for (size_t e = 0; e < record->edge_count; ++e) {
            size_t found = record->edges[e];
            if (!state[found]) { state[found] = 1; queue[count++] = found; }
        }
    }
    size_t total = len;
    for (size_t i = 0; i < index->count; ++i) {
        const ehir_ir_record *record = &index->records[i];
        if (state[i] != 1) continue;
        if (record->len >= SIZE_MAX - total) { free(queue); free(state); return NULL; }
        total += record->len + 1;
    }
    if (total == SIZE_MAX) { free(queue); free(state); return NULL; }
    char *output = malloc(total + 1);
    if (output) {
        size_t offset = 0;
        for (size_t i = 0; i < index->count; ++i) {
            const ehir_ir_record *record = &index->records[i];
            if (state[i] != 1) continue;
            memcpy(output + offset, index->text + record->start, record->len); offset += record->len;
            output[offset++] = '\n';
        }
        if (len) memcpy(output + offset, body, len);
        output[total] = 0; *output_len = total;
    }
    free(queue); free(state);
    return output;
}
#endif
