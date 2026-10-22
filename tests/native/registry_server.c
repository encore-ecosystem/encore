/* Loopback HTTP fixture for native registry discovery and redirect rejection. */
#include <arpa/inet.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <pthread.h>
#include <stdatomic.h>
#include <assert.h>

static struct { int socket; pthread_t thread; char *root; atomic_bool running; } ci_http;
static bool ci_send(int socket, const void *bytes, size_t length) {
    const char *data = bytes;
    while (length > 0) {
        ssize_t sent = send(socket, data, length, MSG_NOSIGNAL);
        if (sent <= 0) return false;
        data += sent; length -= (size_t)sent;
    }
    return true;
}
static void ci_http_request(int socket) {
    struct timeval timeout = {3, 0};
    setsockopt(socket, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
    setsockopt(socket, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
    char request[16384] = {0}; size_t used = 0;
    while (strstr(request, "\r\n\r\n") == NULL && used + 1 < sizeof(request)) {
        ssize_t count = recv(socket, request + used, sizeof(request) - used - 1, 0);
        if (count <= 0) return;
        used += (size_t)count;
    }
    char path[2048] = {0};
    if (sscanf(request, "GET %2047s", path) != 1 || strstr(path, "..") != NULL) return;
    char filename[4096];
    snprintf(filename, sizeof(filename), "%s/requests", ci_http.root);
    FILE *log = fopen(filename, "ab");
    if (log != NULL) { fprintf(log, "%s\n", path); fclose(log); }
    snprintf(filename, sizeof(filename), "%s/mode", ci_http.root);
    char mode[64] = {0}; FILE *file = fopen(filename, "rb");
    if (file != NULL) { (void)fread(mode, 1, sizeof(mode) - 1, file); fclose(file); }
    int status = 200; const char *literal = NULL, *location = "";
    if (!strcmp(path, "/index/config.json")) {
        if (!strcmp(mode, "cross-origin")) literal = "{\"schema\":1,\"api\":\"https://example.org/api/v1\"}";
        else if (!strcmp(mode, "schema")) literal = "{\"schema\":999,\"api\":\"/api/v1\"}";
        snprintf(filename, sizeof(filename), "%s/config.json", ci_http.root);
    } else {
        snprintf(filename, sizeof(filename), "%s%s", ci_http.root, path);
        if (!strcmp(path, "/api/v1/packages/probe")) {
            if (!strcmp(mode, "missing")) { status = 404; literal = "{}"; }
            if (!strcmp(mode, "invalid")) literal = "not JSON";
            if (!strcmp(mode, "redirect")) { status = 302; literal = ""; location = "Location: /must-not-follow\r\n"; }
        }
    }
    file = literal == NULL ? fopen(filename, "rb") : NULL;
    if (literal == NULL && file == NULL) { status = 404; literal = "{}"; }
    size_t length = literal != NULL ? strlen(literal) : 0;
    if (file != NULL) { fseek(file, 0, SEEK_END); long size = ftell(file); if (size < 0) { fclose(file); return; } length = (size_t)size; rewind(file); }
    char header[512];
    int size = snprintf(header, sizeof(header), "HTTP/1.1 %d Fixture\r\n%sContent-Length: %zu\r\nConnection: close\r\n\r\n", status, location, length);
    bool success = ci_send(socket, header, (size_t)size);
    if (literal != NULL) { if (success) ci_send(socket, literal, length); }
    else {
        char buffer[16384]; size_t count;
        while (success && (count = fread(buffer, 1, sizeof(buffer), file)) > 0) success = ci_send(socket, buffer, count);
        fclose(file);
    }
}
static void *ci_http_run(void *unused) {
    (void)unused;
    while (atomic_load(&ci_http.running)) {
        int client = accept(ci_http.socket, NULL, NULL);
        if (client < 0) { if (errno == EINTR) continue; break; }
        ci_http_request(client); close(client);
    }
    return NULL;
}
size_t encore_ci_registry_start(encore_compiler_str directory) {
    ci_http.root = encore_compiler_cstr(directory);
    assert(ci_http.root != NULL);
    ci_http.socket = socket(AF_INET, SOCK_STREAM, 0); assert(ci_http.socket >= 0);
    struct sockaddr_in address = {.sin_family = AF_INET, .sin_addr.s_addr = htonl(INADDR_LOOPBACK)};
    assert(bind(ci_http.socket, (struct sockaddr *)&address, sizeof(address)) == 0 && listen(ci_http.socket, 16) == 0);
    socklen_t length = sizeof(address);
    assert(getsockname(ci_http.socket, (struct sockaddr *)&address, &length) == 0);
    atomic_store(&ci_http.running, true);
    assert(pthread_create(&ci_http.thread, NULL, ci_http_run, NULL) == 0);
    return ntohs(address.sin_port);
}
void encore_ci_registry_stop(void) {
    atomic_store(&ci_http.running, false);
    shutdown(ci_http.socket, SHUT_RDWR);
    pthread_join(ci_http.thread, NULL);
    close(ci_http.socket); free(ci_http.root);
}
