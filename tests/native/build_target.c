#include "../../runtime/build_target.h"

int entry(void) {
    return encore_compiler_host_is_windows_gnu() ? 1 : 0;
}
