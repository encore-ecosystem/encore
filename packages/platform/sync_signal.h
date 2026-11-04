#ifndef ENCORE_SYNC_SIGNAL_H
#define ENCORE_SYNC_SIGNAL_H
#include "sync_time.h"
#include <string.h>
#ifdef _WIN32
uint32_t encore_sync_signal_support(void) { return 1; }
size_t encore_sync_signal_new(void) { return 0; }
uint32_t encore_sync_signal_next(size_t token) {
  (void)token;
  return 0;
}
void encore_sync_signal_close(size_t token) { (void)token; }
size_t encore_sync_signal_register(size_t token, size_t waker) {
  (void)token;
  (void)waker;
  return 0;
}
#else
#include <errno.h>
#include <fcntl.h>
#include <sched.h>
#include <signal.h>
#include <unistd.h>
static pthread_mutex_t encore_signal_owner_mutex = PTHREAD_MUTEX_INITIALIZER;
static _Atomic int encore_signal_fd = -1;
static atomic_uint encore_signal_active, encore_signal_pending;
static bool encore_signal_owned;
typedef struct {
  encore_sync_header header;
  encore_sync_mutex mutex;
  encore_sync_condition condition;
  int read_fd, write_fd;
  pthread_t thread;
  bool closed, joining, joined;
  unsigned pending;
  encore_sync_waiter *waiters;
  struct sigaction previous_int, previous_term;
} encore_sync_signals;
static void encore_sync_signal_handler(int number) {
  int saved_errno = errno;
  atomic_fetch_add_explicit(&encore_signal_active, 1, memory_order_seq_cst);
  int fd = atomic_load_explicit(&encore_signal_fd, memory_order_seq_cst);
  if (fd >= 0) {
    atomic_fetch_or(&encore_signal_pending, number == SIGINT ? 1u : 2u);
    unsigned char byte = 1;
    ssize_t ignored = write(fd, &byte, 1);
    (void)ignored;
  }
  atomic_fetch_sub_explicit(&encore_signal_active, 1, memory_order_seq_cst);
  errno = saved_errno;
}
static void *encore_sync_signal_worker(void *arg) {
  encore_sync_signals *s = arg;
  unsigned char bytes[128];
  for (;;) {
    ssize_t count = read(s->read_fd, bytes, sizeof(bytes));
    if (count < 0 && errno == EINTR)
      continue;
    if (count <= 0)
      break;
    encore_sync_mutex_lock(&s->mutex);
    if (s->closed) {
      encore_sync_mutex_unlock(&s->mutex);
      break;
    }
    s->pending |= atomic_exchange(&encore_signal_pending, 0);
    if (s->pending)
      encore_sync_notify(&s->waiters);
    encore_sync_mutex_unlock(&s->mutex);
  }
  return NULL;
}
uint32_t encore_sync_signal_support(void) {
  if (!atomic_is_lock_free(&encore_signal_fd) ||
      !atomic_is_lock_free(&encore_signal_active) ||
      !atomic_is_lock_free(&encore_signal_pending))
    return 1;
  pthread_mutex_lock(&encore_signal_owner_mutex);
  struct sigaction a, b;
  bool busy = encore_signal_owned || sigaction(SIGINT, NULL, &a) != 0 ||
              sigaction(SIGTERM, NULL, &b) != 0;
  if (!busy)
    busy = a.sa_handler != SIG_DFL || b.sa_handler != SIG_DFL;
  pthread_mutex_unlock(&encore_signal_owner_mutex);
  return busy ? 2 : 0;
}
void encore_sync_signal_close(size_t token) {
  encore_sync_signals *s = (encore_sync_signals *)(uintptr_t)token;
  if (!s)
    return;
  encore_sync_mutex_lock(&s->mutex);
  bool close_here = !s->closed;
  if (close_here) {
    s->closed = true;
    encore_sync_notify(&s->waiters);
  }
  bool join_here = !s->joining;
  if (join_here)
    s->joining = true;
  encore_sync_mutex_unlock(&s->mutex);
  if (join_here) {
    pthread_mutex_lock(&encore_signal_owner_mutex);
    atomic_store(&encore_signal_fd, -1);
    struct sigaction current;
    if (sigaction(SIGINT, NULL, &current) == 0 &&
        current.sa_handler == encore_sync_signal_handler)
      sigaction(SIGINT, &s->previous_int, NULL);
    if (sigaction(SIGTERM, NULL, &current) == 0 &&
        current.sa_handler == encore_sync_signal_handler)
      sigaction(SIGTERM, &s->previous_term, NULL);
    while (atomic_load(&encore_signal_active) != 0)
      sched_yield();
    unsigned char byte = 0;
    ssize_t ignored = write(s->write_fd, &byte, 1);
    (void)ignored;
    pthread_join(s->thread, NULL);
    close(s->read_fd);
    close(s->write_fd);
    encore_signal_owned = false;
    atomic_store(&encore_signal_pending, 0);
    pthread_mutex_unlock(&encore_signal_owner_mutex);
    encore_sync_mutex_lock(&s->mutex);
    s->joined = true;
    encore_sync_condition_notify(&s->condition);
    encore_sync_mutex_unlock(&s->mutex);
  } else {
    encore_sync_mutex_lock(&s->mutex);
    while (!s->joined)
      encore_sync_condition_wait(&s->condition, &s->mutex, 0, true);
    encore_sync_mutex_unlock(&s->mutex);
  }
}
static void encore_sync_signal_destroy(encore_sync_header *h) {
  encore_sync_signals *s = (encore_sync_signals *)h;
  encore_sync_signal_close((size_t)(uintptr_t)s);
  encore_sync_condition_destroy(&s->condition);
  encore_sync_mutex_destroy(&s->mutex);
  free(s);
}
size_t encore_sync_signal_new(void) {
  if (encore_sync_signal_support() != 0)
    return 0;
  pthread_mutex_lock(&encore_signal_owner_mutex);
  struct sigaction previous_int, previous_term;
  if (encore_signal_owned || sigaction(SIGINT, NULL, &previous_int) != 0 ||
      sigaction(SIGTERM, NULL, &previous_term) != 0 ||
      previous_int.sa_handler != SIG_DFL ||
      previous_term.sa_handler != SIG_DFL) {
    pthread_mutex_unlock(&encore_signal_owner_mutex);
    return 0;
  }
  encore_sync_signals *s = calloc(1, sizeof(*s));
  int fds[2];
  if (!s) {
    pthread_mutex_unlock(&encore_signal_owner_mutex);
    return 0;
  }
  if (pipe(fds) != 0) {
    free(s);
    pthread_mutex_unlock(&encore_signal_owner_mutex);
    return 0;
  }
  int flags = fcntl(fds[1], F_GETFL, 0);
  if (flags < 0 || fcntl(fds[1], F_SETFL, flags | O_NONBLOCK) < 0 ||
      fcntl(fds[0], F_SETFD, FD_CLOEXEC) < 0 ||
      fcntl(fds[1], F_SETFD, FD_CLOEXEC) < 0 ||
      !encore_sync_mutex_init(&s->mutex)) {
    close(fds[0]);
    close(fds[1]);
    free(s);
    pthread_mutex_unlock(&encore_signal_owner_mutex);
    return 0;
  }
  if (!encore_sync_condition_init(&s->condition)) {
    encore_sync_mutex_destroy(&s->mutex);
    close(fds[0]);
    close(fds[1]);
    free(s);
    pthread_mutex_unlock(&encore_signal_owner_mutex);
    return 0;
  }
  s->read_fd = fds[0];
  s->write_fd = fds[1];
  s->previous_int = previous_int;
  s->previous_term = previous_term;
  struct sigaction action;
  memset(&action, 0, sizeof(action));
  sigemptyset(&action.sa_mask);
  action.sa_handler = encore_sync_signal_handler;
  action.sa_flags = SA_RESTART;
  if (pthread_create(&s->thread, NULL, encore_sync_signal_worker, s) != 0) {
    encore_sync_condition_destroy(&s->condition);
    encore_sync_mutex_destroy(&s->mutex);
    close(fds[0]);
    close(fds[1]);
    free(s);
    pthread_mutex_unlock(&encore_signal_owner_mutex);
    return 0;
  }
  atomic_store(&encore_signal_pending, 0);
  atomic_store(&encore_signal_fd, fds[1]);
  bool installed_int = sigaction(SIGINT, &action, NULL) == 0;
  bool installed_term = installed_int && sigaction(SIGTERM, &action, NULL) == 0;
  if (!installed_term) {
    atomic_store(&encore_signal_fd, -1);
    if (installed_int)
      sigaction(SIGINT, &previous_int, NULL);
    while (atomic_load(&encore_signal_active) != 0)
      sched_yield();
    encore_sync_mutex_lock(&s->mutex);
    s->closed = true;
    encore_sync_mutex_unlock(&s->mutex);
    unsigned char byte = 0;
    ssize_t ignored = write(fds[1], &byte, 1);
    (void)ignored;
    pthread_join(s->thread, NULL);
    encore_sync_condition_destroy(&s->condition);
    encore_sync_mutex_destroy(&s->mutex);
    close(fds[0]);
    close(fds[1]);
    free(s);
    pthread_mutex_unlock(&encore_signal_owner_mutex);
    return 0;
  }
  encore_signal_owned = true;
  encore_sync_header_init(&s->header, ENCORE_SYNC_SIGNAL,
                          encore_sync_signal_destroy);
  pthread_mutex_unlock(&encore_signal_owner_mutex);
  return (size_t)(uintptr_t)s;
}
uint32_t encore_sync_signal_next(size_t token) {
  encore_sync_signals *s = (encore_sync_signals *)(uintptr_t)token;
  if (!s)
    return 3;
  encore_sync_mutex_lock(&s->mutex);
  uint32_t result = 0;
  if (s->pending & 1) {
    s->pending &= ~1u;
    result = 1;
  } else if (s->pending & 2) {
    s->pending &= ~2u;
    result = 2;
  } else if (s->closed)
    result = 3;
  encore_sync_mutex_unlock(&s->mutex);
  return result;
}
size_t encore_sync_signal_register(size_t token, size_t waker) {
  encore_sync_signals *s = (encore_sync_signals *)(uintptr_t)token;
  if (!s)
    return 0;
  encore_sync_mutex_lock(&s->mutex);
  if (s->closed || s->pending) {
    encore_sync_mutex_unlock(&s->mutex);
    return 0;
  }
  encore_sync_waiter *w =
      encore_sync_waiter_new(&s->header, &s->mutex, &s->waiters, waker);
  encore_sync_mutex_unlock(&s->mutex);
  return w ? (size_t)(uintptr_t)w : SIZE_MAX;
}
#endif
#endif
