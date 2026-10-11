#ifndef _WIN32
#ifdef __APPLE__
#define _DARWIN_C_SOURCE
#endif
#define _GNU_SOURCE
#define _POSIX_C_SOURCE 200809L
#endif
#include "../../runtime/build_process.h"
#include <stdio.h>

int main(int argc, char **argv) {
    if (argc != 7) return 2;
    char parent[32];
    snprintf(parent, sizeof(parent), "%llu", (unsigned long long)encore_build_process_pid());
    const char *args[] = {"-c", argv[3], parent};
    size_t child = encore_build_process_spawn(argv[2], args, 3, argv[4], argv[5], argv[6]);
    if (child == 0) return 3;
    if (strcmp(argv[1], "exit") == 0) {
        if (getchar() != '\n') return 4;
        /* Deliberately no close: ordinary exit must reap the owned worker. */
        return 0;
    }
    for (;;) {
        int interrupted = encore_build_process_interrupted();
        if (interrupted != 0) return 128 + interrupted;
        int status = encore_build_process_poll(child);
        if (status != ENCORE_BUILD_PROCESS_RUNNING) return status;
#ifdef _WIN32
        Sleep(5);
#else
        struct timespec delay = {0, 5000000};
        while (nanosleep(&delay, &delay) < 0 && errno == EINTR) {}
#endif
    }
}
