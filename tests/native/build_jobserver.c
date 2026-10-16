#include "../../runtime/build_jobserver.h"

#ifdef _WIN32
#define EXPORT __declspec(dllexport)
#else
#define EXPORT
#endif

EXPORT size_t test_jobserver_create(const char *path, size_t jobs) {
    return encore_build_jobserver_create_path(path, jobs);
}
EXPORT size_t test_jobserver_attach(const char *path) {
    return encore_build_jobserver_attach_path(path);
}
EXPORT int test_jobserver_acquire(size_t server) {
    return encore_build_jobserver_try_acquire(server);
}
EXPORT bool test_jobserver_release(size_t server) {
    return encore_build_jobserver_release(server);
}
EXPORT void test_jobserver_cancel(size_t server) {
    encore_build_jobserver_cancel(server);
}
EXPORT size_t test_jobserver_used(size_t server) {
    return encore_build_jobserver_used(server);
}
EXPORT void test_jobserver_close(size_t server) {
    encore_build_jobserver_close(server);
}
