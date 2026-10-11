#ifndef ENCORE_BUILD_IDENTITY_H
#define ENCORE_BUILD_IDENTITY_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

static inline bool encore_build_identity_byte(unsigned char byte) {
    return (byte >= 'a' && byte <= 'z') || (byte >= 'A' && byte <= 'Z') ||
        (byte >= '0' && byte <= '9') || byte == '_';
}

/* EHIR has explicit declaration headers and brace scopes. A nominal rename
 * must not rename a lexical generic binder or uses within its scope. This
 * mask is only for identity rewriting, not a second frontend/parser. Quoted
 * strings and comments are handled by the existing identifier rewriter. */
static inline unsigned char *encore_build_generic_mask(const char *text, size_t length,
    const char *name, size_t name_length) {
    if (length == SIZE_MAX) return NULL;
    unsigned char *mask = calloc(length + 1, 1);
    unsigned char *scopes = calloc(length + 1, 1);
    unsigned char *enum_scopes = calloc(length + 1, 1);
    if (mask == NULL || scopes == NULL || enum_scopes == NULL) {
        free(mask); free(scopes); free(enum_scopes); return NULL;
    }
    size_t depth = 0, line = 0;
    bool quoted = false, escaped = false, comment = false;
    bool header_shadow = false;
    bool enum_header = false;
    size_t variant_start = SIZE_MAX, variant_end = SIZE_MAX;
    size_t binder_start = SIZE_MAX;
    for (size_t index = 0; index < length; ++index) {
        if (index == line) {
            size_t cursor = index;
            while (cursor < length && (text[cursor] == ' ' || text[cursor] == '\t')) ++cursor;
            static const char *const kinds[] = {"fn ", "extern fn ", "struct ", "enum ", "trait ", "impl["};
            bool declaration = false;
            enum_header = false;
            variant_start = SIZE_MAX; variant_end = SIZE_MAX;
            for (size_t kind = 0; kind < sizeof(kinds) / sizeof(kinds[0]); ++kind) {
                size_t size = strlen(kinds[kind]);
                if (size <= length - cursor && memcmp(text + cursor, kinds[kind], size) == 0) {
                    enum_header = strcmp(kinds[kind], "enum ") == 0;
                    declaration = true; cursor += size;
                    if (kinds[kind][size - 1] == '[') --cursor;
                    break;
                }
            }
            header_shadow = false; binder_start = SIZE_MAX;
            if (!declaration && enum_scopes[depth]) {
                variant_start = cursor;
                while (cursor < length && encore_build_identity_byte((unsigned char)text[cursor])) ++cursor;
                variant_end = cursor;
            }
            if (declaration) {
                while (cursor < length && text[cursor] != '[' && text[cursor] != '(' &&
                    text[cursor] != '{' && text[cursor] != '\n') ++cursor;
                if (cursor < length && text[cursor] == '[') {
                    binder_start = cursor;
                    size_t nesting = 1;
                    bool binder = true;
                    for (++cursor; cursor < length && nesting != 0 && text[cursor] != '\n'; ++cursor) {
                        unsigned char byte = (unsigned char)text[cursor];
                        if (byte == '[' || byte == '(') { ++nesting; continue; }
                        if (byte == ']' || byte == ')') { --nesting; continue; }
                        if (nesting != 1) continue;
                        if (byte == ',') { binder = true; continue; }
                        if (byte == ':' || byte == '=') { binder = false; continue; }
                        if (binder && encore_build_identity_byte(byte)) {
                            size_t begin = cursor;
                            while (cursor < length && encore_build_identity_byte((unsigned char)text[cursor])) ++cursor;
                            if (cursor - begin == name_length && memcmp(text + begin, name, name_length) == 0) header_shadow = true;
                            binder = false;
                            if (cursor != 0) --cursor;
                        }
                    }
                }
            }
        }
        unsigned char byte = (unsigned char)text[index];
        mask[index] = scopes[depth] || (header_shadow && index >= binder_start) ||
            (index >= variant_start && index < variant_end);
        if (comment) {
            if (byte == '\n') comment = false;
        } else if (quoted) {
            if (escaped) escaped = false;
            else if (byte == '\\') escaped = true;
            else if (byte == '"') quoted = false;
        } else if (byte == '/' && index + 1 < length && text[index + 1] == '/') {
            comment = true;
        } else if (byte == '"') quoted = true;
        else if (byte == '{') {
            scopes[depth + 1] = scopes[depth] || header_shadow;
            enum_scopes[depth + 1] = enum_header;
            ++depth;
        }
        else if (byte == '}' && depth != 0) --depth;
        if (byte == '\n') line = index + 1;
    }
    free(scopes);
    free(enum_scopes);
    return mask;
}

/* Scope members and labels/field names are identifiers, not type references. */
static inline bool encore_build_member_identifier(const char *text, size_t length,
    size_t begin, size_t size) {
    if (begin >= 2 && text[begin - 2] == ':' && text[begin - 1] == ':') return true;
    size_t end = begin + size;
    while (end < length && (text[end] == ' ' || text[end] == '\t')) ++end;
    if (end < length && text[end] == ':' && (end + 1 == length || text[end + 1] != ':')) return true;
    size_t previous = begin;
    while (previous > 0 && (text[previous - 1] == ' ' || text[previous - 1] == '\t')) --previous;
    if (previous > 0 && text[previous - 1] == '>' &&
        (previous < 2 || text[previous - 2] != '-')) return true;
    if (previous > 0 && text[previous - 1] == ',') {
        size_t line = previous;
        while (line > 0 && text[line - 1] != '\n') --line;
        for (size_t cursor = line; cursor + 5 <= previous; ++cursor) {
            if (memcmp(text + cursor, " ieq ", 5) == 0) return true;
        }
    }
    return false;
}

#endif
