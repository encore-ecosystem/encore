#if defined(__GLIBC__)
#include <malloc.h>
#endif

void encore_compiler_release_heap(void) {
#if defined(__GLIBC__)
    malloc_trim(0);
#endif
}
