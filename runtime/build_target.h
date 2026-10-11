#ifndef ENCORE_BUILD_TARGET_H
#define ENCORE_BUILD_TARGET_H

#include <stdbool.h>

/* OS alone cannot identify the ABI of a Windows compiler executable. Use the
 * target of its native runtime, including when produced by a cross compiler. */
bool encore_compiler_host_is_windows_gnu(void) {
#if defined(_WIN32) && defined(__MINGW32__)
    return true;
#else
    return false;
#endif
}

#endif
