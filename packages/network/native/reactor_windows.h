#ifndef ENCORE_REACTOR_WINDOWS_H
#define ENCORE_REACTOR_WINDOWS_H
#include "winsock_iocp.h"

#define MFNET_WINDOWS_WATCHES 1024

typedef struct {
    EncoreSocketWatch watch;
    size_t generation;
    short interests;
    bool active;
    bool probed;
    bool seen;
} MfWindowsWatch;

static EncoreIocp reactor_iocp;
static MfWindowsWatch winsock_watches[MFNET_WINDOWS_WATCHES];
static ULONG_PTR next_watch_key = 1;
static volatile LONG reactor_wake_pending;

static bool reactor_init(void) { return encore_iocp_init(&reactor_iocp); }
static void reactor_notify(void) {
    if (!reactor_iocp.handle) return;
    if (InterlockedExchange(&reactor_wake_pending, 1) == 0 &&
        encore_iocp_post(&reactor_iocp, 0, NULL) != ERROR_SUCCESS) {
        InterlockedExchange(&reactor_wake_pending, 0);
    }
}

static void win_operation_complete(EncoreIocpEvent event);

static MfWindowsWatch *find_socket_watch(SOCKET socket) {
    for (size_t i = 0; i < MFNET_WINDOWS_WATCHES; ++i) {
        MfWindowsWatch *watch = &winsock_watches[i];
        if (watch->active && watch->watch.socket == socket) return watch;
    }
    return NULL;
}

static void drop_socket_watch(MfWindowsWatch *watch) {
    encore_socket_unwatch(&watch->watch);
    watch->active = false;
    watch->seen = false;
}

static MfWindowsWatch *add_socket_watch(SOCKET socket, short interests, size_t generation) {
    MfWindowsWatch *previous = find_socket_watch(socket);
    if (previous) drop_socket_watch(previous);
    long events = FD_CLOSE;
    if (interests & POLLIN) events |= FD_READ | FD_ACCEPT;
    if (interests & POLLOUT) events |= FD_WRITE | FD_CONNECT;
    if (next_watch_key == 0) return NULL;
    for (size_t i = 0; i < MFNET_WINDOWS_WATCHES; ++i) {
        MfWindowsWatch *watch = &winsock_watches[i];
        if (watch->active) continue;
        if (!encore_socket_watch(&watch->watch, &reactor_iocp, socket, events, next_watch_key++)) {
            return NULL;
        }
        watch->active = true;
        watch->probed = false;
        watch->interests = interests;
        watch->generation = generation;
        return watch;
    }
    return NULL;
}

static short windows_socket_events(WSANETWORKEVENTS events) {
    short ready = 0;
    long flags = events.lNetworkEvents;
    if (flags & (FD_READ | FD_ACCEPT)) ready |= POLLIN;
    if (flags & (FD_WRITE | FD_CONNECT)) ready |= POLLOUT;
    if (flags & FD_CLOSE) ready |= POLLHUP;
    for (unsigned i = 0; i < FD_MAX_EVENTS; ++i) {
        if ((flags & (1L << i)) && events.iErrorCode[i]) ready |= POLLERR;
    }
    return ready;
}

static int reactor_wait(struct pollfd *fds, const size_t *generations, size_t count,
                        int timeout) {
    for (size_t i = 0; i < MFNET_WINDOWS_WATCHES; ++i) winsock_watches[i].seen = false;
    for (size_t i = 1; i < count; ++i) {
        fds[i].revents = 0;
        MfWindowsWatch *watch = find_socket_watch(fds[i].fd);
        if (watch && watch->seen) continue;
        short interests = fds[i].events;
        for (size_t j = i + 1; j < count; ++j) {
            if (fds[j].fd == fds[i].fd) interests |= fds[j].events;
        }
        if (watch && (watch->interests != interests || watch->generation != generations[i])) {
            drop_socket_watch(watch);
            watch = NULL;
        }
        if (!watch) {
            watch = add_socket_watch(fds[i].fd, interests, generations[i]);
            if (!watch) {
                fds[i].revents = POLLERR;
                return 1;
            }
        }
        if (!watch->probed) {
            watch->probed = true;
            /* Also observe sockets that became ready synchronously. */
            struct pollfd probe = {fds[i].fd, interests, 0};
            if (WSAPoll(&probe, 1, 0) > 0 && probe.revents) {
                for (size_t j = i; j < count; ++j) {
                    if (fds[j].fd == fds[i].fd) fds[j].revents = probe.revents;
                }
                return 1;
            }
        }
        watch->seen = true;
    }
    for (size_t i = 0; i < MFNET_WINDOWS_WATCHES; ++i) {
        MfWindowsWatch *watch = &winsock_watches[i];
        if (watch->active && !watch->seen) drop_socket_watch(watch);
    }
    EncoreIocpEvent event = encore_iocp_wait(&reactor_iocp, (DWORD)timeout);
    if (event.operation) {
        win_operation_complete(event);
        return 1;
    }
    if (event.error == WAIT_TIMEOUT) return 0;
    if (event.error) return -1;
    if (!event.key) {
        InterlockedExchange(&reactor_wake_pending, 0);
        return 1;
    }
    for (size_t i = 0; i < MFNET_WINDOWS_WATCHES; ++i) {
        MfWindowsWatch *watch = &winsock_watches[i];
        if (!watch->active || watch->watch.key != event.key) continue;
        WSANETWORKEVENTS events;
        short ready = encore_socket_ready(&watch->watch, &events) ? windows_socket_events(events) : POLLERR;
        for (size_t j = 1; j < count; ++j) {
            if (fds[j].fd == watch->watch.socket) fds[j].revents = ready;
        }
        break;
    }
    return 1;
}
#endif
