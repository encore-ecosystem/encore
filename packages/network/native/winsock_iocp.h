#ifndef ENCORE_WINSOCK_IOCP_H
#define ENCORE_WINSOCK_IOCP_H

#include <winsock2.h>
#include <ws2tcpip.h>
#include "pipe_iocp.h"

typedef struct {
    SOCKET socket;
    WSAEVENT signal;
    HANDLE waiter;
    EncoreIocp *iocp;
    ULONG_PTR key;
} EncoreSocketWatch;

/* Only an integer key reaches the completion port. Pending completion packets
 * therefore remain safe when the watch or its socket has already been removed. */
static void CALLBACK encore_socket_notify(void *data, BOOLEAN timed_out) {
    EncoreSocketWatch *watch = data;
    if (!timed_out) encore_iocp_post(watch->iocp, watch->key, NULL);
}

static bool encore_socket_rearm(EncoreSocketWatch *watch) {
    return RegisterWaitForSingleObject(&watch->waiter, watch->signal,
        encore_socket_notify, watch, INFINITE, WT_EXECUTEONLYONCE) != 0;
}

static bool encore_socket_watch(EncoreSocketWatch *watch, EncoreIocp *iocp,
                                SOCKET socket, long interests, ULONG_PTR key) {
    WSAEVENT signal = WSACreateEvent();
    if (signal == WSA_INVALID_EVENT) return false;
    *watch = (EncoreSocketWatch){socket, signal, NULL, iocp, key};
    if (WSAEventSelect(socket, signal, interests) == 0 && encore_socket_rearm(watch)) {
        return true;
    }
    WSAEventSelect(socket, NULL, 0);
    WSACloseEvent(signal);
    return false;
}

static bool encore_socket_ready(EncoreSocketWatch *watch, WSANETWORKEVENTS *events) {
    if (watch->waiter) {
        UnregisterWaitEx(watch->waiter, INVALID_HANDLE_VALUE);
        watch->waiter = NULL;
    }
    if (WSAEnumNetworkEvents(watch->socket, watch->signal, events) == SOCKET_ERROR) {
        return false;
    }
    return encore_socket_rearm(watch);
}

static void encore_socket_unwatch(EncoreSocketWatch *watch) {
    if (watch->waiter) UnregisterWaitEx(watch->waiter, INVALID_HANDLE_VALUE);
    WSAEventSelect(watch->socket, NULL, 0);
    WSACloseEvent(watch->signal);
    watch->waiter = NULL;
}

#endif
