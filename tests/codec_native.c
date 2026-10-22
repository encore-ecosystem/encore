#include "../packages/core/runtime.c"
#include <assert.h>
int main(void) {
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
