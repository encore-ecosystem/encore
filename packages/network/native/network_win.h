#ifndef ENCORE_NETWORK_WIN_H
#define ENCORE_NETWORK_WIN_H

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <process.h>

typedef SRWLOCK pthread_mutex_t;
typedef CONDITION_VARIABLE pthread_cond_t;
typedef INIT_ONCE pthread_once_t;
typedef HANDLE pthread_t;
#define PTHREAD_MUTEX_INITIALIZER SRWLOCK_INIT
#define PTHREAD_COND_INITIALIZER CONDITION_VARIABLE_INIT
#define PTHREAD_ONCE_INIT INIT_ONCE_STATIC_INIT
#define SHUT_RDWR SD_BOTH
#define SHUT_WR SD_SEND

static void pthread_mutex_lock(pthread_mutex_t *lock) { AcquireSRWLockExclusive(lock); }
static void pthread_mutex_unlock(pthread_mutex_t *lock) { ReleaseSRWLockExclusive(lock); }
static void pthread_cond_wait(pthread_cond_t *condition, pthread_mutex_t *lock) {
    SleepConditionVariableSRW(condition, lock, INFINITE, 0);
}
static void pthread_cond_signal(pthread_cond_t *condition) { WakeConditionVariable(condition); }

static BOOL CALLBACK mf_once_proc(PINIT_ONCE once, void *param, void **out) {
    (void)once; (void)out;
    (*(void (**)(void))param)();
    return TRUE;
}
static void pthread_once(pthread_once_t *once, void (*fn)(void)) {
    InitOnceExecuteOnce(once, mf_once_proc, &fn, NULL);
}

typedef struct {
    void *(*fn)(void *);
    void *arg;
} MfThreadStart;

static unsigned __stdcall mf_thread_proc(void *data) {
    MfThreadStart start = *(MfThreadStart *)data;
    free(data);
    start.fn(start.arg);
    return 0;
}

static int pthread_create(pthread_t *thread, void *options, void *(*fn)(void *), void *arg) {
    (void)options;
    MfThreadStart *start = malloc(sizeof(*start));
    if (!start) return -1;
    *start = (MfThreadStart){fn, arg};
    *thread = (HANDLE)_beginthreadex(NULL, 0, mf_thread_proc, start, 0, NULL);
    if (*thread) return 0;
    free(start);
    return -1;
}
static void pthread_detach(pthread_t thread) { CloseHandle(thread); }

/* The OpenSSL socket BIO accepts an int. Preserve the Winsock handle exactly. */
static int mf_socket_descriptor(SOCKET socket) {
    if (socket == INVALID_SOCKET) return -1;
    if (socket > INT_MAX) {
        closesocket(socket);
        WSASetLastError(WSAEMFILE);
        return -1;
    }
    return (int)socket;
}
static int mf_socket_open(int family, int type, int protocol) {
    return mf_socket_descriptor(WSASocketW(family, type, protocol, NULL, 0,
                                         WSA_FLAG_OVERLAPPED | WSA_FLAG_NO_HANDLE_INHERIT));
}
static int mf_socket_accept(int fd) { return mf_socket_descriptor(accept((SOCKET)fd, NULL, NULL)); }
static void mf_socket_close(int fd) { if (fd >= 0) closesocket((SOCKET)fd); }
static bool mf_retry_io(void) {
    int error = WSAGetLastError();
    return error == WSAEWOULDBLOCK || error == WSAEINTR;
}
static bool mf_retry_connect(void) {
    int error = WSAGetLastError();
    return error == WSAEWOULDBLOCK || error == WSAEINPROGRESS;
}

static int mf_nonblocking(int fd) {
    u_long enable = 1;
    return ioctlsocket((SOCKET)fd, FIONBIO, &enable);
}

static bool mf_init_network(void) {
    WSADATA data;
    return WSAStartup(MAKEWORD(2, 2), &data) == 0;
}

#endif
