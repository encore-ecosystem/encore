/* Real codec + durable writer + runtime SHA256, exercised by the CI fixture. */
#include <assert.h>
#ifndef _WIN32
#include <signal.h>
#include <sys/resource.h>
#include <sys/wait.h>
#endif

#ifdef _WIN32
typedef struct { encore_compiler_str path; _Atomic bool stop; _Atomic int bad; } cache_inventory_reader;
static DWORD WINAPI cache_read_inventory(LPVOID raw) {
    cache_inventory_reader *reader = raw;
    while (!atomic_load(&reader->stop)) {
        uint64_t size = encore_compiler_cache_logical_size(reader->path);
        /* Inventory is advisory during replacement: an unavailable header may
         * report zero/the physical size, but must never block publication. */
        if (size != 0 && size != 200000 && size != 200000 + ENCORE_CACHE_HEADER) atomic_store(&reader->bad, 1);
    }
    return 0;
}
#endif

int32_t encore_ci_cache_payload(encore_compiler_str directory) {
    char *root = encore_compiler_cstr(directory);
    assert(root != NULL);
    char path[4096];
    snprintf(path, sizeof(path), "%s/cache-payload-\xd0\xba\xd0\xb5\xd1\x88", root);
    char *path_copy = malloc(strlen(path) + 1);
    assert(path_copy != NULL); strcpy(path_copy, path);
    encore_compiler_str name = encore_compiler_owned_string(path_copy, strlen(path));
    size_t size = 200000;
    char *bytes = malloc(size);
    assert(bytes != NULL);
    for (size_t i = 0; i < size; ++i) bytes[i] = (char)(i % 17);
    encore_compiler_str raw = encore_compiler_owned_string(bytes, size);
    encore_compiler_str digest = encore_text_sha256(raw);
    encore_compiler_str encoded = encore_compiler_cache_encode(raw, digest, true);
    assert(encoded.object != NULL && encoded.object->len < size / 8 && encoded.object->data[8] == 1);
    assert(encore_compiler_write_atomic(name, encoded));
    encore_compiler_str restored = encore_compiler_cache_read(name, true, (encore_compiler_str){NULL});
    assert(restored.object != NULL && restored.object->len == size && !memcmp(restored.object->data, raw.object->data, size));
    free(restored.object);
    /* A valid compression stream with a wrong logical checksum is still a miss. */
    char saved = encoded.object->data[32];
    encoded.object->data[32] = saved == '0' ? '1' : '0';
    assert(encore_compiler_write_atomic(name, encoded));
    restored = encore_compiler_cache_read(name, true, (encore_compiler_str){NULL}); assert(restored.object == NULL);
    encoded.object->data[32] = saved;
    /* Reject forged allocation sizes, codecs, reserved fields and trailing bytes. */
    const size_t offsets[] = {8, 9, 23, 24, encoded.object->len - 1};
    for (size_t i = 0; i < sizeof(offsets) / sizeof(offsets[0]); ++i) {
        size_t at = offsets[i]; char old = encoded.object->data[at]; encoded.object->data[at] = (char)255;
        assert(encore_compiler_write_atomic(name, encoded));
        restored = encore_compiler_cache_read(name, true, (encore_compiler_str){NULL}); assert(restored.object == NULL);
        encoded.object->data[at] = old;
    }
    size_t original_length = encoded.object->len;
    encoded.object->len = 12;
    assert(encore_compiler_write_atomic(name, encoded));
    restored = encore_compiler_cache_read(name, true, (encore_compiler_str){NULL}); assert(restored.object == NULL);
    encoded.object->len = original_length;
    /* Legacy raw data remains readable, but cannot masquerade as a flat entry. */
    assert(encore_compiler_write_atomic(name, raw));
    restored = encore_compiler_cache_read(name, false, (encore_compiler_str){NULL});
    assert(restored.object != NULL && restored.object->len == size); free(restored.object);
    restored = encore_compiler_cache_read(name, true, (encore_compiler_str){NULL}); assert(restored.object == NULL);
    /* Small packed entries carry a checksum even without compression. */
    raw.object->len = 31;
    free(digest.object); digest = encore_text_sha256(raw);
    encore_compiler_str small = encore_compiler_cache_encode(raw, digest, true);
    assert(small.object != NULL && small.object->len == 31 + ENCORE_CACHE_HEADER && small.object->data[8] == 0);
    assert(encore_compiler_write_atomic(name, small));
    restored = encore_compiler_cache_read(name, true, (encore_compiler_str){NULL});
    assert(restored.object != NULL && restored.object->len == 31); free(restored.object);
#ifndef _WIN32
    pid_t child = fork(); assert(child >= 0);
    if (child == 0) {
        signal(SIGXFSZ, SIG_IGN);
        struct rlimit limit = {32, 32};
        if (setrlimit(RLIMIT_FSIZE, &limit) != 0) _exit(2);
        _exit(encore_compiler_write_atomic(name, encoded) ? 3 : 0);
    }
    int status = 0;
    assert(waitpid(child, &status, 0) == child && WIFEXITED(status) && WEXITSTATUS(status) == 0);
    restored = encore_compiler_cache_read(name, true, (encore_compiler_str){NULL});
    assert(restored.object != NULL && restored.object->len == 31); free(restored.object);
#endif
    /* A large incompressible value uses the raw codec, still checksummed. */
    raw.object->len = size;
    uint32_t state = 123456789;
    for (size_t i = 0; i < size; ++i) {
        state ^= state << 13; state ^= state >> 17; state ^= state << 5;
        raw.object->data[i] = (char)state;
    }
    free(digest.object); digest = encore_text_sha256(raw);
    encore_compiler_str random = encore_compiler_cache_encode(raw, digest, true);
    assert(random.object != NULL && random.object->len == size + ENCORE_CACHE_HEADER && random.object->data[8] == 0);
    assert(encore_compiler_write_atomic(name, random));
    restored = encore_compiler_cache_read(name, true, (encore_compiler_str){NULL});
    assert(restored.object != NULL && restored.object->len == size && !memcmp(restored.object->data, raw.object->data, size));
    free(restored.object); free(random.object);
#ifdef _WIN32
    /* Header inventory must use UTF-16 paths and share deletion with writers. */
    assert(encore_compiler_cache_logical_size(name) == size);
    encore_compiler_str record = encore_compiler_read_artifact(name);
    cache_inventory_reader reader = {name, false, 0};
    HANDLE thread = CreateThread(NULL, 0, cache_read_inventory, &reader, 0, NULL); assert(thread != NULL);
    for (size_t i = 0; i < 64; ++i) assert(encore_compiler_write_atomic(name, record));
    atomic_store(&reader.stop, true);
    assert(WaitForSingleObject(thread, 10000) == WAIT_OBJECT_0 && atomic_load(&reader.bad) == 0);
    assert(encore_compiler_cache_logical_size(name) == size);
    CloseHandle(thread); free(record.object);
#endif
    /* Escape the envelope prefix even when a short value stays uncompressed. */
    raw.object->len = 14; memcpy(raw.object->data, "ENQCP001legacy", 14);
    free(digest.object); digest = encore_text_sha256(raw);
    encore_compiler_str reserved = encore_compiler_cache_encode(raw, digest, false);
    assert(reserved.object != NULL && reserved.object->len == 14 + ENCORE_CACHE_HEADER);
    assert(encore_compiler_write_atomic(name, reserved));
    restored = encore_compiler_cache_read(name, false, digest);
    assert(restored.object != NULL && restored.object->len == 14 && !memcmp(restored.object->data, raw.object->data, 14));
    free(restored.object); free(reserved.object);
    free(small.object); free(raw.object); free(digest.object); free(encoded.object); free(name.object); free(root);
    return 0;
}
