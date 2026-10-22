#include "../packages/core/runtime.c"
#include <assert.h>

/* Character slicing is the established public contains contract, including
 * its treatment of malformed/truncated raw UTF-8 strings. */
static bool contains_by_character_slices(encore_str value, encore_str needle) {
    size_t count = encore_str_char_len(needle);
    size_t length = encore_str_char_len(value);
    if (count == 0) return true;
    if (count > length) return false;
    for (size_t position = 0; position <= length - count; ++position) {
        encore_str slice = encore_str_slice_chars(value, position, count);
        bool matches = encore_str_eq(slice, needle);
        encore_str_drop(slice);
        if (matches) return true;
    }
    return false;
}

static uint32_t next(uint32_t *state) {
    *state ^= *state << 13;
    *state ^= *state >> 17;
    *state ^= *state << 5;
    return *state;
}

int main(void) {
    uint32_t state = UINT32_C(0x51c0ffee);
    for (size_t sample = 0; sample < 50000; ++sample) {
        unsigned char bytes[8], pattern[8];
        size_t length = next(&state) % 9;
        size_t wanted = next(&state) % 9;
        for (size_t i = 0; i < length; ++i) bytes[i] = (unsigned char)next(&state);
        for (size_t i = 0; i < wanted; ++i) pattern[i] = (unsigned char)next(&state);
        if (length && sample % 2 == 0) {
            size_t start = next(&state) % length;
            wanted = next(&state) % (length - start + 1);
            memcpy(pattern, bytes + start, wanted);
        }
        encore_str value = encore_str_from_buffer((const char *)bytes, length);
        encore_str needle = encore_str_from_buffer((const char *)pattern, wanted);
        assert(encore_str_contains(value, needle) == contains_by_character_slices(value, needle));
        encore_str_drop(value);
        encore_str_drop(needle);
    }
    return 0;
}
