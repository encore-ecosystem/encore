#ifndef ENCORE_PIPE_IOCP_H
#define ENCORE_PIPE_IOCP_H

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <stdbool.h>
#include <stddef.h>
#include <wchar.h>

#define ENCORE_PIPE_NAME_CAPACITY 256

typedef struct {
    HANDLE handle;
} EncoreIocp;

typedef struct {
    OVERLAPPED request;
} EncorePipeOperation;

typedef struct {
    EncorePipeOperation *operation;
    ULONG_PTR key;
    DWORD size;
    DWORD error;
} EncoreIocpEvent;

static bool encore_iocp_init(EncoreIocp *iocp) {
    iocp->handle = CreateIoCompletionPort(INVALID_HANDLE_VALUE, NULL, 0, 1);
    return iocp->handle != NULL;
}

static DWORD encore_pipe_name(const char *path, size_t size,
                              wchar_t name[ENCORE_PIPE_NAME_CAPACITY]) {
    const wchar_t prefix[] = L"\\\\.\\pipe\\";
    const size_t prefix_size = sizeof(prefix) / sizeof(*prefix) - 1;
    if (size == 0 || size >= ENCORE_PIPE_NAME_CAPACITY - prefix_size) {
        return ERROR_INVALID_NAME;
    }
    for (size_t i = 0; i < size; ++i) {
        if (path[i] == '\0' || path[i] == '\\' || path[i] == '/') {
            return ERROR_INVALID_NAME;
        }
    }
    int count = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, path, (int)size,
                                   name + prefix_size, (int)(ENCORE_PIPE_NAME_CAPACITY - prefix_size - 1));
    if (!count) return GetLastError();
    wmemcpy(name, prefix, prefix_size);
    name[prefix_size + (size_t)count] = L'\0';
    return ERROR_SUCCESS;
}

static HANDLE encore_iocp_attach(EncoreIocp *iocp, HANDLE pipe, ULONG_PTR key) {
    if (pipe == INVALID_HANDLE_VALUE) return INVALID_HANDLE_VALUE;
    if (CreateIoCompletionPort(pipe, iocp->handle, key, 0)) return pipe;
    DWORD error = GetLastError();
    CloseHandle(pipe);
    SetLastError(error);
    return INVALID_HANDLE_VALUE;
}

static HANDLE encore_pipe_listen(EncoreIocp *iocp, const wchar_t *name,
                                 bool first, ULONG_PTR key) {
    DWORD flags = PIPE_ACCESS_DUPLEX | FILE_FLAG_OVERLAPPED;
    if (first) flags |= FILE_FLAG_FIRST_PIPE_INSTANCE;
    HANDLE pipe = CreateNamedPipeW(name, flags,
        PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT | PIPE_REJECT_REMOTE_CLIENTS,
        PIPE_UNLIMITED_INSTANCES, 65536, 65536, 0, NULL);
    return encore_iocp_attach(iocp, pipe, key);
}

static HANDLE encore_pipe_connect(EncoreIocp *iocp, const wchar_t *name, ULONG_PTR key) {
    HANDLE pipe = CreateFileW(name, GENERIC_READ | GENERIC_WRITE, 0, NULL,
        OPEN_EXISTING, FILE_FLAG_OVERLAPPED | SECURITY_SQOS_PRESENT |
        SECURITY_IDENTIFICATION, NULL);
    return encore_iocp_attach(iocp, pipe, key);
}

static DWORD encore_iocp_post(EncoreIocp *iocp, ULONG_PTR key, EncorePipeOperation *op) {
    if (PostQueuedCompletionStatus(iocp->handle, 0, key, op ? &op->request : NULL)) {
        return ERROR_SUCCESS;
    }
    return GetLastError();
}

/* A successful submission owns the operation and its buffer until wait yields it.
 * OVERLAPPED must remain at the same address, including during cancellation. */
static DWORD encore_pipe_accept(EncoreIocp *iocp, HANDLE pipe, ULONG_PTR key,
                                EncorePipeOperation *op) {
    ZeroMemory(op, sizeof(*op));
    if (ConnectNamedPipe(pipe, &op->request)) return ERROR_SUCCESS;
    DWORD error = GetLastError();
    if (error == ERROR_PIPE_CONNECTED) return encore_iocp_post(iocp, key, op);
    return error == ERROR_IO_PENDING ? ERROR_SUCCESS : error;
}

static DWORD encore_pipe_read(EncoreIocp *iocp, HANDLE pipe, ULONG_PTR key,
                              void *buffer, DWORD size, EncorePipeOperation *op) {
    ZeroMemory(op, sizeof(*op));
    if (ReadFile(pipe, buffer, size, NULL, &op->request)) return ERROR_SUCCESS;
    DWORD error = GetLastError();
    if (error == ERROR_BROKEN_PIPE || error == ERROR_PIPE_NOT_CONNECTED) {
        return encore_iocp_post(iocp, key, op);
    }
    return error == ERROR_IO_PENDING ? ERROR_SUCCESS : error;
}

static DWORD encore_pipe_write(HANDLE pipe, const void *buffer, DWORD size,
                               EncorePipeOperation *op) {
    ZeroMemory(op, sizeof(*op));
    if (WriteFile(pipe, buffer, size, NULL, &op->request)) return ERROR_SUCCESS;
    DWORD error = GetLastError();
    return error == ERROR_IO_PENDING ? ERROR_SUCCESS : error;
}

static DWORD encore_pipe_cancel(HANDLE pipe, EncorePipeOperation *op) {
    if (CancelIoEx(pipe, &op->request)) return ERROR_SUCCESS;
    DWORD error = GetLastError();
    return error == ERROR_NOT_FOUND ? ERROR_SUCCESS : error;
}

static EncoreIocpEvent encore_iocp_wait(EncoreIocp *iocp, DWORD timeout) {
    EncoreIocpEvent event = {0};
    OVERLAPPED *operation = NULL;
    if (!GetQueuedCompletionStatus(iocp->handle, &event.size, &event.key, &operation, timeout)) {
        event.error = GetLastError();
    }
    event.operation = (EncorePipeOperation *)operation;
    return event;
}

#endif
