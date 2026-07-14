#include <stddef.h>

static size_t encore_target_pointer_width = sizeof(void *) * 8u;

void encore_llvm_set_target_pointer_width(size_t bits) {
    encore_target_pointer_width = bits == 32u ? 32u : 64u;
}

size_t encore_llvm_target_pointer_width(void) {
    return encore_target_pointer_width;
}
