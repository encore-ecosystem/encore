#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#if defined(__GLIBC__)
#include <malloc.h>
#endif
#ifdef _WIN32
#include <process.h>
#else
#include <unistd.h>
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
