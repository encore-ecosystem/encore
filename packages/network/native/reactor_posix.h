#if defined(__linux__) || defined(__APPLE__)
#if defined(__linux__)
#include <sys/epoll.h>
#else
#include <sys/event.h>
#endif

#define REACTOR_WATCHES 1025

typedef struct {
    int fd;
    short interests;
    short ready;
    size_t generation;
} reactor_watch;

static int reactor_queue = -1;
static reactor_watch previous_watches[REACTOR_WATCHES];
static size_t previous_count;

static bool reactor_init(void) {
#if defined(__linux__)
    reactor_queue = epoll_create1(EPOLL_CLOEXEC);
#else
    reactor_queue = kqueue();
    if (reactor_queue >= 0) fcntl(reactor_queue, F_SETFD, FD_CLOEXEC);
#endif
    return reactor_queue >= 0;
}

static int reactor_watch_compare(const void *left, const void *right) {
    int a = ((const reactor_watch *)left)->fd;
    int b = ((const reactor_watch *)right)->fd;
    return (a > b) - (a < b);
}

static reactor_watch *reactor_find(reactor_watch *watches, size_t count, int fd) {
    reactor_watch key = {.fd = fd};
    return bsearch(&key, watches, count, sizeof(*watches), reactor_watch_compare);
}

static bool reactor_update(const reactor_watch *old, const reactor_watch *next) {
#if defined(__linux__)
    if (!next) {
        return epoll_ctl(reactor_queue, EPOLL_CTL_DEL, old->fd, NULL) == 0 || errno == EBADF || errno == ENOENT;
    }
    struct epoll_event event = {0};
    event.data.fd = next->fd;
    if (next->interests & POLLIN) event.events |= EPOLLIN;
    if (next->interests & POLLOUT) event.events |= EPOLLOUT;
    if (old && epoll_ctl(reactor_queue, EPOLL_CTL_MOD, next->fd, &event) == 0) return true;
    return epoll_ctl(reactor_queue, EPOLL_CTL_ADD, next->fd, &event) == 0;
#else
    int fd = next ? next->fd : old->fd;
    short old_mask = old ? old->interests : 0;
    short next_mask = next ? next->interests : 0;
    const short masks[] = {POLLIN, POLLOUT};
    const short filters[] = {EVFILT_READ, EVFILT_WRITE};
    for (size_t i = 0; i < 2; i++) {
        struct kevent event;
        if (next_mask & masks[i]) {
            EV_SET(&event, (uintptr_t)fd, filters[i], EV_ADD | EV_ENABLE, 0, 0, NULL);
        } else if (old_mask & masks[i]) {
            EV_SET(&event, (uintptr_t)fd, filters[i], EV_DELETE, 0, 0, NULL);
        } else {
            continue;
        }
        if (kevent(reactor_queue, &event, 1, NULL, 0, NULL) < 0 && errno != ENOENT && errno != EBADF) return false;
    }
    return true;
#endif
}

static int reactor_wait(struct pollfd *fds, const size_t *ids, size_t count, int timeout_ms) {
    reactor_watch watches[REACTOR_WATCHES];
    for (size_t i = 0; i < count; i++) {
        fds[i].revents = 0;
        watches[i] = (reactor_watch){fds[i].fd, fds[i].events, 0, ids[i]};
    }
    qsort(watches, count, sizeof(*watches), reactor_watch_compare);
    size_t unique = 0;
    for (size_t i = 0; i < count; i++) {
        if (unique && watches[unique - 1].fd == watches[i].fd) {
            reactor_watch *existing = &watches[unique - 1];
            existing->interests |= watches[i].interests;
            if (watches[i].generation < existing->generation) existing->generation = watches[i].generation;
        } else {
            watches[unique++] = watches[i];
        }
    }
    for (size_t i = 0; i < previous_count; i++) {
        reactor_watch *old = &previous_watches[i];
        if (!reactor_find(watches, unique, old->fd)) reactor_update(old, NULL);
    }
    for (size_t i = 0; i < unique; i++) {
        reactor_watch *next = &watches[i];
        reactor_watch *old = reactor_find(previous_watches, previous_count, next->fd);
        if (!old || old->generation != next->generation || old->interests != next->interests) {
            if (!reactor_update(old, next)) next->ready = POLLERR;
        }
    }
    memcpy(previous_watches, watches, unique * sizeof(*watches));
    previous_count = unique;
#if defined(__linux__)
    struct epoll_event events[REACTOR_WATCHES];
    int ready = epoll_wait(reactor_queue, events, REACTOR_WATCHES, timeout_ms);
    for (int i = 0; i < ready; i++) {
        reactor_watch *watch = reactor_find(watches, unique, events[i].data.fd);
        if (!watch) continue;
        uint32_t flags = events[i].events;
        if (flags & EPOLLIN) watch->ready |= POLLIN;
        if (flags & EPOLLOUT) watch->ready |= POLLOUT;
        if (flags & EPOLLERR) watch->ready |= POLLERR;
        if (flags & EPOLLHUP) watch->ready |= POLLHUP;
    }
#else
    struct kevent events[REACTOR_WATCHES];
    struct timespec timeout = {timeout_ms / 1000, (long)(timeout_ms % 1000) * 1000000};
    int ready = kevent(reactor_queue, NULL, 0, events, REACTOR_WATCHES, &timeout);
    for (int i = 0; i < ready; i++) {
        reactor_watch *watch = reactor_find(watches, unique, (int)events[i].ident);
        if (!watch) continue;
        if (events[i].filter == EVFILT_READ) watch->ready |= POLLIN;
        if (events[i].filter == EVFILT_WRITE) watch->ready |= POLLOUT;
        if (events[i].flags & EV_ERROR) watch->ready |= POLLERR;
        if (events[i].flags & EV_EOF) watch->ready |= POLLHUP;
    }
#endif
    for (size_t i = 0; i < count; i++) {
        reactor_watch *watch = reactor_find(watches, unique, fds[i].fd);
        if (watch) fds[i].revents = watch->ready & (fds[i].events | POLLERR | POLLHUP);
    }
    return ready;
}
#else
static bool reactor_init(void) { return true; }
static int reactor_wait(struct pollfd *fds, const size_t *ids, size_t count, int timeout_ms) {
    (void)ids;
    return poll(fds, (nfds_t)count, timeout_ms);
}
#endif
