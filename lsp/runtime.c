#define _POSIX_C_SOURCE 200809L

#include <ctype.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
    char *ptr;
    size_t len;
} encore_str;

static encore_str lsp_empty_str(void) {
    static char empty[] = "";
    return (encore_str){.ptr = empty, .len = 0};
}

static encore_str lsp_from_owned_buffer(char *buffer, size_t len) {
    if (buffer == NULL) {
        return lsp_empty_str();
    }
    buffer[len] = '\0';
    return (encore_str){.ptr = buffer, .len = len};
}

static char *lsp_to_cstr(encore_str value) {
    char *buffer = malloc(value.len + 1);
    if (buffer == NULL) {
        return NULL;
    }
    if (value.len > 0 && value.ptr != NULL) {
        memcpy(buffer, value.ptr, value.len);
    }
    buffer[value.len] = '\0';
    return buffer;
}

static int lsp_ascii_eq_prefix(const char *line, const char *prefix) {
    while (*prefix != '\0') {
        unsigned char lhs = (unsigned char)*line;
        unsigned char rhs = (unsigned char)*prefix;
        if (tolower(lhs) != tolower(rhs)) {
            return 0;
        }
        line += 1;
        prefix += 1;
    }
    return 1;
}

encore_str encore_lsp_read_message(void) {
    char header[4096];
    size_t content_length = 0;

    while (fgets(header, sizeof(header), stdin) != NULL) {
        if (strcmp(header, "\r\n") == 0 || strcmp(header, "\n") == 0) {
            break;
        }

        if (lsp_ascii_eq_prefix(header, "Content-Length:")) {
            char *value = header + strlen("Content-Length:");
            while (*value == ' ' || *value == '\t') {
                value += 1;
            }
            errno = 0;
            unsigned long parsed = strtoul(value, NULL, 10);
            if (errno == 0) {
                content_length = (size_t)parsed;
            }
        }
    }

    if (content_length == 0) {
        return lsp_empty_str();
    }

    char *body = malloc(content_length + 1);
    if (body == NULL) {
        return lsp_empty_str();
    }

    size_t offset = 0;
    while (offset < content_length) {
        size_t count = fread(body + offset, 1, content_length - offset, stdin);
        if (count == 0) {
            free(body);
            return lsp_empty_str();
        }
        offset += count;
    }

    return lsp_from_owned_buffer(body, content_length);
}

int32_t encore_lsp_write_message(encore_str body) {
    fprintf(stdout, "Content-Length: %zu\r\n\r\n", body.len);
    if (body.len > 0 && body.ptr != NULL) {
        fwrite(body.ptr, 1, body.len, stdout);
    }
    fflush(stdout);
    return 0;
}

int32_t encore_lsp_log(encore_str value) {
    char *message = lsp_to_cstr(value);
    if (message == NULL) {
        return 1;
    }
    fprintf(stderr, "%s\n", message);
    fflush(stderr);
    free(message);
    return 0;
}

