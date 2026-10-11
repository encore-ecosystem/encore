#include "../../runtime/build_resources.h"
#include <assert.h>
#include <stdlib.h>

int main(void) {
    uint64_t number = 0;
    assert(encore_build_memory_number("18446744073709551615\n", &number) && number == UINT64_MAX);
    assert(encore_build_memory_number("0\r\n", &number) && number == 0);
    assert(!encore_build_memory_number("18446744073709551616", &number));
    assert(!encore_build_memory_number("max\n", &number));
    assert(!encore_build_memory_number("42 bytes", &number));
    assert(!encore_build_memory_number("-1", &number));
    assert(!encore_build_memory_number(NULL, &number));
    assert(encore_build_memory_remaining(1024, 256) == 768);
    assert(encore_build_memory_remaining(1024, 1024) == 1);
    assert(encore_build_memory_remaining(1024, UINT64_MAX) == 1);
#ifdef __linux__
    assert(encore_build_cgroup_memory_controller("cpu,memory,pids"));
    assert(encore_build_cgroup_memory_controller("memory"));
    assert(!encore_build_cgroup_memory_controller("memory_extra,cpu"));
    uint64_t restricted = encore_build_cgroup_available_memory();
    const char *expected_limit = getenv("ENCORE_EXPECT_MAX_MEMORY_BYTES");
    if (expected_limit != NULL) {
        uint64_t limit = 0;
        assert(encore_build_memory_number(expected_limit, &limit));
        assert(restricted != 0 && restricted <= limit);
        assert(encore_build_available_memory() <= limit);
        assert(encore_build_effective_memory_budget() <= limit);
    }
#endif
    assert(encore_build_memavailable_line("MemAvailable:  12345 kB\n") == 12345 * UINT64_C(1024));
    assert(encore_build_memavailable_line("MemAvailable:\t42 kB\r\n") == 42 * UINT64_C(1024));
    assert(encore_build_memavailable_line("MemTotal: 12345 kB\n") == 0);
    assert(encore_build_memavailable_line("MemAvailable: -1 kB\n") == 0);
    assert(encore_build_memavailable_line("MemAvailable: 18446744073709551616 kB\n") == 0);
    assert(encore_build_memavailable_line("MemAvailable: 18014398509481984 kB\n") == 0);
    assert(encore_build_memavailable_line("MemAvailable: 42 MB\n") == 0);
    assert(encore_build_memavailable_line("MemAvailable: 42 kB ignored") == 0);
    assert(encore_build_memavailable_line("MemAvailable: 42 k") == 0);
    assert(encore_build_memavailable_line(NULL) == 0);
    assert(encore_build_memory_budget(0) == 0);
    assert(encore_build_memory_budget(1) == 0);
    assert(encore_build_memory_budget(5) == 4);
    assert(encore_build_memory_budget(1024) == 819);
    assert(encore_build_memory_budget(UINT64_MAX) == UINT64_MAX / 5 * 4);
    uint64_t available = encore_build_available_memory();
    assert(available > 0);
    assert(encore_build_memory_budget(available) < available);
    assert(encore_build_effective_memory_budget() > 0);
    return 0;
}
