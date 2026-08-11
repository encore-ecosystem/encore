#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#if defined(__GLIBC__)
#include <malloc.h>
#endif
#ifdef _WIN32
#include <process.h>
#else
#include <unistd.h>
#include <sys/types.h>
#include <sys/wait.h>
#endif

typedef struct encore_compiler_str_object {
    size_t ref_count;
    size_t len;
    char data[];
} encore_compiler_str_object;

typedef struct encore_compiler_str {
    encore_compiler_str_object *object;
} encore_compiler_str;

static char *encore_compiler_cstr(encore_compiler_str value) {
    size_t len = value.object == NULL ? 0 : value.object->len;
    char *out = (char *)malloc(len + 1);
    if (out == NULL) return NULL;
    if (len > 0) memcpy(out, value.object->data, len);
    out[len] = '\0';
    return out;
}

void encore_compiler_release_heap(void) {
#if defined(__GLIBC__)
    malloc_trim(0);
#endif
}

int encore_compiler_exec_parts(encore_compiler_str program, size_t raw_args, size_t args_len) {
    encore_compiler_str *args = (encore_compiler_str *)raw_args;
    char **argv = (char **)calloc(args_len + 2, sizeof(char *));
    if (argv == NULL) return -1;
    argv[0] = encore_compiler_cstr(program);
    if (argv[0] == NULL) { free(argv); return -1; }
    for (size_t index = 0; index < args_len; index += 1) {
        argv[index + 1] = encore_compiler_cstr(args[index]);
        if (argv[index + 1] == NULL) return -1;
    }
#ifdef _WIN32
    return (int)_spawnvp(_P_WAIT, argv[0], (const char *const *)argv);
#else
    execvp(argv[0], argv);
    return -1;
#endif
}

static encore_compiler_str encore_compiler_owned_string(char *data, size_t len) {
    encore_compiler_str out = {NULL};
    encore_compiler_str_object *object = malloc(sizeof(*object) + len + 1);
    if (object == NULL) { free(data); return out; }
    object->ref_count = 1; object->len = len;
    if (len > 0) memcpy(object->data, data, len);
    object->data[len] = '\0'; free(data); out.object = object; return out;
}

static bool encore_compiler_identifier_byte(unsigned char value) {
    return (value >= '0' && value <= '9') ||
           (value >= 'A' && value <= 'Z') ||
           (value >= 'a' && value <= 'z') || value == '_';
}

bool encore_compiler_str_contains(encore_compiler_str value,
                                  encore_compiler_str needle) {
    const size_t value_len = value.object == NULL ? 0 : value.object->len;
    const size_t needle_len = needle.object == NULL ? 0 : needle.object->len;
    if (needle_len == 0) return true;
    if (needle_len > value_len || value.object == NULL || needle.object == NULL)
        return false;
    for (size_t index = 0; index + needle_len <= value_len; ++index) {
        if (memcmp(value.object->data + index, needle.object->data, needle_len) == 0)
            return true;
    }
    return false;
}

encore_compiler_str encore_compiler_replace_ehir_identifier(
    encore_compiler_str value, encore_compiler_str token,
    encore_compiler_str replacement) {
    const char *source = value.object == NULL ? "" : value.object->data;
    const char *match = token.object == NULL ? "" : token.object->data;
    const char *insert = replacement.object == NULL ? "" : replacement.object->data;
    const size_t source_len = value.object == NULL ? 0 : value.object->len;
    const size_t match_len = token.object == NULL ? 0 : token.object->len;
    const size_t insert_len = replacement.object == NULL ? 0 : replacement.object->len;
    size_t count = 0, index = 0;
    bool quoted = false, escaped = false, comment = false;

    while (match_len > 0 && index < source_len) {
        const unsigned char byte = (unsigned char)source[index];
        if (comment) {
            if (byte == '\n') comment = false;
            ++index; continue;
        }
        if (quoted) {
            if (escaped) escaped = false;
            else if (byte == '\\') escaped = true;
            else if (byte == '"') quoted = false;
            ++index; continue;
        }
        if (byte == '"') { quoted = true; ++index; continue; }
        if (byte == '/' && index + 1 < source_len && source[index + 1] == '/') {
            comment = true; index += 2; continue;
        }
        if (index + match_len <= source_len &&
            memcmp(source + index, match, match_len) == 0 &&
            (index == 0 || !encore_compiler_identifier_byte((unsigned char)source[index - 1])) &&
            (index + match_len == source_len ||
             !encore_compiler_identifier_byte((unsigned char)source[index + match_len]))) {
            ++count; index += match_len; continue;
        }
        ++index;
    }

    const size_t output_len = insert_len >= match_len
        ? source_len + count * (insert_len - match_len)
        : source_len - count * (match_len - insert_len);
    char *output = malloc(output_len + 1);
    if (output == NULL) return (encore_compiler_str){NULL};
    size_t written = 0; index = 0;
    quoted = false; escaped = false; comment = false;
    while (index < source_len) {
        const unsigned char byte = (unsigned char)source[index];
        bool replace = false;
        if (!comment && !quoted && match_len > 0 &&
            index + match_len <= source_len &&
            memcmp(source + index, match, match_len) == 0 &&
            (index == 0 || !encore_compiler_identifier_byte((unsigned char)source[index - 1])) &&
            (index + match_len == source_len ||
             !encore_compiler_identifier_byte((unsigned char)source[index + match_len]))) {
            replace = true;
        }
        if (replace) {
            if (insert_len > 0) memcpy(output + written, insert, insert_len);
            written += insert_len; index += match_len; continue;
        }
        output[written++] = source[index++];
        if (comment) {
            if (byte == '\n') comment = false;
        } else if (quoted) {
            if (escaped) escaped = false;
            else if (byte == '\\') escaped = true;
            else if (byte == '"') quoted = false;
        } else if (byte == '"') {
            quoted = true;
        } else if (byte == '/' && index < source_len && source[index] == '/') {
            output[written++] = source[index++];
            comment = true;
        }
    }
    output[written] = '\0';
    return encore_compiler_owned_string(output, written);
}
