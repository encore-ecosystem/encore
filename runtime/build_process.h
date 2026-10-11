#ifndef ENCORE_BUILD_PROCESS_H
#define ENCORE_BUILD_PROCESS_H

/* A coordinator-owned child and its tool descendants. No shell command is
 * assembled: arguments, working directory and log paths are separate inputs.
 * Closing a running child always cancels and reaps it before freeing storage.
 * Handles are deliberately not shared with compilation threads. */
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#include <limits.h>
#include <errno.h>

#ifdef _WIN32
#include <windows.h>
#else
#include <fcntl.h>
#include <signal.h>
#include <spawn.h>
#include <sys/resource.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>
#ifdef __linux__
#include <sys/prctl.h>
#elif defined(__APPLE__)
#include <sys/event.h>
#include <pthread.h>
#endif
extern char **environ;
#endif

#define ENCORE_BUILD_PROCESS_RUNNING INT_MIN
#define ENCORE_BUILD_PROCESS_ERROR (INT_MIN + 1)

typedef struct encore_build_process {
    size_t identity;
    struct encore_build_process *next;
    bool finished;
    int exit_code;
    uint64_t peak_rss;
#ifdef _WIN32
    HANDLE process;
    HANDLE job;
#else
    pid_t pid;
    bool owns_group;
#endif
} encore_build_process;

/* Only the coordinator thread accesses this registry. Handles are monotonically
 * assigned identities, not addresses: closing a copied/stale handle cannot
 * dereference freed storage or accidentally close a newly allocated child. */
static encore_build_process *encore_build_process_children;
static size_t encore_build_process_sequence;
static uint64_t encore_build_process_owner;
static bool encore_build_process_registered;
static inline void encore_build_process_close(size_t identity);

static inline uint64_t encore_build_process_pid(void) {
#ifdef _WIN32
    return (uint64_t)GetCurrentProcessId();
#else
    return (uint64_t)getpid();
#endif
}

static inline encore_build_process *encore_build_process_lookup(size_t identity) {
    if (identity == 0 || encore_build_process_owner != encore_build_process_pid()) return NULL;
    for (encore_build_process *child = encore_build_process_children; child != NULL; child = child->next)
        if (child->identity == identity) return child;
    return NULL;
}

static void encore_build_process_shutdown(void) {
    if (encore_build_process_owner != encore_build_process_pid()) return;
    while (encore_build_process_children != NULL)
        encore_build_process_close(encore_build_process_children->identity);
}

#ifndef _WIN32
static volatile sig_atomic_t encore_build_process_signal;
static void encore_build_process_interrupt(int signal_number) {
    encore_build_process_signal = signal_number;
}
#endif

static inline int encore_build_process_interrupted(void) {
#ifdef _WIN32
    return 0;
#else
    return (int)encore_build_process_signal;
#endif
}

static inline bool encore_build_process_register(void) {
    if (!encore_build_process_registered) {
        if (atexit(encore_build_process_shutdown) != 0) return false;
#ifndef _WIN32
        /* Do not replace an embedding application's custom signal handlers.
         * The compiler coordinator polls this flag and performs normal, reaped
         * cleanup. Signal handlers themselves never allocate or wait. */
        const int signals[] = {SIGINT, SIGTERM};
        for (size_t index = 0; index < sizeof(signals) / sizeof(signals[0]); ++index) {
            struct sigaction old, action;
            memset(&action, 0, sizeof(action));
            action.sa_handler = encore_build_process_interrupt;
            sigemptyset(&action.sa_mask);
            if (sigaction(signals[index], NULL, &old) != 0) return false;
            if (old.sa_handler == SIG_DFL && sigaction(signals[index], &action, NULL) != 0) return false;
        }
#endif
        encore_build_process_registered = true;
    }
    if (encore_build_process_owner != encore_build_process_pid()) {
        encore_build_process_children = NULL;
        encore_build_process_owner = encore_build_process_pid();
    }
    return encore_build_process_sequence != SIZE_MAX;
}

#ifndef _WIN32
static volatile sig_atomic_t encore_build_worker_group;
static void encore_build_worker_parent_died(int signal_number) {
    (void)signal_number;
    /* The worker was spawned as the leader of its own process group. All
     * Clang/linker descendants share it; no unrelated terminal process does. */
    pid_t group = (pid_t)encore_build_worker_group;
    if (group > 0) kill(-group, SIGKILL);
    _exit(137);
}
#ifdef __APPLE__
static void *encore_build_worker_parent_watch(void *argument) {
    int queue = (int)(intptr_t)argument;
    struct kevent event;
    int count;
    do { count = kevent(queue, NULL, 0, &event, 1, NULL); } while (count < 0 && errno == EINTR);
    close(queue);
    encore_build_worker_parent_died(SIGTERM);
    return NULL;
}
#endif
#endif

/* Call before reading a worker request. Kernel-backed parent-death notification
 * also covers SIGKILL/crashes, where coordinator atexit cannot run. */
static inline bool encore_build_worker_watch_parent(uint64_t parent) {
#ifdef _WIN32
    (void)parent; /* The coordinator's kill-on-close Job Object owns this tree. */
    return true;
#else
    if (parent == 0 || parent > INT_MAX || getpid() != getpgrp()) return false;
    struct sigaction action;
    memset(&action, 0, sizeof(action));
    action.sa_handler = encore_build_worker_parent_died;
    sigemptyset(&action.sa_mask);
    encore_build_worker_group = (sig_atomic_t)getpid();
    if (sigaction(SIGTERM, &action, NULL) != 0) return false;
#ifdef __linux__
    if (prctl(PR_SET_PDEATHSIG, SIGTERM) != 0) return false;
    if ((uint64_t)getppid() != parent) encore_build_worker_parent_died(SIGTERM);
    return true;
#elif defined(__APPLE__)
    int queue = kqueue();
    if (queue < 0) return false;
    if (fcntl(queue, F_SETFD, FD_CLOEXEC) < 0) { close(queue); return false; }
    struct kevent event;
    EV_SET(&event, (uintptr_t)parent, EVFILT_PROC, EV_ADD | EV_ONESHOT, NOTE_EXIT, 0, NULL);
    if (kevent(queue, &event, 1, NULL, 0, NULL) != 0) {
        int saved = errno; close(queue);
        if (saved == ESRCH) encore_build_worker_parent_died(SIGTERM);
        return false;
    }
    if ((uint64_t)getppid() != parent) { close(queue); encore_build_worker_parent_died(SIGTERM); }
    pthread_t watcher;
    if (pthread_create(&watcher, NULL, encore_build_worker_parent_watch, (void *)(intptr_t)queue) != 0) {
        close(queue); return false;
    }
    pthread_detach(watcher);
    return true;
#else
    return false;
#endif
#endif
}

#ifdef _WIN32
static inline wchar_t *encore_build_process_wide(const char *text) {
    if (text == NULL) return NULL;
    int length = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text, -1, NULL, 0);
    if (length == 0) return NULL;
    wchar_t *wide = calloc((size_t)length, sizeof(*wide));
    if (wide != NULL && !MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text, -1, wide, length)) {
        free(wide);
        return NULL;
    }
    return wide;
}

/* Follow the Windows CRT argv rules, including backslashes preceding a quote
 * or the closing quote. Always quote every argument; never involve cmd.exe. */
static inline wchar_t *encore_build_process_command(const char *program, const char *const *args, size_t count) {
    size_t capacity = 1;
    for (size_t index = 0; index <= count; ++index) {
        const char *arg = index == 0 ? program : args[index - 1];
        if (arg == NULL || capacity > 32763 || strlen(arg) > (32767 - capacity - 4) / 2) return NULL;
        capacity += 2 * strlen(arg) + 4;
    }
    wchar_t *command = calloc(capacity, sizeof(*command));
    if (command == NULL) return NULL;
    size_t offset = 0;
    for (size_t index = 0; index <= count; ++index) {
        wchar_t *arg = encore_build_process_wide(index == 0 ? program : args[index - 1]);
        if (arg == NULL) { free(command); return NULL; }
        if (index != 0) command[offset++] = L' ';
        command[offset++] = L'"';
        size_t slashes = 0;
        for (size_t position = 0;; ++position) {
            wchar_t ch = arg[position];
            if (ch == L'\\') { ++slashes; continue; }
            size_t copies = (ch == L'"' || ch == L'\0') ? 2 * slashes : slashes;
            while (copies-- != 0) command[offset++] = L'\\';
            slashes = 0;
            if (ch == L'\0') break;
            if (ch == L'"') command[offset++] = L'\\';
            command[offset++] = ch;
        }
        command[offset++] = L'"';
        free(arg);
    }
    command[offset] = L'\0';
    return command;
}

static inline HANDLE encore_build_process_log(const char *path, SECURITY_ATTRIBUTES *attributes) {
    wchar_t *wide = encore_build_process_wide(path);
    if (wide == NULL) return INVALID_HANDLE_VALUE;
    HANDLE file = CreateFileW(wide, GENERIC_WRITE, FILE_SHARE_READ, attributes,
        CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OPEN_REPARSE_POINT, NULL);
    free(wide);
    if (file != INVALID_HANDLE_VALUE) {
        BY_HANDLE_FILE_INFORMATION information;
        if (!GetFileInformationByHandle(file, &information) ||
            (information.dwFileAttributes & (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT))) {
            CloseHandle(file);
            return INVALID_HANDLE_VALUE;
        }
    }
    return file;
}
#endif

static inline size_t encore_build_process_spawn(const char *program, const char *const *args, size_t count,
    const char *directory, const char *stdout_path, const char *stderr_path) {
    if (program == NULL || *program == '\0' || directory == NULL || stdout_path == NULL ||
        stderr_path == NULL || strcmp(stdout_path, stderr_path) == 0 || count > 65536 ||
        (count != 0 && args == NULL)) return 0;
    for (size_t index = 0; index < count; ++index) if (args[index] == NULL) return 0;
    if (!encore_build_process_register() || encore_build_process_interrupted() != 0) return 0;
    encore_build_process *child = calloc(1, sizeof(*child));
    if (child == NULL) return 0;
#ifdef _WIN32
    wchar_t *application = encore_build_process_wide(program);
    wchar_t *command = encore_build_process_command(program, args, count);
    wchar_t *cwd = encore_build_process_wide(directory);
    SECURITY_ATTRIBUTES attributes = {sizeof(attributes), NULL, TRUE};
    HANDLE output = encore_build_process_log(stdout_path, &attributes);
    HANDLE error = encore_build_process_log(stderr_path, &attributes);
    HANDLE input = CreateFileW(L"NUL", GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE,
        &attributes, OPEN_EXISTING, 0, NULL);
    child->job = CreateJobObjectW(NULL, NULL);
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits = {0};
    limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
    bool valid = application != NULL && command != NULL && cwd != NULL &&
        output != INVALID_HANDLE_VALUE && error != INVALID_HANDLE_VALUE && input != INVALID_HANDLE_VALUE &&
        child->job != NULL && SetInformationJobObject(child->job, JobObjectExtendedLimitInformation, &limits, sizeof(limits));
    /* Only these three handles may enter the worker. Inheriting every open
     * coordinator handle can strand jobserver files and other workers' logs. */
    SIZE_T size = 0;
    InitializeProcThreadAttributeList(NULL, 1, 0, &size);
    LPPROC_THREAD_ATTRIBUTE_LIST list = malloc(size);
    bool initialized = list != NULL && InitializeProcThreadAttributeList(list, 1, 0, &size);
    HANDLE inherited[] = {input, output, error};
    valid = valid && initialized && UpdateProcThreadAttribute(list, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
        inherited, sizeof(inherited), NULL, NULL);
    STARTUPINFOEXW startup = {0};
    startup.StartupInfo.cb = sizeof(startup);
    startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
    startup.StartupInfo.hStdInput = input;
    startup.StartupInfo.hStdOutput = output;
    startup.StartupInfo.hStdError = error;
    startup.lpAttributeList = list;
    PROCESS_INFORMATION information = {0};
    bool created = valid && CreateProcessW(application, command, NULL, NULL, TRUE,
        CREATE_SUSPENDED | CREATE_NO_WINDOW | EXTENDED_STARTUPINFO_PRESENT, NULL, cwd,
        &startup.StartupInfo, &information);
    if (created) {
        valid = AssignProcessToJobObject(child->job, information.hProcess) && ResumeThread(information.hThread) != (DWORD)-1;
        if (valid) child->process = information.hProcess;
        else { TerminateProcess(information.hProcess, 1); WaitForSingleObject(information.hProcess, INFINITE); CloseHandle(information.hProcess); }
        CloseHandle(information.hThread);
    } else valid = false;
    if (initialized) DeleteProcThreadAttributeList(list);
    free(list);
    if (input != INVALID_HANDLE_VALUE) CloseHandle(input);
    if (output != INVALID_HANDLE_VALUE) CloseHandle(output);
    if (error != INVALID_HANDLE_VALUE) CloseHandle(error);
    free(application); free(command); free(cwd);
    if (!valid) { if (child->job != NULL) CloseHandle(child->job); free(child); return 0; }
#else
    char **argv = calloc(count + 2, sizeof(*argv));
    if (argv == NULL) { free(child); return 0; }
    argv[0] = (char *)program;
    for (size_t index = 0; index < count; ++index) argv[index + 1] = (char *)args[index];
    posix_spawn_file_actions_t actions;
    posix_spawnattr_t attributes;
    int status = posix_spawn_file_actions_init(&actions);
    if (status != 0) { free(argv); free(child); return 0; }
    status = posix_spawnattr_init(&attributes);
    if (status != 0) { posix_spawn_file_actions_destroy(&actions); free(argv); free(child); return 0; }
    int flags = O_WRONLY | O_CREAT | O_TRUNC | O_NOFOLLOW;
    status = posix_spawn_file_actions_addchdir_np(&actions, directory);
    if (status == 0) status = posix_spawn_file_actions_addopen(&actions, STDIN_FILENO, "/dev/null", O_RDONLY, 0);
    if (status == 0) status = posix_spawn_file_actions_addopen(&actions, STDOUT_FILENO, stdout_path, flags, 0600);
    if (status == 0) status = posix_spawn_file_actions_addopen(&actions, STDERR_FILENO, stderr_path, flags, 0600);
    sigset_t defaults, mask;
    sigemptyset(&defaults); sigaddset(&defaults, SIGINT); sigaddset(&defaults, SIGTERM); sigaddset(&defaults, SIGPIPE);
    sigemptyset(&mask);
    if (status == 0) status = posix_spawnattr_setsigdefault(&attributes, &defaults);
    if (status == 0) status = posix_spawnattr_setsigmask(&attributes, &mask);
    /* Coordinators isolate workers. Tools launched by a guarded worker must
     * stay inside that worker's group, including their own subprocesses:
     * parent-death kill must terminate the entire tree, not just its leader. */
    child->owns_group = encore_build_worker_group == 0;
    short spawn_flags = POSIX_SPAWN_SETSIGDEF | POSIX_SPAWN_SETSIGMASK;
    if (child->owns_group) {
        if (status == 0) status = posix_spawnattr_setpgroup(&attributes, 0);
        spawn_flags |= POSIX_SPAWN_SETPGROUP;
    }
    if (status == 0) status = posix_spawnattr_setflags(&attributes, spawn_flags);
    if (status == 0) status = posix_spawnp(&child->pid, program, &actions, &attributes, argv, environ);
    posix_spawnattr_destroy(&attributes);
    posix_spawn_file_actions_destroy(&actions);
    free(argv);
    if (status != 0) { free(child); return 0; }
#endif
    child->identity = ++encore_build_process_sequence;
    child->next = encore_build_process_children;
    encore_build_process_children = child;
    return child->identity;
}

static inline int encore_build_process_poll(size_t raw_child) {
    encore_build_process *child = encore_build_process_lookup(raw_child);
    if (child == NULL) return ENCORE_BUILD_PROCESS_ERROR;
    if (child->finished) return child->exit_code;
#ifdef _WIN32
    DWORD waited = WaitForSingleObject(child->process, 0);
    if (waited == WAIT_TIMEOUT) return ENCORE_BUILD_PROCESS_RUNNING;
    DWORD status;
    if (waited != WAIT_OBJECT_0 || !GetExitCodeProcess(child->process, &status)) return ENCORE_BUILD_PROCESS_ERROR;
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION information;
    if (QueryInformationJobObject(child->job, JobObjectExtendedLimitInformation, &information, sizeof(information), NULL))
        child->peak_rss = (uint64_t)information.PeakProcessMemoryUsed;
    child->exit_code = (int)status;
    TerminateJobObject(child->job, 1); /* A completed worker cannot leave tools running. */
#else
    int status;
    struct rusage usage;
    pid_t waited;
    do { waited = wait4(child->pid, &status, WNOHANG, &usage); } while (waited < 0 && errno == EINTR);
    if (waited == 0) return ENCORE_BUILD_PROCESS_RUNNING;
    if (waited != child->pid) return ENCORE_BUILD_PROCESS_ERROR;
    child->exit_code = WIFEXITED(status) ? WEXITSTATUS(status) : (WIFSIGNALED(status) ? 128 + WTERMSIG(status) : 1);
#ifdef __APPLE__
    child->peak_rss = (uint64_t)usage.ru_maxrss;
#else
    child->peak_rss = (uint64_t)usage.ru_maxrss * 1024;
#endif
    if (child->owns_group) kill(-child->pid, SIGKILL);
#endif
    child->finished = true;
    return child->exit_code;
}

static inline int encore_build_process_cancel(size_t raw_child) {
    encore_build_process *child = encore_build_process_lookup(raw_child);
    if (child == NULL) return ENCORE_BUILD_PROCESS_ERROR;
    if (child->finished) return child->exit_code;
#ifdef _WIN32
    TerminateJobObject(child->job, 1);
    if (WaitForSingleObject(child->process, INFINITE) != WAIT_OBJECT_0) return ENCORE_BUILD_PROCESS_ERROR;
#else
    /* Escalate promptly even when a tool ignores SIGTERM. This API never
     * forgets a live PID: wait4 below reaps the exact owned process. */
    kill(child->owns_group ? -child->pid : child->pid, SIGTERM);
    for (size_t attempt = 0; attempt < 20; ++attempt) {
        int status = encore_build_process_poll(raw_child);
        if (status != ENCORE_BUILD_PROCESS_RUNNING) return status;
        struct timespec delay = {0, 5000000};
        while (nanosleep(&delay, &delay) < 0 && errno == EINTR) {}
    }
    kill(child->owns_group ? -child->pid : child->pid, SIGKILL);
#endif
    int result;
    do { result = encore_build_process_poll(raw_child); } while (result == ENCORE_BUILD_PROCESS_RUNNING);
    return result;
}

static inline uint64_t encore_build_process_peak_rss(size_t raw_child) {
    encore_build_process *child = encore_build_process_lookup(raw_child);
    return child == NULL ? 0 : child->peak_rss;
}

static inline void encore_build_process_close(size_t raw_child) {
    encore_build_process *child = encore_build_process_lookup(raw_child);
    if (child == NULL) return;
    encore_build_process_cancel(raw_child);
#ifdef _WIN32
    CloseHandle(child->process);
    CloseHandle(child->job);
#endif
    encore_build_process **link = &encore_build_process_children;
    while (*link != NULL && *link != child) link = &(*link)->next;
    if (*link == child) *link = child->next;
    free(child);
}

#endif
