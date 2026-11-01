#include "../packages/core/runtime.c"
#include <assert.h>
static void scalar_snapshot_contract(void) {
    unsigned char buffer[40];
    const unsigned char expected64[] = { 8, 7, 6, 5, 4, 3, 2, 1 };
    const unsigned char expected32[] = { 0xef, 0xcd, 0xab, 0x89 };
    for (size_t offset = 0; offset < 16; ++offset) {
        memset(buffer, 0xa5, sizeof buffer);
        encore_codec_write_u64_le(buffer + offset, UINT64_C(0x0102030405060708));
        assert(memcmp(buffer + offset, expected64, 8) == 0);
        assert(encore_codec_read_u64_le(buffer + offset) == UINT64_C(0x0102030405060708));
        for (size_t i = 0; i < sizeof buffer; ++i)
            if (i < offset || i >= offset + 8) assert(buffer[i] == 0xa5);
        encore_codec_write_u64_le(buffer + offset, UINT64_MAX);
        assert(encore_codec_read_u64_le(buffer + offset) == UINT64_MAX);
        memset(buffer, 0xa5, sizeof buffer);
        encore_codec_write_u32_le(buffer + offset, UINT32_C(0x89abcdef));
        assert(memcmp(buffer + offset, expected32, 4) == 0);
        assert(encore_codec_read_u32_le(buffer + offset) == UINT32_C(0x89abcdef));
        for (size_t i = 0; i < sizeof buffer; ++i)
            if (i < offset || i >= offset + 4) assert(buffer[i] == 0xa5);
    }
}

int main(void) {
    scalar_snapshot_contract();
    encore_str midpoint = encore_str_from_buffer("1.000000059604644775390625", 26);
    assert(encore_codec_f32_bits(encore_codec_parse_f32(midpoint)) == UINT32_C(0x3f800000));
    const uint64_t cases[] = {0, UINT64_C(0x8000000000000000), 1, UINT64_C(0x0010000000000000), UINT64_C(0x7fefffffffffffff), UINT64_C(0x3ff0000000000001)};
    setlocale(LC_NUMERIC, "ru_RU.UTF-8");
    for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); ++i) {
        encore_str encoded = encore_codec_format_f64(encore_codec_f64_from_bits(cases[i]));
        assert(encore_codec_f64_bits(encore_codec_parse_f64(encoded)) == cases[i]);
    }
    assert(encore_codec_utf8_valid((const uint8_t *)"\xf0\x9f\x90\x9f", 4));
    assert(!encore_codec_utf8_valid((const uint8_t *)"\xc0\xaf", 2));
    assert(!encore_codec_utf8_valid((const uint8_t *)"\xed\xa0\x80", 3));
    assert(!encore_codec_utf8_valid((const uint8_t *)"\xf4\x90\x80\x80", 4));
    return 0;
}
