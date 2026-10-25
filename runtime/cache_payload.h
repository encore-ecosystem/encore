#ifndef ENCORE_CACHE_PAYLOAD_H
#define ENCORE_CACHE_PAYLOAD_H

#include <limits.h>
#define LZ4LIB_VISIBILITY static
#include "vendor/lz4/lz4.c"

/* Fixed little-endian envelope. Digests describe decoded bytes, so semantic
 * identities do not change when the physical cache representation changes. */
#define ENCORE_CACHE_HEADER 96
static const unsigned char encore_cache_magic[8] = {'E','N','Q','C','P','0','0','1'};
static uint64_t encore_cache_u64(const unsigned char *p) {
    uint64_t n = 0;
    for (unsigned i = 0; i < 8; ++i) n |= (uint64_t)p[i] << (8 * i);
    return n;
}
static void encore_cache_put_u64(unsigned char *p, uint64_t n) {
    for (unsigned i = 0; i < 8; ++i) p[i] = (unsigned char)(n >> (8 * i));
}
static bool encore_cache_digest_valid(const char *digest, size_t length) {
    if (length != 64) return false;
    for (size_t i = 0; i < 64; ++i)
        if (!((digest[i] >= '0' && digest[i] <= '9') || (digest[i] >= 'a' && digest[i] <= 'f'))) return false;
    return true;
}

static char *encore_cache_encode(const char *data, size_t length, const char *digest,
    size_t digest_length, bool packed, size_t *result_length) {
    *result_length = 0;
    if (!encore_cache_digest_valid(digest, digest_length) || length > SIZE_MAX - ENCORE_CACHE_HEADER - 1) return NULL;
    int bound = length >= 65536 && length <= LZ4_MAX_INPUT_SIZE ? LZ4_compressBound((int)length) : 0;
    char *compressed = bound > 0 ? malloc((size_t)bound) : NULL;
    int stored = compressed != NULL ? LZ4_compress_default(data, compressed, (int)length, bound) : 0;
    bool use_lz4 = stored > 0 && (size_t)stored + ENCORE_CACHE_HEADER <= length - length / 8;
    size_t payload_length = use_lz4 ? (size_t)stored : length;
    bool reserved_prefix = length >= 8 && memcmp(data, encore_cache_magic, 8) == 0;
    size_t header = packed || use_lz4 || reserved_prefix ? ENCORE_CACHE_HEADER : 0;
    char *out = calloc(payload_length + header + 1, 1);
    if (out != NULL) {
        if (header) {
            memcpy(out, encore_cache_magic, 8);
            out[8] = use_lz4 ? 1 : 0;
            encore_cache_put_u64((unsigned char *)out + 16, length);
            encore_cache_put_u64((unsigned char *)out + 24, payload_length);
            memcpy(out + 32, digest, 64);
        }
        if (payload_length) memcpy(out + header, use_lz4 ? compressed : data, payload_length);
        *result_length = payload_length + header;
    }
    free(compressed);
    return out;
}

/* A decoder never allocates from an unchecked length. LZ4's maximum expansion
 * ratio is bounded; forged lengths, trailing bytes and unknown codecs miss. */
static char *encore_cache_decode(char *input, size_t *length, char digest[65]) {
    digest[0] = '\0';
    if (*length < 8 || memcmp(input, encore_cache_magic, 8)) return input;
    if (*length < ENCORE_CACHE_HEADER) { free(input); return NULL; }
    unsigned char *p = (unsigned char *)input;
    uint64_t original = encore_cache_u64(p + 16), stored = encore_cache_u64(p + 24);
    bool reserved = false;
    for (size_t i = 9; i < 16; ++i) reserved |= p[i] != 0;
    if (reserved || p[8] > 1 || stored != *length - ENCORE_CACHE_HEADER || original >= SIZE_MAX ||
        !encore_cache_digest_valid(input + 32, 64) ||
        (p[8] == 0 && original != stored) ||
        (p[8] == 1 && (original > LZ4_MAX_INPUT_SIZE || stored > INT_MAX ||
                      original > stored * UINT64_C(255) + 65536))) {
        free(input); return NULL;
    }
    char *out = malloc((size_t)original + 1);
    if (out == NULL) { free(input); return NULL; }
    bool valid = p[8] == 0;
    if (valid && original) memcpy(out, input + ENCORE_CACHE_HEADER, (size_t)original);
    if (p[8] == 1) valid = LZ4_decompress_safe(input + ENCORE_CACHE_HEADER, out,
        (int)stored, (int)original) == (int)original;
    if (valid) {
        memcpy(digest, input + 32, 64); digest[64] = '\0';
        *length = (size_t)original; out[*length] = '\0';
    }
    free(input);
    if (!valid) { free(out); return NULL; }
    return out;
}
#endif
