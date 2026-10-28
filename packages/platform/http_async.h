#if defined(__linux__) && !defined(__ANDROID__)
#define _GNU_SOURCE
/* Linux ABI shim. HTTP, deadlines and the connection state machine live in Encore.
 * Every public handle is a monotonically allocated ID, never an exposed pointer.
 * The mutex serializes mailboxes and waker registration against completion/close.
 * Only the reactor touches sockets, TLS and DNS, except after it has been joined.
 */
#include <ares.h>
#include <arpa/inet.h>
#include <errno.h>
#include <limits.h>
#include <netinet/in.h>
#include <openssl/err.h>
#include <openssl/ssl.h>
#include <pthread.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/epoll.h>
#include <sys/eventfd.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

#ifndef ENCORE_HTTP_ASYNC_IN_PLATFORM
typedef struct encore_str_object encore_str_object;
typedef struct { encore_str_object *object; } encore_str;
#endif
extern char *encore_str_data(encore_str);
extern size_t encore_str_size(encore_str);
extern encore_str encore_str_from_buffer(const void *, size_t);
extern void encore_async_waker_wake(size_t);

#define ENCORE_HTTP_ASYNC_LIMIT 32
#define ENCORE_HTTP_ASYNC_DNS_FDS 16
typedef struct encore_http_async_runtime encore_http_async_runtime;
typedef struct encore_http_async_token { size_t id; int cancelled; struct encore_http_async_token *next; } encore_http_async_token;
typedef struct encore_http_async_job {
  size_t id;
  encore_http_async_runtime *runtime;
  char *host, *wire, *ca, *result, *headers;
  size_t wire_len, result_len;
  size_t token, body_limit, header_limit, connect_ms, total_ms;
  int http_status;
  int port, tls, status, cancelled, abandoned, read_state;
  size_t waker, owner;
  int fd, interest, ready, connecting;
  SSL_CTX *ctx;
  SSL *ssl;
  ares_channel dns;
  int dns_started, dns_done, dns_count, address_index;
  struct sockaddr_storage addresses[8];
  socklen_t address_lengths[8];
  struct { int fd, interest, ready; } dns_fds[ENCORE_HTTP_ASYNC_DNS_FDS];
} encore_http_async_job;
struct encore_http_async_runtime {
  size_t id;
  int epoll_fd, wake_fd, stopping;
  size_t capacity;
  encore_http_async_job *jobs[ENCORE_HTTP_ASYNC_LIMIT];
  encore_http_async_token *tokens;
  encore_http_async_runtime *next;
};
static pthread_mutex_t encore_http_async_mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_once_t encore_http_async_once = PTHREAD_ONCE_INIT;
static int encore_http_async_init_error;
static size_t encore_http_async_next = 1;
static encore_http_async_runtime *encore_http_async_runtimes;
void encore_http_async_reactor_enter(void) {
  sigset_t set;
  sigemptyset(&set); sigaddset(&set, SIGPIPE);
  pthread_sigmask(SIG_BLOCK, &set, NULL);
}
extern bool encore_async_register_waker_cleanup(void (*hook)(size_t));
void encore_http_async_detach(size_t runtime, size_t waker);
static void encore_http_async_waker_cleanup(size_t waker) { encore_http_async_detach(0, waker); }
static void encore_http_async_initialize(void) {
  if (!encore_async_register_waker_cleanup(encore_http_async_waker_cleanup)) { encore_http_async_init_error = 1; return; }
  encore_http_async_init_error = ares_library_init(ARES_LIB_INIT_ALL);
  OPENSSL_init_ssl(0, NULL);
}
static char *encore_http_async_copy(encore_str s) {
  size_t n = encore_str_size(s);
  if (n == SIZE_MAX) return NULL;
  char *p = malloc(n + 1);
  if (p) { if (n) memcpy(p, encore_str_data(s), n); p[n] = 0; }
  return p;
}
static int encore_http_async_text(encore_str s) {
  size_t n = encore_str_size(s);
  return n <= INT_MAX && (!n || !memchr(encore_str_data(s), 0, n));
}
static encore_http_async_runtime *encore_http_async_rt(size_t id) {
  for (encore_http_async_runtime *r = encore_http_async_runtimes; r; r = r->next) if (r->id == id) return r;
  return NULL;
}
static encore_http_async_job *encore_http_async_find(size_t id) {
  for (encore_http_async_runtime *r = encore_http_async_runtimes; r; r = r->next)
    for (size_t i = 0; i < ENCORE_HTTP_ASYNC_LIMIT; ++i)
      if (r->jobs[i] && r->jobs[i]->id == id) return r->jobs[i];
  return NULL;
}
static void encore_http_async_signal(encore_http_async_runtime *r) {
  uint64_t one = 1;
  ssize_t ignored = write(r->wake_fd, &one, sizeof(one)); (void)ignored;
}
static void encore_http_async_wake(encore_http_async_job *j) {
  size_t token = j->waker;
  j->waker = 0;
  /* Registration, removal and wake are under the same lock. */
  if (token) encore_async_waker_wake(token);
}
static void encore_http_async_set_interest(encore_http_async_job *j, int interest) {
  j->interest = interest;
  if (j->fd < 0) return;
  struct epoll_event ev = {0};
  ev.events = EPOLLERR | EPOLLHUP | EPOLLRDHUP;
  if (interest & 1) ev.events |= EPOLLIN;
  if (interest & 2) ev.events |= EPOLLOUT;
  ev.data.fd = j->fd;
  if (epoll_ctl(j->runtime->epoll_fd, EPOLL_CTL_MOD, j->fd, &ev) < 0 && errno == ENOENT)
    epoll_ctl(j->runtime->epoll_fd, EPOLL_CTL_ADD, j->fd, &ev);
}
static void encore_http_async_dns_socket(void *arg, ares_socket_t fd, int readable, int writable) {
  encore_http_async_job *j = arg;
  size_t slot = ENCORE_HTTP_ASYNC_DNS_FDS;
  for (size_t i = 0; i < ENCORE_HTTP_ASYNC_DNS_FDS; ++i) if (j->dns_fds[i].fd == fd) { slot = i; break; }
  if (!readable && !writable) {
    epoll_ctl(j->runtime->epoll_fd, EPOLL_CTL_DEL, fd, NULL);
    if (slot < ENCORE_HTTP_ASYNC_DNS_FDS) j->dns_fds[slot].fd = -1;
    return;
  }
  if (slot == ENCORE_HTTP_ASYNC_DNS_FDS)
    for (size_t i = 0; i < ENCORE_HTTP_ASYNC_DNS_FDS; ++i) if (j->dns_fds[i].fd == -1) { slot = i; break; }
  if (slot == ENCORE_HTTP_ASYNC_DNS_FDS) return;
  j->dns_fds[slot].fd = fd;
  j->dns_fds[slot].interest = (readable ? 1 : 0) | (writable ? 2 : 0);
  j->dns_fds[slot].ready = 0;
  struct epoll_event ev = {0};
  ev.events = EPOLLERR | EPOLLHUP | (readable ? EPOLLIN : 0) | (writable ? EPOLLOUT : 0);
  ev.data.fd = fd;
  if (epoll_ctl(j->runtime->epoll_fd, EPOLL_CTL_MOD, fd, &ev) < 0 && errno == ENOENT)
    epoll_ctl(j->runtime->epoll_fd, EPOLL_CTL_ADD, fd, &ev);
}
static void encore_http_async_dns_done(void *arg, int status, int timeouts, struct ares_addrinfo *info) {
  (void)timeouts;
  encore_http_async_job *j = arg;
  j->dns_done = 1;
  if (status == ARES_SUCCESS && info)
    for (struct ares_addrinfo_node *p = info->nodes; p && j->dns_count < 8; p = p->ai_next)
      if ((p->ai_family == AF_INET || p->ai_family == AF_INET6) && p->ai_addrlen <= sizeof(struct sockaddr_storage)) {
        memcpy(&j->addresses[j->dns_count], p->ai_addr, p->ai_addrlen);
        j->address_lengths[j->dns_count++] = p->ai_addrlen;
      }
  if (info) ares_freeaddrinfo(info);
}
static void encore_http_async_cleanup_io(encore_http_async_job *j) {
  if (j->dns) { ares_destroy(j->dns); j->dns = NULL; }
  if (j->ssl) { SSL_free(j->ssl); j->ssl = NULL; }
  if (j->ctx) { SSL_CTX_free(j->ctx); j->ctx = NULL; }
  if (j->fd >= 0) {
    epoll_ctl(j->runtime->epoll_fd, EPOLL_CTL_DEL, j->fd, NULL);
    close(j->fd); j->fd = -1;
  }
}
static void encore_http_async_free_job(encore_http_async_job *j) {
  encore_http_async_cleanup_io(j);
  free(j->host); free(j->wire); free(j->ca); free(j->result); free(j->headers); free(j);
}
size_t encore_http_async_runtime_new(size_t capacity) {
  if (!capacity || capacity > ENCORE_HTTP_ASYNC_LIMIT) return 0;
  pthread_once(&encore_http_async_once, encore_http_async_initialize);
  if (encore_http_async_init_error) return 0;
  encore_http_async_runtime *r = calloc(1, sizeof(*r));
  if (!r) return 0;
  r->capacity = capacity;
  r->epoll_fd = epoll_create1(EPOLL_CLOEXEC);
  r->wake_fd = eventfd(0, EFD_CLOEXEC | EFD_NONBLOCK);
  if (r->epoll_fd < 0 || r->wake_fd < 0) {
    if (r->epoll_fd >= 0) close(r->epoll_fd);
    if (r->wake_fd >= 0) close(r->wake_fd);
    free(r); return 0;
  }
  struct epoll_event ev = { .events = EPOLLIN, .data.fd = r->wake_fd };
  if (epoll_ctl(r->epoll_fd, EPOLL_CTL_ADD, r->wake_fd, &ev) < 0) {
    close(r->epoll_fd); close(r->wake_fd); free(r); return 0;
  }
  pthread_mutex_lock(&encore_http_async_mutex);
  r->id = encore_http_async_next++; r->next = encore_http_async_runtimes; encore_http_async_runtimes = r;
  pthread_mutex_unlock(&encore_http_async_mutex);
  return r->id;
}
int32_t encore_http_async_runtime_stopping(size_t id) {
  pthread_mutex_lock(&encore_http_async_mutex);
  encore_http_async_runtime *r = encore_http_async_rt(id); int value = !r || r->stopping;
  pthread_mutex_unlock(&encore_http_async_mutex); return value;
}
void encore_http_async_runtime_stop(size_t id) {
  pthread_mutex_lock(&encore_http_async_mutex);
  encore_http_async_runtime *r = encore_http_async_rt(id);
  if (r) {
    r->stopping = 1;
    for (size_t i = 0; i < ENCORE_HTTP_ASYNC_LIMIT; ++i) if (r->jobs[i]) {
      if (!r->jobs[i]->status) r->jobs[i]->status = 5;
      encore_http_async_wake(r->jobs[i]);
    }
    encore_http_async_signal(r);
  }
  pthread_mutex_unlock(&encore_http_async_mutex);
}
/* Called only after the Encore JoinHandle has been joined. */
void encore_http_async_runtime_destroy(size_t id) {
  pthread_mutex_lock(&encore_http_async_mutex);
  encore_http_async_runtime **link = &encore_http_async_runtimes;
  while (*link && (*link)->id != id) link = &(*link)->next;
  if (*link) {
    encore_http_async_runtime *r = *link; *link = r->next;
    for (size_t i = 0; i < ENCORE_HTTP_ASYNC_LIMIT; ++i) if (r->jobs[i]) encore_http_async_free_job(r->jobs[i]);
    while (r->tokens) { encore_http_async_token *t = r->tokens; r->tokens = t->next; free(t); }
    close(r->wake_fd); close(r->epoll_fd); free(r);
  }
  pthread_mutex_unlock(&encore_http_async_mutex);
}
size_t encore_http_async_submit(size_t runtime, encore_str host, int32_t port, int32_t tls, encore_str ca, encore_str wire,
                 size_t token, size_t body_limit, size_t header_limit, size_t connect_ms, size_t total_ms) {
  if (!encore_http_async_text(host) || !encore_str_size(host) || !encore_http_async_text(ca) || port < 1 || port > 65535) return 0;
  pthread_mutex_lock(&encore_http_async_mutex);
  encore_http_async_runtime *r = encore_http_async_rt(runtime); size_t slot = ENCORE_HTTP_ASYNC_LIMIT;
  if (r && !r->stopping)
    for (size_t i = 0; i < r->capacity; ++i) if (!r->jobs[i]) { slot = i; break; }
  if (slot == ENCORE_HTTP_ASYNC_LIMIT) { pthread_mutex_unlock(&encore_http_async_mutex); return 0; }
  encore_http_async_job *j = calloc(1, sizeof(*j));
  if (!j) { pthread_mutex_unlock(&encore_http_async_mutex); return 0; }
  j->host = encore_http_async_copy(host); j->wire = encore_http_async_copy(wire); j->ca = encore_http_async_copy(ca);
  if (!j->host || !j->wire || !j->ca) {
    free(j->host); free(j->wire); free(j->ca); free(j);
    pthread_mutex_unlock(&encore_http_async_mutex); return 0;
  }
  j->wire_len = encore_str_size(wire); j->runtime = r; j->id = encore_http_async_next++;
  j->fd = -1; j->port = port; j->tls = tls;
  j->token = token; j->body_limit = body_limit; j->header_limit = header_limit;
  j->connect_ms = connect_ms; j->total_ms = total_ms;
  for (size_t i = 0; i < ENCORE_HTTP_ASYNC_DNS_FDS; ++i) j->dns_fds[i].fd = -1;
  r->jobs[slot] = j; encore_http_async_signal(r);
  pthread_mutex_unlock(&encore_http_async_mutex); return j->id;
}
size_t encore_http_async_token_new(size_t runtime) {
  pthread_mutex_lock(&encore_http_async_mutex); encore_http_async_runtime *r = encore_http_async_rt(runtime);
  encore_http_async_token *t = r && !r->stopping ? calloc(1, sizeof(*t)) : NULL;
  size_t id = 0;
  if (t) { id = t->id = encore_http_async_next++; t->next = r->tokens; r->tokens = t; }
  pthread_mutex_unlock(&encore_http_async_mutex); return id;
}
void encore_http_async_token_cancel(size_t runtime, size_t token) {
  pthread_mutex_lock(&encore_http_async_mutex); encore_http_async_runtime *r = encore_http_async_rt(runtime);
  if (r) for (encore_http_async_token *t = r->tokens; t; t = t->next)
    if (t->id == token) { t->cancelled = 1; encore_http_async_signal(r); break; }
  pthread_mutex_unlock(&encore_http_async_mutex);
}
size_t encore_http_async_setting(size_t id, int32_t key) {
  pthread_mutex_lock(&encore_http_async_mutex); encore_http_async_job *j = encore_http_async_find(id); size_t value = 0;
  if (j) switch (key) {
    case 0: value = j->body_limit; break;
    case 1: value = j->header_limit; break;
    case 2: value = j->connect_ms; break;
    case 3: value = j->total_ms; break;
  }
  pthread_mutex_unlock(&encore_http_async_mutex); return value;
}
int32_t encore_http_async_http_status(size_t id) {
  pthread_mutex_lock(&encore_http_async_mutex); encore_http_async_job *j = encore_http_async_find(id); int value = j ? j->http_status : 0;
  pthread_mutex_unlock(&encore_http_async_mutex); return value;
}
encore_str encore_http_async_headers(size_t id) {
  pthread_mutex_lock(&encore_http_async_mutex); encore_http_async_job *j = encore_http_async_find(id);
  encore_str out = encore_str_from_buffer(j && j->headers ? j->headers : "", j && j->headers ? strlen(j->headers) : 0);
  pthread_mutex_unlock(&encore_http_async_mutex); return out;
}
size_t encore_http_async_slot(size_t runtime, size_t slot) {
  pthread_mutex_lock(&encore_http_async_mutex);
  encore_http_async_runtime *r = encore_http_async_rt(runtime);
  size_t id = r && slot < ENCORE_HTTP_ASYNC_LIMIT && r->jobs[slot] && !r->jobs[slot]->status ? r->jobs[slot]->id : 0;
  pthread_mutex_unlock(&encore_http_async_mutex); return id;
}
encore_str encore_http_async_wire(size_t id) {
  pthread_mutex_lock(&encore_http_async_mutex); encore_http_async_job *j = encore_http_async_find(id);
  encore_str out = encore_str_from_buffer(j ? j->wire : "", j ? j->wire_len : 0);
  pthread_mutex_unlock(&encore_http_async_mutex); return out;
}
/* The status check and waker registration are atomic with completion. */
int32_t encore_http_async_status(size_t id, size_t waker) {
  pthread_mutex_lock(&encore_http_async_mutex); encore_http_async_job *j = encore_http_async_find(id);
  int value = j ? j->status : 5;
  if (j && !value) { j->waker = waker; j->owner = waker; }
  pthread_mutex_unlock(&encore_http_async_mutex); return value;
}
encore_str encore_http_async_result(size_t id) {
  pthread_mutex_lock(&encore_http_async_mutex); encore_http_async_job *j = encore_http_async_find(id);
  encore_str out = encore_str_from_buffer(j && j->result ? j->result : "", j ? j->result_len : 0);
  pthread_mutex_unlock(&encore_http_async_mutex); return out;
}
void encore_http_async_release(size_t id) {
  pthread_mutex_lock(&encore_http_async_mutex);
  for (encore_http_async_runtime *r = encore_http_async_runtimes; r; r = r->next)
    for (size_t i = 0; i < ENCORE_HTTP_ASYNC_LIMIT; ++i)
      if (r->jobs[i] && r->jobs[i]->id == id && r->jobs[i]->status && !r->jobs[i]->waker) {
        encore_http_async_free_job(r->jobs[i]); r->jobs[i] = NULL;
        pthread_mutex_unlock(&encore_http_async_mutex); return;
      }
  pthread_mutex_unlock(&encore_http_async_mutex);
}
void encore_http_async_complete(size_t id, int32_t status, int32_t http_status, encore_str headers, encore_str result) {
  pthread_mutex_lock(&encore_http_async_mutex); encore_http_async_job *j = encore_http_async_find(id);
  if (j && !j->status) {
    encore_http_async_cleanup_io(j);
    j->result = encore_http_async_copy(result); j->result_len = j->result ? encore_str_size(result) : 0;
    j->headers = encore_http_async_copy(headers); j->http_status = http_status;
    j->status = j->result ? status : 4; encore_http_async_wake(j);
    if (j->abandoned) {
      for (size_t i = 0; i < ENCORE_HTTP_ASYNC_LIMIT; ++i) if (j->runtime->jobs[i] == j) j->runtime->jobs[i] = NULL;
      encore_http_async_free_job(j);
    }
  }
  pthread_mutex_unlock(&encore_http_async_mutex);
}
void encore_http_async_cancel(size_t id) {
  pthread_mutex_lock(&encore_http_async_mutex); encore_http_async_job *j = encore_http_async_find(id);
  if (j && !j->status) { j->cancelled = 1; encore_http_async_signal(j->runtime); }
  pthread_mutex_unlock(&encore_http_async_mutex);
}
int32_t encore_http_async_cancelled(size_t id) {
  pthread_mutex_lock(&encore_http_async_mutex); encore_http_async_job *j = encore_http_async_find(id);
  int out = !j || j->cancelled;
  if (j && j->token) for (encore_http_async_token *t = j->runtime->tokens; t; t = t->next)
    if (t->id == j->token && t->cancelled) out = 1;
  pthread_mutex_unlock(&encore_http_async_mutex); return out;
}
/* Waker teardown invokes this AFTER its root future returns Ready and BEFORE the executor frees
 * the event token. Abandoned child requests are cancelled, and no stale waker
 * can race the executor's teardown. This does not depend on Future destructors.
 */
void encore_http_async_detach(size_t runtime, size_t waker) {
  (void)runtime;
  pthread_mutex_lock(&encore_http_async_mutex);
  /* A caller can compose clients from different runtimes in one future. The
   * executor event must be detached everywhere before it is freed. */
  for (encore_http_async_runtime *r = encore_http_async_runtimes; r; r = r->next) {
    for (size_t i = 0; i < ENCORE_HTTP_ASYNC_LIMIT; ++i) {
      encore_http_async_job *j = r->jobs[i];
      if (j && j->owner == waker) {
        j->waker = 0; j->owner = 0;
        if (j->status) { encore_http_async_free_job(j); r->jobs[i] = NULL; }
        else { j->cancelled = 1; j->abandoned = 1; encore_http_async_signal(r); }
      }
    }
  }
  pthread_mutex_unlock(&encore_http_async_mutex);
}
int32_t encore_http_async_dns_step(size_t id) {
  pthread_mutex_lock(&encore_http_async_mutex); encore_http_async_job *j = encore_http_async_find(id);
  if (!j || j->status) { pthread_mutex_unlock(&encore_http_async_mutex); return -1; }
  if (!j->dns_started) {
    j->dns_started = 1;
    struct ares_options options = {0};
    options.sock_state_cb = encore_http_async_dns_socket; options.sock_state_cb_data = j;
    if (ares_init_options(&j->dns, &options, ARES_OPT_SOCK_STATE_CB) != ARES_SUCCESS) {
      pthread_mutex_unlock(&encore_http_async_mutex); return -1;
    }
    struct ares_addrinfo_hints hints = {0};
    hints.ai_family = AF_UNSPEC; hints.ai_socktype = SOCK_STREAM;
    ares_getaddrinfo(j->dns, j->host, NULL, &hints, encore_http_async_dns_done, j);
  }
  if (!j->dns_done) {
#if ARES_VERSION >= 0x012200
    ares_fd_events_t events[ENCORE_HTTP_ASYNC_DNS_FDS]; size_t count = 0;
    for (size_t i = 0; i < ENCORE_HTTP_ASYNC_DNS_FDS; ++i) if (j->dns_fds[i].fd >= 0 && j->dns_fds[i].ready) {
      events[count].fd = j->dns_fds[i].fd;
      events[count++].events = ((j->dns_fds[i].ready & 1) ? ARES_FD_EVENT_READ : 0) |
                              ((j->dns_fds[i].ready & 2) ? ARES_FD_EVENT_WRITE : 0);
      j->dns_fds[i].ready = 0;
    }
    ares_process_fds(j->dns, events, count, ARES_PROCESS_FLAG_NONE);
#else
    int processed = 0;
    for (size_t i = 0; i < ENCORE_HTTP_ASYNC_DNS_FDS && !j->dns_done; ++i) {
      if (j->dns_fds[i].fd < 0 || !j->dns_fds[i].ready) continue;
      int fd = j->dns_fds[i].fd, ready = j->dns_fds[i].ready;
      j->dns_fds[i].ready = 0;
      ares_process_fd(j->dns, (ready & 1) ? fd : ARES_SOCKET_BAD,
                     (ready & 2) ? fd : ARES_SOCKET_BAD);
      processed = 1;
    }
    if (!processed && !j->dns_done) ares_process_fd(j->dns, ARES_SOCKET_BAD, ARES_SOCKET_BAD);
#endif
  }
  int out = j->dns_done ? (j->dns_count ? 1 : -1) : 0;
  pthread_mutex_unlock(&encore_http_async_mutex); return out;
}
int32_t encore_http_async_dns_timeout(size_t id) {
  pthread_mutex_lock(&encore_http_async_mutex); encore_http_async_job *j = encore_http_async_find(id);
  struct timeval max = {1, 0}, out;
  struct timeval *v = j && j->dns && !j->dns_done ? ares_timeout(j->dns, &max, &out) : NULL;
  int result = v ? (int)(v->tv_sec * 1000 + (v->tv_usec + 999) / 1000) : 1000;
  pthread_mutex_unlock(&encore_http_async_mutex); return result;
}
int32_t encore_http_async_connect_step(size_t id) {
  pthread_mutex_lock(&encore_http_async_mutex); encore_http_async_job *j = encore_http_async_find(id);
  if (!j || j->status) { pthread_mutex_unlock(&encore_http_async_mutex); return -1; }
  for (;;) {
    if (j->fd >= 0) {
      if (!(j->ready & 2)) { pthread_mutex_unlock(&encore_http_async_mutex); return 0; }
      j->ready = 0;
      int error = 0; socklen_t n = sizeof(error);
      if (getsockopt(j->fd, SOL_SOCKET, SO_ERROR, &error, &n) == 0 && !error) {
        pthread_mutex_unlock(&encore_http_async_mutex); return 1;
      }
      epoll_ctl(j->runtime->epoll_fd, EPOLL_CTL_DEL, j->fd, NULL);
      close(j->fd); j->fd = -1;
    }
    if (j->address_index >= j->dns_count) { pthread_mutex_unlock(&encore_http_async_mutex); return -1; }
    struct sockaddr_storage address = j->addresses[j->address_index];
    socklen_t n = j->address_lengths[j->address_index++];
    if (address.ss_family == AF_INET) ((struct sockaddr_in *)&address)->sin_port = htons((uint16_t)j->port);
    else ((struct sockaddr_in6 *)&address)->sin6_port = htons((uint16_t)j->port);
    j->fd = socket(address.ss_family, SOCK_STREAM | SOCK_NONBLOCK | SOCK_CLOEXEC, 0);
    if (j->fd < 0) continue;
    if (connect(j->fd, (struct sockaddr *)&address, n) == 0) {
      encore_http_async_set_interest(j, 2); pthread_mutex_unlock(&encore_http_async_mutex); return 1;
    }
    if (errno == EINPROGRESS) {
      encore_http_async_set_interest(j, 2); pthread_mutex_unlock(&encore_http_async_mutex); return 0;
    }
    close(j->fd); j->fd = -1;
  }
}
static int encore_http_async_ssl_pending(encore_http_async_job *j, int result) {
  int error = SSL_get_error(j->ssl, result);
  if (error == SSL_ERROR_WANT_READ) { encore_http_async_set_interest(j, 1); return 0; }
  if (error == SSL_ERROR_WANT_WRITE) { encore_http_async_set_interest(j, 2); return 0; }
  return -1;
}
int32_t encore_http_async_tls_step(size_t id) {
  pthread_mutex_lock(&encore_http_async_mutex); encore_http_async_job *j = encore_http_async_find(id);
  if (!j || j->status) { pthread_mutex_unlock(&encore_http_async_mutex); return -1; }
  if (!j->tls) { pthread_mutex_unlock(&encore_http_async_mutex); return 1; }
  if (!j->ssl) {
    j->ctx = SSL_CTX_new(TLS_client_method());
    if (!j->ctx) { pthread_mutex_unlock(&encore_http_async_mutex); return -1; }
    SSL_CTX_set_min_proto_version(j->ctx, TLS1_2_VERSION);
    SSL_CTX_set_verify(j->ctx, SSL_VERIFY_PEER, NULL);
    int ok = *j->ca ? SSL_CTX_load_verify_locations(j->ctx, j->ca, NULL) : SSL_CTX_set_default_verify_paths(j->ctx);
    if (ok != 1) { pthread_mutex_unlock(&encore_http_async_mutex); return -1; }
    j->ssl = SSL_new(j->ctx);
    if (!j->ssl || SSL_set_fd(j->ssl, j->fd) != 1) { pthread_mutex_unlock(&encore_http_async_mutex); return -1; }
    unsigned char ip[16];
    if (inet_pton(AF_INET, j->host, ip) == 1 || inet_pton(AF_INET6, j->host, ip) == 1)
      ok = X509_VERIFY_PARAM_set1_ip_asc(SSL_get0_param(j->ssl), j->host);
    else ok = SSL_set1_host(j->ssl, j->host) && SSL_set_tlsext_host_name(j->ssl, j->host);
    if (!ok) { pthread_mutex_unlock(&encore_http_async_mutex); return -1; }
    SSL_set_mode(j->ssl, SSL_MODE_ENABLE_PARTIAL_WRITE | SSL_MODE_ACCEPT_MOVING_WRITE_BUFFER);
  }
  ERR_clear_error();
  int value = SSL_connect(j->ssl);
  int out = value == 1 ? 1 : encore_http_async_ssl_pending(j, value);
  if (out == 1 && SSL_get_verify_result(j->ssl) != X509_V_OK) out = -1;
  pthread_mutex_unlock(&encore_http_async_mutex); return out;
}
int32_t encore_http_async_write(size_t id, size_t offset) {
  pthread_mutex_lock(&encore_http_async_mutex); encore_http_async_job *j = encore_http_async_find(id);
  if (!j || j->status || offset > j->wire_len) { pthread_mutex_unlock(&encore_http_async_mutex); return -1; }
  size_t length = j->wire_len - offset; if (length > 16384) length = 16384;
  int out;
  if (!length) out = 0;
  else if (j->tls) {
    ERR_clear_error(); out = SSL_write(j->ssl, j->wire + offset, (int)length);
    if (out <= 0) out = encore_http_async_ssl_pending(j, out) == 0 ? -2 : -1;
  } else {
    ssize_t n = send(j->fd, j->wire + offset, length, MSG_NOSIGNAL);
    out = n >= 0 ? (int)n : (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR ? -2 : -1);
    if (out == -2) encore_http_async_set_interest(j, 2);
  }
  pthread_mutex_unlock(&encore_http_async_mutex); return out;
}
void encore_http_async_read_interest(size_t id) {
  pthread_mutex_lock(&encore_http_async_mutex); encore_http_async_job *j = encore_http_async_find(id);
  if (j && !j->status) encore_http_async_set_interest(j, 1);
  pthread_mutex_unlock(&encore_http_async_mutex);
}
encore_str encore_http_async_read(size_t id) {
  char buffer[16384]; int n = -1;
  pthread_mutex_lock(&encore_http_async_mutex); encore_http_async_job *j = encore_http_async_find(id);
  if (j && !j->status) {
    j->read_state = -1;
    if (j->tls) {
      ERR_clear_error(); n = SSL_read(j->ssl, buffer, sizeof(buffer));
      if (n > 0) j->read_state = 1;
      else {
        int error = SSL_get_error(j->ssl, n);
        if (error == SSL_ERROR_ZERO_RETURN) j->read_state = 2;
        else if (error == SSL_ERROR_WANT_READ) { encore_http_async_set_interest(j, 1); j->read_state = 0; }
        else if (error == SSL_ERROR_WANT_WRITE) { encore_http_async_set_interest(j, 2); j->read_state = 0; }
      }
    } else {
      n = (int)recv(j->fd, buffer, sizeof(buffer), 0);
      if (n > 0) j->read_state = 1;
      else if (!n) j->read_state = 2;
      else if (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR) j->read_state = 0;
    }
  }
  encore_str out = encore_str_from_buffer(n > 0 ? buffer : "", n > 0 ? (size_t)n : 0);
  pthread_mutex_unlock(&encore_http_async_mutex); return out;
}
int32_t encore_http_async_read_status(size_t id) {
  pthread_mutex_lock(&encore_http_async_mutex); encore_http_async_job *j = encore_http_async_find(id);
  int out = j ? j->read_state : -1;
  pthread_mutex_unlock(&encore_http_async_mutex); return out;
}
void encore_http_async_wait(size_t runtime, int32_t timeout) {
  struct epoll_event events[64];
  pthread_mutex_lock(&encore_http_async_mutex); encore_http_async_runtime *r = encore_http_async_rt(runtime);
  int ep = r ? r->epoll_fd : -1;
  pthread_mutex_unlock(&encore_http_async_mutex);
  if (ep < 0) return;
  int count = epoll_wait(ep, events, 64, timeout < 0 ? 0 : timeout);
  pthread_mutex_lock(&encore_http_async_mutex); r = encore_http_async_rt(runtime);
  if (r) for (int e = 0; e < count; ++e) {
    int fd = events[e].data.fd;
    if (fd == r->wake_fd) { uint64_t value; while (read(fd, &value, sizeof(value)) > 0) {} continue; }
    int ready = ((events[e].events & (EPOLLIN | EPOLLERR | EPOLLHUP | EPOLLRDHUP)) ? 1 : 0) |
                ((events[e].events & (EPOLLOUT | EPOLLERR | EPOLLHUP)) ? 2 : 0);
    for (size_t i = 0; i < ENCORE_HTTP_ASYNC_LIMIT; ++i) if (r->jobs[i]) {
      encore_http_async_job *j = r->jobs[i];
      if (j->fd == fd) j->ready |= ready;
      for (size_t d = 0; d < ENCORE_HTTP_ASYNC_DNS_FDS; ++d) if (j->dns_fds[d].fd == fd) j->dns_fds[d].ready |= ready;
    }
  }
  pthread_mutex_unlock(&encore_http_async_mutex);
}

int32_t encore_http_async_supported(void) { return 1; }
#else
size_t encore_http_async_runtime_new(size_t capacity) { (void)capacity; return 0; }
void encore_http_async_reactor_enter(void) {  }
int32_t encore_http_async_runtime_stopping(size_t runtime) { (void)runtime; return 0; }
void encore_http_async_runtime_stop(size_t runtime) { (void)runtime; }
void encore_http_async_runtime_destroy(size_t runtime) { (void)runtime; }
size_t encore_http_async_submit(size_t runtime, encore_str host, int32_t port, int32_t tls, encore_str ca, encore_str wire, size_t token, size_t body_limit, size_t header_limit, size_t connect_ms, size_t total_ms) { (void)runtime; (void)host; (void)port; (void)tls; (void)ca; (void)wire; (void)token; (void)body_limit; (void)header_limit; (void)connect_ms; (void)total_ms; return 0; }
size_t encore_http_async_slot(size_t runtime, size_t slot) { (void)runtime; (void)slot; return 0; }
encore_str encore_http_async_wire(size_t request) { (void)request; return encore_empty_str(); }
int32_t encore_http_async_status(size_t request, size_t waker) { (void)request; (void)waker; return 0; }
encore_str encore_http_async_result(size_t request) { (void)request; return encore_empty_str(); }
encore_str encore_http_async_headers(size_t request) { (void)request; return encore_empty_str(); }
int32_t encore_http_async_http_status(size_t request) { (void)request; return 0; }
size_t encore_http_async_setting(size_t request, int32_t key) { (void)request; (void)key; return 0; }
void encore_http_async_release(size_t request) { (void)request; }
void encore_http_async_complete(size_t request, int32_t status, int32_t http_status, encore_str headers, encore_str result) { (void)request; (void)status; (void)http_status; (void)headers; (void)result; }
int32_t encore_http_async_cancelled(size_t request) { (void)request; return 0; }
void encore_http_async_detach(size_t runtime, size_t waker) { (void)runtime; (void)waker; }
size_t encore_http_async_token_new(size_t runtime) { (void)runtime; return 0; }
void encore_http_async_token_cancel(size_t runtime, size_t token) { (void)runtime; (void)token; }
int32_t encore_http_async_dns_step(size_t request) { (void)request; return 0; }
int32_t encore_http_async_dns_timeout(size_t request) { (void)request; return 0; }
int32_t encore_http_async_connect_step(size_t request) { (void)request; return 0; }
int32_t encore_http_async_tls_step(size_t request) { (void)request; return 0; }
int32_t encore_http_async_write(size_t request, size_t offset) { (void)request; (void)offset; return 0; }
void encore_http_async_read_interest(size_t request) { (void)request; }
encore_str encore_http_async_read(size_t request) { (void)request; return encore_empty_str(); }
int32_t encore_http_async_read_status(size_t request) { (void)request; return 0; }
void encore_http_async_wait(size_t runtime, int32_t timeout) { (void)runtime; (void)timeout; }
int32_t encore_http_async_supported(void) { return 0; }
#endif
