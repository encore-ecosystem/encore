#ifndef ENCORE_RUNTIME_CODEC_H
#define ENCORE_RUNTIME_CODEC_H
#include <stdint.h>

/* Callers prove the complete 4/8-byte range first. Byte accesses support
 * unaligned snapshots on every host; the wire format is always little endian. */
uint32_t encore_codec_read_u32_le(const uint8_t *p) {
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 |
        (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}
uint64_t encore_codec_read_u64_le(const uint8_t *p) {
    return (uint64_t)p[0] | (uint64_t)p[1] << 8 |
        (uint64_t)p[2] << 16 | (uint64_t)p[3] << 24 |
        (uint64_t)p[4] << 32 | (uint64_t)p[5] << 40 |
        (uint64_t)p[6] << 48 | (uint64_t)p[7] << 56;
}
void encore_codec_write_u32_le(uint8_t *p, uint32_t value) {
    p[0] = (uint8_t)value; p[1] = (uint8_t)(value >> 8);
    p[2] = (uint8_t)(value >> 16); p[3] = (uint8_t)(value >> 24);
}
void encore_codec_write_u64_le(uint8_t *p, uint64_t value) {
    p[0] = (uint8_t)value; p[1] = (uint8_t)(value >> 8);
    p[2] = (uint8_t)(value >> 16); p[3] = (uint8_t)(value >> 24);
    p[4] = (uint8_t)(value >> 32); p[5] = (uint8_t)(value >> 40);
    p[6] = (uint8_t)(value >> 48); p[7] = (uint8_t)(value >> 56);
}
#endif
