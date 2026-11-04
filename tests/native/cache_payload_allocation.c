/* SHA allocation failure must become a cache miss, including when the
 * platform returns its immortal empty string. No platform library is mocked
 * in the ordinary codec tests; this separate process injects only that failure. */
#include "../../runtime.c"
#include <assert.h>
static struct { size_t ref_count, len; char data[1]; } empty;
encore_compiler_str encore_text_sha256(encore_compiler_str value) {
    (void)value;
    return (encore_compiler_str){(encore_compiler_str_object *)&empty};
}
encore_compiler_str encore_fs_sha256(encore_compiler_str path) {
    return encore_text_sha256(path);
}
uint64_t encore_clock_ns(uint8_t kind) {
    (void)kind;
    struct timespec value;
    assert(clock_gettime(CLOCK_MONOTONIC, &value) == 0);
    return (uint64_t)value.tv_sec * UINT64_C(1000000000) + (uint64_t)value.tv_nsec;
}
static encore_compiler_str string(const char *text) {
    size_t n = strlen(text); char *data = malloc(n + 1); assert(data); memcpy(data, text, n + 1);
    return encore_compiler_owned_string(data, n);
}
int main(int argc, char **argv) {
    assert(argc == 2);
    encore_compiler_str path = string(argv[1]), data = string("payload");
    encore_compiler_str digest = string("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa");
    assert(encore_compiler_write_atomic(path, data));
    assert(encore_compiler_cache_read(path, false, digest).object == NULL);
    free(path.object); free(data.object); free(digest.object);
    return 0;
}
