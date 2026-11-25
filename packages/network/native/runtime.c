/* MIT. Local extension of Encore std/platform's handle-based TCP/TLS and
 * HTTP reactor patterns. No Encore heap object is retained by a worker. */
#define _POSIX_C_SOURCE 200809L
#ifdef __APPLE__
#define _DARWIN_C_SOURCE
#endif
#include <errno.h>
#include <limits.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#ifdef _WIN32
#include "network_win.h"
typedef int mf_addrlen;
#define mf_dns_error gai_strerrorA
#else
#include <arpa/inet.h>
#include <fcntl.h>
#include <netdb.h>
#include <poll.h>
#include <pthread.h>
#include <signal.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>
typedef socklen_t mf_addrlen;
#define mf_dns_error gai_strerror
static int mf_socket_open(int family, int type, int protocol) { return socket(family,type,protocol); }
static int mf_socket_accept(int fd) { return accept(fd,NULL,NULL); }
static void mf_socket_close(int fd) { if (fd>=0) close(fd); }
static bool mf_retry_io(void) { return errno==EAGAIN || errno==EWOULDBLOCK || errno==EINTR; }
static bool mf_retry_connect(void) { return errno==EINPROGRESS; }
static bool mf_init_network(void) { return true; }
#endif
#include <openssl/ssl.h>
#include <openssl/err.h>
#include <openssl/rand.h>
#ifdef _WIN32
#include "reactor_windows.h"
#else
#include "reactor_posix.h"
#endif

typedef struct { size_t refs, len; char data[]; } mf_str_object;
typedef struct { mf_str_object *object; } mf_str;
extern mf_str encore_from_owned_buffer(char *, size_t);
extern mf_str encore_from_cstr_copy(const char *);
extern void encore_async_waker_wake(size_t);
extern bool encore_async_register_waker_cleanup(void (*)(size_t));
static size_t slen(mf_str s) { return s.object ? s.object->len : 0; }
static const char *sdata(mf_str s) { return s.object ? s.object->data : ""; }
static char *scopy(mf_str s) {
    size_t n=slen(s); if (memchr(sdata(s),0,n)) return NULL;
    char *p=malloc(n+1); if(p) { memcpy(p,sdata(s),n); p[n]=0; } return p;
}
static uint64_t now_ms(void) {
#ifdef _WIN32
    return GetTickCount64();
#else
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC,&t);
    return (uint64_t)t.tv_sec*1000+t.tv_nsec/1000000;
#endif
}
typedef struct message message;
struct message { char *bytes; size_t length; message *next; };
typedef struct endpoint endpoint;
typedef struct operation operation;
struct endpoint {
#ifdef _WIN32
    HANDLE pipe;
    wchar_t pipe_name[ENCORE_PIPE_NAME_CAPACITY];
#endif
 size_t id, refs, group; int fd; bool closed, listener, local; SSL_CTX *ctx; SSL *ssl; char *state[16]; size_t state_length[16], flags[16]; bool mailbox, finished; size_t capacity, queued_count, queued_bytes; message *first, *last; endpoint *next; };
struct operation {
#ifdef _WIN32
    EncorePipeOperation pipe_operation;
    bool pipe_pending, pipe_completed;
    DWORD pipe_error, pipe_size;
    uint64_t retry_at;
#endif

    size_t id, endpoint_id, result_id, waker, owner, group;
    int kind, status, stage, dns; short interest;
    uint64_t deadline; bool released, cancelled;
    char *host, *ca, *cert, *key, *bytes; size_t length, offset;
    unsigned port; bool tls; char error[256];
    struct addrinfo *addresses, *current;
    SSL_CTX *server_ctx;
    endpoint *ep; operation *next;
};
enum { LOCAL_CONNECT = 9, LOCAL_BIND = 10, SHUTDOWN_WRITE = 11 };
static pthread_mutex_t mu=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t dns_cv=PTHREAD_COND_INITIALIZER;
static pthread_once_t once=PTHREAD_ONCE_INIT;
#ifndef _WIN32
static int wake_pipe[2]={-1,-1};
#endif
static int init_error;
static size_t next_id=1, operation_count;
static endpoint *endpoints; static operation *operations;
static bool init_wake_pair(void) {
#ifdef _WIN32
    return true;
#else
    if (pipe(wake_pipe)<0) return false;
    fcntl(wake_pipe[0],F_SETFL,O_NONBLOCK); fcntl(wake_pipe[1],F_SETFL,O_NONBLOCK);
    fcntl(wake_pipe[0],F_SETFD,FD_CLOEXEC); fcntl(wake_pipe[1],F_SETFD,FD_CLOEXEC);
    return true;
#endif
}
static void notify(void) {
#ifdef _WIN32
    reactor_notify();
#else
    char byte = 1;
    if (wake_pipe[1]>=0) {
        ssize_t count=write(wake_pipe[1],&byte,1);
        (void)count;
    }
#endif
}
#ifndef _WIN32
static void drain_wakeup(void) {
    char buffer[128];
    while (read(wake_pipe[0],buffer,sizeof(buffer))>0) {}
}
#endif
static endpoint *find_ep(size_t id) { for(endpoint *e=endpoints;e;e=e->next) if(e->id==id) return e; return NULL; }
static operation *find_op(size_t id) { for(operation *o=operations;o;o=o->next) if(o->id==id && !o->released) return o; return NULL; }
static void close_ep(endpoint *e) { if(!e || e->closed) return; e->closed=true;
#ifdef _WIN32
    if (e->pipe) { CloseHandle(e->pipe); e->pipe = NULL; }
#endif
    if(e->fd>=0) { shutdown(e->fd,SHUT_RDWR); mf_socket_close(e->fd); e->fd=-1; } for(endpoint *child=endpoints;child;child=child->next) if(child->group==e->id) close_ep(child); }
static endpoint *new_ep(int fd, bool listener) {
    endpoint *e=calloc(1,sizeof(*e)); if(!e) { mf_socket_close(fd); return NULL; }
    e->id=next_id++; e->fd=fd; e->listener=listener; e->next=endpoints; endpoints=e; return e;
}
static void done(operation *o, int status, const char *error) {
    o->status=status;
    if(error) snprintf(o->error,sizeof(o->error),"%s",error);
    size_t w=o->waker; o->waker=0;
    if(w) encore_async_waker_wake(w);
}
static void fail(operation *o, int status, const char *error) {
#ifdef _WIN32
    if (o->pipe_pending && o->ep && o->ep->pipe) {
        encore_pipe_cancel(o->ep->pipe, &o->pipe_operation);
        if (o->kind == 4) {
            CloseHandle(o->ep->pipe);
            o->ep->pipe = NULL;
        }
    }
#endif
    if(o->ep && (o->kind==1 || o->kind==LOCAL_CONNECT || (o->kind==4 && o->stage==2) || o->kind==3)) close_ep(o->ep);
    done(o,status,error);
}
static int nonblocking(int fd) {
#ifdef _WIN32
    return mf_nonblocking(fd);
#else
    if(fcntl(fd,F_SETFL,fcntl(fd,F_GETFL,0)|O_NONBLOCK)<0) return -1;
    fcntl(fd,F_SETFD,FD_CLOEXEC);
#ifdef SO_NOSIGPIPE
    int one=1; setsockopt(fd,SOL_SOCKET,SO_NOSIGPIPE,&one,sizeof(one));
#endif
    return 0;
#endif
}
static void ssl_error(operation *o, const char *context) {
    unsigned long code=ERR_get_error(); char text[160]="TLS connection failed";
    if(code) ERR_error_string_n(code,text,sizeof(text));
    char message[256]; snprintf(message,sizeof(message),"%s: %s",context,text); fail(o,7,message);
}
static int mf_default_trust(SSL_CTX *context) {
#ifdef _WIN32
    return SSL_CTX_load_verify_store(context, "org.openssl.winstore:");
#else
    return SSL_CTX_set_default_verify_paths(context);
#endif
}
static bool setup_client_tls(operation *o) {
    endpoint *e=o->ep; e->ctx=SSL_CTX_new(TLS_client_method()); if(!e->ctx) { ssl_error(o,"TLS context"); return false; }
    SSL_CTX_set_min_proto_version(e->ctx,TLS1_2_VERSION); SSL_CTX_set_verify(e->ctx,SSL_VERIFY_PEER,NULL);
    if((o->ca[0] ? SSL_CTX_load_verify_locations(e->ctx,o->ca,NULL) : mf_default_trust(e->ctx))!=1) { ssl_error(o,"CA certificates"); return false; }
    e->ssl=SSL_new(e->ctx); if(!e->ssl) { ssl_error(o,"TLS allocation"); return false; }
    unsigned char ip[16];
    int is_ip=inet_pton(AF_INET,o->host,ip)==1 || inet_pton(AF_INET6,o->host,ip)==1;
    if((is_ip ? X509_VERIFY_PARAM_set1_ip_asc(SSL_get0_param(e->ssl),o->host) : SSL_set1_host(e->ssl,o->host))!=1 || (!is_ip && SSL_set_tlsext_host_name(e->ssl,o->host)!=1) || SSL_set_fd(e->ssl,e->fd)!=1) { ssl_error(o,"TLS hostname"); return false; }
    SSL_set_connect_state(e->ssl); return true;
}
static void start_address(operation *o) {
    while(o->current) {
        struct addrinfo *a=o->current; o->current=a->ai_next;
        int fd=mf_socket_open(a->ai_family,a->ai_socktype,a->ai_protocol); if(fd<0) continue;
        if(nonblocking(fd)<0) { mf_socket_close(fd); continue; }
        int rc=connect(fd,a->ai_addr,a->ai_addrlen);
        if(rc<0 && !mf_retry_connect()) { mf_socket_close(fd); continue; }
        endpoint *e=new_ep(fd,false); if(!e) { fail(o,8,"allocation failed"); return; }
        e->refs++; e->group=o->group; o->ep=e; o->stage=1; o->interest=POLLOUT; return;
    }
    fail(o,6,"TCP connection failed for all addresses");
}
static void start_local(operation *o) {
#ifdef _WIN32
    uint64_t now = now_ms();
    if (o->retry_at > now) return;
    wchar_t name[ENCORE_PIPE_NAME_CAPACITY];
    if (encore_pipe_name(o->host, strlen(o->host), name) != ERROR_SUCCESS) {
        fail(o, 6, "invalid local pipe name");
        return;
    }
    bool listener = o->kind == LOCAL_BIND;
    HANDLE pipe = listener ? encore_pipe_listen(&reactor_iocp, name, true, 0)
                           : encore_pipe_connect(&reactor_iocp, name, 0);
    if (pipe == INVALID_HANDLE_VALUE) {
        if (!listener && GetLastError() == ERROR_PIPE_BUSY) {
            o->retry_at = now + 5;
            return;
        }
        fail(o, 6, listener ? "cannot bind local pipe" : "cannot connect to local pipe");
        return;
    }
    endpoint *e = new_ep(-1, listener);
    if (!e) {
        CloseHandle(pipe);
        fail(o, 8, "allocation failed");
        return;
    }
    e->pipe = pipe;
    e->local = true;
    if (listener) memcpy(e->pipe_name, name, (wcslen(name) + 1) * sizeof(*name));
    o->result_id = e->id;
    done(o, 1, NULL);
#else
    struct sockaddr_un address = {.sun_family = AF_UNIX};
    size_t length = strlen(o->host);
    if (!length || length >= sizeof(address.sun_path)) {
        fail(o, 6, "invalid Unix socket path");
        return;
    }
    memcpy(address.sun_path, o->host, length + 1);
    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0 || nonblocking(fd) < 0) {
        if (fd >= 0) mf_socket_close(fd);
        fail(o, 6, "cannot open Unix socket");
        return;
    }
    bool listener = o->kind == LOCAL_BIND;
    endpoint *e = new_ep(fd, listener);
    if (!e) {
        fail(o, 8, "allocation failed");
        return;
    }
    o->ep = e;
    e->refs++;
    e->local = true;
    if (listener) {
        if (bind(fd, (struct sockaddr *)&address, sizeof(address)) < 0) {
            close_ep(e);
            fail(o, 6, "cannot bind Unix socket");
            return;
        }
        if (listen(fd, 128) < 0) {
            close_ep(e);
            fail(o, 6, "cannot listen on Unix socket");
            return;
        }
    } else if (connect(fd, (struct sockaddr *)&address, sizeof(address)) < 0) {
        if (mf_retry_connect()) {
            o->stage = 1;
            o->interest = POLLOUT;
            return;
        }
        close_ep(e);
        fail(o, 6, "cannot connect to Unix socket");
        return;
    }
    o->result_id = e->id;
    done(o, 1, NULL);
#endif
}

#ifdef _WIN32
static void win_operation_complete(EncoreIocpEvent event) {
    operation *o = CONTAINING_RECORD(event.operation, operation, pipe_operation);
    pthread_mutex_lock(&mu);
    o->pipe_pending = false;
    o->pipe_completed = true;
    o->pipe_error = event.error;
    o->pipe_size = event.size;
    pthread_mutex_unlock(&mu);
}

static void step_pipe(operation *o, endpoint *e) {
    if (o->pipe_pending) return;
    if (o->pipe_completed) {
        o->pipe_completed = false;
        if (o->pipe_error != ERROR_SUCCESS && !(o->kind == 2 &&
            (o->pipe_error == ERROR_BROKEN_PIPE || o->pipe_error == ERROR_PIPE_NOT_CONNECTED))) {
            fail(o, 6, "local pipe operation failed");
            return;
        }
        if (o->kind == 4) {
            endpoint *child = new_ep(-1, false);
            if (!child) {
                CloseHandle(e->pipe);
                e->pipe = NULL;
                fail(o, 8, "allocation failed");
                return;
            }
            child->local = true;
            child->pipe = e->pipe;
            e->pipe = NULL;
            o->result_id = child->id;
            done(o, 1, NULL);
            return;
        }
        if (o->kind == 2) {
            o->offset = o->pipe_size;
            done(o, 1, NULL);
            return;
        }
        o->offset += o->pipe_size;
        if (o->offset == o->length) {
            done(o, 1, NULL);
            return;
        }
        if (o->pipe_size == 0) {
            fail(o, 2, "local pipe write made no progress");
            return;
        }
    }
    DWORD status;
    if (o->kind == 4) {
        if (!e->pipe) {
            HANDLE pipe = encore_pipe_listen(&reactor_iocp, e->pipe_name, false, 0);
            if (pipe == INVALID_HANDLE_VALUE) {
                fail(o, 6, "cannot create local pipe instance");
                return;
            }
            e->pipe = pipe;
        }
        status = encore_pipe_accept(&reactor_iocp, e->pipe, 0, &o->pipe_operation);
    } else if (o->kind == 2) {
        status = encore_pipe_read(&reactor_iocp, e->pipe, 0, o->bytes, (DWORD)o->length, &o->pipe_operation);
    } else if (o->kind == 3) {
        status = encore_pipe_write(e->pipe, o->bytes + o->offset, (DWORD)(o->length - o->offset), &o->pipe_operation);
    } else {
        fail(o, 6, "operation is not supported on Windows named pipes");
        return;
    }
    if (status == ERROR_SUCCESS) o->pipe_pending = true;
    else fail(o, 6, "cannot submit local pipe operation");
}
#endif

static void step(operation *o, short events) {
    if(o->status || o->released) return;
    if(o->group) { endpoint *g=find_ep(o->group); if(!g || g->closed) { close_ep(o->ep); fail(o,3,"operation group is closed"); return; } }
    if(o->kind==3) { for(operation *p=operations;p;p=p->next) if(p->kind==3 && p->ep==o->ep && p->id<o->id && !p->status && !p->released) return; }
    if(o->cancelled) { fail(o,3,"operation cancelled"); return; }
    if(now_ms()>=o->deadline) { if(o->kind==5) done(o,1,NULL); else fail(o,4,"operation timed out"); return; }
    if(o->kind==5) return;
    if (o->kind == LOCAL_CONNECT || o->kind == LOCAL_BIND) {
        if (o->stage == 0) {
            start_local(o);
        } else if (events & (POLLOUT | POLLERR | POLLHUP)) {
            int error = 0;
            mf_addrlen length = sizeof(error);
            if (getsockopt(o->ep->fd, SOL_SOCKET, SO_ERROR, (char *)&error, &length) < 0 || error) {
                close_ep(o->ep);
                fail(o, 6, "cannot connect to Unix socket");
            } else {
                o->result_id = o->ep->id;
                done(o, 1, NULL);
            }
        }
        return;
    }
    if(o->kind==1 || o->kind==7) {
        if(o->dns!=3) return;
        if(o->stage==0) {
            if(!o->addresses) { fail(o,(o->kind==7 && o->tls && o->error[0] && strncmp(o->error,"cannot load",11)==0)?7:5,o->error[0]?o->error:"DNS resolution failed"); return; }
            if(o->kind==7) {
                for(struct addrinfo *a=o->addresses;a;a=a->ai_next) {
                    int fd=mf_socket_open(a->ai_family,a->ai_socktype,a->ai_protocol); if(fd<0) continue;
                    int one=1; setsockopt(fd,SOL_SOCKET,SO_REUSEADDR,(const char *)&one,sizeof(one));
                    if(nonblocking(fd)<0 || bind(fd,a->ai_addr,a->ai_addrlen)<0 || listen(fd,128)<0) { mf_socket_close(fd); continue; }
                    endpoint *e=new_ep(fd,true); if(!e) { fail(o,8,"allocation failed"); return; }
                    e->ctx=o->server_ctx; o->server_ctx=NULL; o->result_id=e->id; done(o,1,NULL); return;
                }
                fail(o,6,"cannot bind listener"); return;
            }
            o->current=o->addresses; start_address(o); return;
        }
        if(o->stage==1) {
            if(!(events&(POLLOUT|POLLERR|POLLHUP))) return;
            int error=0; mf_addrlen n=sizeof(error);
            if(getsockopt(o->ep->fd,SOL_SOCKET,SO_ERROR,(char *)&error,&n)<0 || error) {
                close_ep(o->ep); o->ep->refs--; o->ep=NULL; start_address(o); return;
            }
            if(!o->tls) { o->result_id=o->ep->id; done(o,1,NULL); return; }
            if(!setup_client_tls(o)) return;
            o->stage=2;
        }
    }
    endpoint *e=o->ep;
    if(!e || e->closed) { fail(o,2,"connection is closed"); return; }
#ifdef _WIN32
    if (e->local) {
        step_pipe(o, e);
        return;
    }
#endif
    if (o->kind == SHUTDOWN_WRITE) {
        if (e->local && shutdown(e->fd, SHUT_WR) == 0) done(o, 1, NULL);
        else fail(o, 6, "cannot close socket write side");
        return;
    }
    if(o->kind==8) {
        if(!e->mailbox) { fail(o,2,"not a mailbox"); return; }
        if(e->first) {
            message *m=e->first; e->first=m->next; if(!e->first) e->last=NULL;
            e->queued_count--; e->queued_bytes-=m->length; free(o->bytes); o->bytes=m->bytes; o->offset=m->length; free(m); done(o,1,NULL);
        } else if(e->finished) done(o,2,e->flags[15]?"mailbox capacity exceeded":"mailbox is finished");
        o->interest=0; return;
    }
    if(o->stage==2) {
        int rc=SSL_do_handshake(e->ssl);
        if(rc==1) { o->result_id=e->id; done(o,1,NULL); return; }
        int error=SSL_get_error(e->ssl,rc);
        if(error==SSL_ERROR_WANT_READ || error==SSL_ERROR_WANT_WRITE) { o->interest=error==SSL_ERROR_WANT_READ?POLLIN:POLLOUT; return; }
        ssl_error(o,"TLS handshake"); return;
    }
    if(o->kind==4) {
        int fd=mf_socket_accept(e->fd);
        if(fd<0) { if(mf_retry_io()) { o->interest=POLLIN; return; } fail(o,6,"accept failed"); return; }
        if(nonblocking(fd)<0) { mf_socket_close(fd); fail(o,6,"cannot configure accepted socket"); return; }
        endpoint *child=new_ep(fd,false); if(!child) { fail(o,8,"allocation failed"); return; }
        if(!e->ctx) { child->local=e->local; o->result_id=child->id; done(o,1,NULL); return; }
        SSL_CTX_up_ref(e->ctx); child->ctx=e->ctx; child->ssl=SSL_new(child->ctx);
        if(!child->ssl || SSL_set_fd(child->ssl,fd)!=1) { close_ep(child); ssl_error(o,"TLS accept"); return; }
        SSL_set_accept_state(child->ssl); e->refs--; o->ep=child; child->refs++; o->stage=2; o->interest=POLLIN; return;
    }
    if(o->kind!=2 && o->kind!=3) return;
    int rc;
    if(e->ssl) {
        rc=o->kind==2 ? SSL_read(e->ssl,o->bytes,(int)o->length) : SSL_write(e->ssl,o->bytes+o->offset,(int)(o->length-o->offset));
        if(rc<=0) {
            int error=SSL_get_error(e->ssl,rc);
            if(error==SSL_ERROR_WANT_READ || error==SSL_ERROR_WANT_WRITE) { o->interest=error==SSL_ERROR_WANT_READ?POLLIN:POLLOUT; return; }
            if(error==SSL_ERROR_ZERO_RETURN && o->kind==2) { o->offset=0; done(o,1,NULL); return; }
            ssl_error(o,"TLS I/O"); return;
        }
    } else {
#ifdef MSG_NOSIGNAL
        int flags=MSG_NOSIGNAL;
#else
        int flags=0;
#endif
        rc=o->kind==2 ? (int)recv(e->fd,o->bytes,o->length,0) : (int)send(e->fd,o->bytes+o->offset,o->length-o->offset,flags);
        if(rc<0) { if(mf_retry_io()) { o->interest=o->kind==2?POLLIN:POLLOUT; return; } fail(o,6,"socket I/O failed"); return; }
    }
    if(o->kind==2) { o->offset=(size_t)rc; done(o,1,NULL); }
    else { o->offset+=(size_t)rc; if(o->offset==o->length) done(o,1,NULL); else o->interest=POLLOUT; }
}
static void destroy_op(operation *o) {
    if(o->result_id && o->released) close_ep(find_ep(o->result_id));
    if (o->kind == LOCAL_CONNECT && !o->status) close_ep(o->ep);
    if(o->ep) o->ep->refs--;
    if(o->addresses) freeaddrinfo(o->addresses);
    if(o->server_ctx) SSL_CTX_free(o->server_ctx);
    free(o->host); free(o->ca); free(o->cert); free(o->key); free(o->bytes); free(o); operation_count--;
}
static void *reactor(void *unused) {
    (void)unused;
#ifndef _WIN32
    sigset_t blocked; sigemptyset(&blocked); sigaddset(&blocked,SIGPIPE); pthread_sigmask(SIG_BLOCK,&blocked,NULL);
#endif
    for(;;) {
        struct pollfd fds[1025]; size_t ids[1025], generations[1025], count=1; int wait=1000;
        pthread_mutex_lock(&mu);
        operation **at=&operations;
        while(*at) {
            operation *o=*at;
#ifdef _WIN32
            if (o->released && o->pipe_pending) {
                if (!o->status) fail(o, 3, "operation released");
                at = &o->next;
                continue;
            }
#endif
            if(o->released && o->dns!=2) { *at=o->next; destroy_op(o); continue; }
            step(o,0);
            if(!o->status && !o->released) {
                uint64_t now=now_ms(); uint64_t left=o->deadline>now?o->deadline-now:0;
                if(left<(uint64_t)wait) wait=(int)left;
#ifdef _WIN32
                if (o->retry_at > now && o->retry_at - now < (uint64_t)wait) wait=(int)(o->retry_at-now);
#endif
                bool queued=false; if(o->kind==3) { for(operation *p=operations;p;p=p->next) if(p->kind==3 && p->ep==o->ep && p->id<o->id && !p->status && !p->released) queued=true; }
                if(!queued && o->ep && !o->ep->closed && o->ep->fd>=0 && o->interest && count<1025) { fds[count]=(struct pollfd){o->ep->fd,o->interest,0}; generations[count]=o->ep->id; ids[count++]=o->id; }
            }
            at=&o->next;
        }
        endpoint **ep=&endpoints;
        while(*ep) { endpoint *e=*ep; if(e->closed && !e->refs) { *ep=e->next; if(e->ssl) SSL_free(e->ssl); if(e->ctx) SSL_CTX_free(e->ctx); for(size_t i=0;i<16;i++) free(e->state[i]); while(e->first) { message *m=e->first; e->first=m->next; free(m->bytes); free(m); } free(e); } else ep=&e->next; }
        pthread_mutex_unlock(&mu);
#ifdef _WIN32
        fds[0]=(struct pollfd){0,0,0};
#else
        fds[0]=(struct pollfd){wake_pipe[0],POLLIN,0};
#endif
        generations[0] = 0;
        int rc=reactor_wait(fds,generations,count,wait);
        if(rc>0) {
#ifndef _WIN32
            if(fds[0].revents) drain_wakeup();
#endif
            pthread_mutex_lock(&mu);
            for(size_t i=1;i<count;i++) if(fds[i].revents) { operation *o=find_op(ids[i]); if(o) step(o,fds[i].revents); }
            pthread_mutex_unlock(&mu);
        }
    }
    return NULL;
}
static void *dns_worker(void *unused) {
    (void)unused;
    for(;;) {
        pthread_mutex_lock(&mu); operation *o=NULL;
        while(!o) { for(operation *p=operations;p;p=p->next) if(p->dns==1 && !p->released) { o=p; o->dns=2; break; } if(!o) pthread_cond_wait(&dns_cv,&mu); }
        pthread_mutex_unlock(&mu);
        struct addrinfo hints={0}, *addresses=NULL; hints.ai_family=AF_UNSPEC; hints.ai_socktype=SOCK_STREAM; if(o->kind==7) hints.ai_flags=AI_PASSIVE;
        char service[16]; snprintf(service,sizeof(service),"%u",o->port);
        int rc=getaddrinfo(o->host[0]?o->host:NULL,service,&hints,&addresses);
        SSL_CTX *ctx=NULL; char error[256]="";
        if(rc) snprintf(error,sizeof(error),"DNS: %s",mf_dns_error(rc));
        if(!rc && o->kind==7 && o->tls) {
            ctx=SSL_CTX_new(TLS_server_method());
            if(!ctx || SSL_CTX_set_min_proto_version(ctx,TLS1_2_VERSION)!=1 || SSL_CTX_use_certificate_chain_file(ctx,o->cert)!=1 || SSL_CTX_use_PrivateKey_file(ctx,o->key,SSL_FILETYPE_PEM)!=1 || SSL_CTX_check_private_key(ctx)!=1) {
                snprintf(error,sizeof(error),"cannot load server TLS certificate/key"); if(ctx) SSL_CTX_free(ctx); ctx=NULL; freeaddrinfo(addresses); addresses=NULL;
            }
        }
        pthread_mutex_lock(&mu); o->addresses=addresses; o->server_ctx=ctx; snprintf(o->error,sizeof(o->error),"%s",error); o->dns=3; pthread_mutex_unlock(&mu); notify();
    }
    return NULL;
}
static void cleanup_waker(size_t w) {
    pthread_mutex_lock(&mu);
    for(operation *o=operations;o;o=o->next) if(o->owner==w) { o->waker=0; o->owner=0; o->cancelled=true; o->released=true; if(o->group) close_ep(o->ep); }
    pthread_mutex_unlock(&mu); notify();
}
static void initialize(void) {
    if(!mf_init_network() || !encore_async_register_waker_cleanup(cleanup_waker) || !reactor_init() || !init_wake_pair()) { init_error=1; return; }
    pthread_t thread;
    if(pthread_create(&thread,NULL,reactor,NULL)) { init_error=1; return; } pthread_detach(thread);
    for(int i=0;i<4;i++) { if(pthread_create(&thread,NULL,dns_worker,NULL)) { init_error=1; return; } pthread_detach(thread); }
}
static operation *allocate_op(int kind, size_t timeout) {
    if(init_error || !timeout || timeout>86400000 || operation_count>=1024) return NULL;
    operation *o=calloc(1,sizeof(*o)); if(!o) return NULL;
    o->id=next_id++; o->kind=kind; o->deadline=now_ms()+timeout; o->next=operations; operations=o; operation_count++; return o;
}
size_t mfnet_endpoint_operation(int kind, mf_str host, size_t port, bool tls, mf_str ca, mf_str cert, mf_str key, size_t timeout) {
    pthread_once(&once,initialize); if(port>65535 || (kind!=1 && kind!=7)) return 0;
    char *h=scopy(host),*c=scopy(ca),*crt=scopy(cert),*k=scopy(key);
    if(!h||!c||!crt||!k) { free(h); free(c); free(crt); free(k); return 0; }
    pthread_mutex_lock(&mu); operation *o=allocate_op(kind,timeout);
    if(o) { o->host=h; o->ca=c; o->cert=crt; o->key=k; o->port=(unsigned)port; o->tls=tls; o->dns=1; }
    size_t id=o?o->id:0; pthread_cond_signal(&dns_cv); pthread_mutex_unlock(&mu);
    if(!o) { free(h); free(c); free(crt); free(k); } notify(); return id;
}
size_t mfnet_local_operation(int kind, mf_str path, size_t timeout) {
    if (kind != LOCAL_CONNECT && kind != LOCAL_BIND) return 0;
    pthread_once(&once, initialize);
    char *address = scopy(path);
    if (!address) return 0;
    pthread_mutex_lock(&mu);
    operation *o = allocate_op(kind, timeout);
    size_t id = 0;
    if (o) {
        o->host = address;
        id = o->id;
    } else {
        free(address);
    }
    pthread_mutex_unlock(&mu);
    notify();
    return id;
}
size_t mfnet_io_operation(int kind, size_t handle, mf_str bytes, size_t max, size_t timeout) {
    pthread_once(&once,initialize); pthread_mutex_lock(&mu);
    endpoint *e=find_ep(handle); operation *o=NULL;
    if(kind==5 || (e && !e->closed && ((kind==4)==e->listener) && (e->mailbox?(kind==8):(kind!=8)))) {
        bool busy=false; size_t queued=0; for(operation *p=operations;p;p=p->next) if(!p->status && !p->released && p->ep==e && p->kind==kind && kind!=5) { queued++; if(kind!=3) busy=true; } if(queued>=64) busy=true;
        size_t length=kind==3?slen(bytes):max;
        if(!busy && length<=67174414) {
            o=allocate_op(kind,timeout);
            if(o) { o->ep=e; if(e) { e->refs++; o->group=e->group; } o->length=length; o->bytes=malloc(length?length:1); o->interest=kind==3?POLLOUT:POLLIN;
                if(!o->bytes) done(o,8,"allocation failed"); else if(kind==3 && length) memcpy(o->bytes,sdata(bytes),length);
                if(!length && (kind==2 || kind==3)) done(o,1,NULL);
            }
        }
    }
    size_t id=o?o->id:0; pthread_mutex_unlock(&mu); notify(); return id;
}
int32_t mfnet_status(size_t id,size_t waker) { pthread_mutex_lock(&mu); operation *o=find_op(id); int rc=o?o->status:2; if(o && !rc) { o->waker=waker; o->owner=waker; } pthread_mutex_unlock(&mu); return rc; }
mf_str mfnet_data(size_t id) { pthread_mutex_lock(&mu); operation *o=find_op(id); size_t n=o&&o->status==1?o->offset:0; char *data=malloc(n+1); if(data) { if(n) memcpy(data,o->bytes,n); data[n]=0; } pthread_mutex_unlock(&mu); return data?encore_from_owned_buffer(data,n):encore_from_cstr_copy(""); }
mf_str mfnet_error(size_t id) { pthread_mutex_lock(&mu); operation *o=find_op(id); mf_str s=encore_from_cstr_copy(o?o->error:"invalid or closed operation"); pthread_mutex_unlock(&mu); return s; }
size_t mfnet_result_handle(size_t id) { pthread_mutex_lock(&mu); operation *o=find_op(id); size_t result=o&&o->status==1?o->result_id:0; if(o) o->result_id=0; pthread_mutex_unlock(&mu); return result; }
void mfnet_release(size_t id) { pthread_mutex_lock(&mu); operation *o=find_op(id); if(o) { o->waker=0; o->owner=0; o->released=true; } pthread_mutex_unlock(&mu); notify(); }
void mfnet_cancel(size_t id) { pthread_mutex_lock(&mu); operation *o=find_op(id); if(o) o->cancelled=true; pthread_mutex_unlock(&mu); notify(); }
void mfnet_close(size_t id) { pthread_mutex_lock(&mu); close_ep(find_ep(id)); pthread_mutex_unlock(&mu); notify(); }
size_t mfnet_port(size_t id) { pthread_mutex_lock(&mu); endpoint *e=find_ep(id); struct sockaddr_storage a; mf_addrlen n=sizeof(a); size_t p=0; if(e&&!e->closed && e->fd>=0 && getsockname(e->fd,(struct sockaddr*)&a,&n)==0) { if (a.ss_family==AF_INET) p=ntohs(((struct sockaddr_in*)&a)->sin_port); else if (a.ss_family==AF_INET6) p=ntohs(((struct sockaddr_in6*)&a)->sin6_port); } pthread_mutex_unlock(&mu); return p; }
mf_str mfnet_random(size_t n) { if(n>16777216) return encore_from_cstr_copy(""); char *data=malloc(n+1); if(!data) return encore_from_cstr_copy(""); if(n && RAND_bytes((unsigned char*)data,(int)n)!=1) { free(data); return encore_from_cstr_copy(""); } data[n]=0; return encore_from_owned_buffer(data,n); }
mf_str mfnet_byte(uint8_t value) { char *data=malloc(2); if(!data) return encore_from_cstr_copy(""); data[0]=(char)value; data[1]=0; return encore_from_owned_buffer(data,1); }
mf_str mfnet_xor(mf_str bytes,mf_str key) { size_t n=slen(bytes),k=slen(key); if(!k) return encore_from_cstr_copy(""); char *data=malloc(n+1); if(!data) return encore_from_cstr_copy(""); for(size_t i=0;i<n;i++) data[i]=sdata(bytes)[i]^sdata(key)[i%k]; data[n]=0; return encore_from_owned_buffer(data,n); }

/* Resource-scoped byte cells let Encore futures keep durable parser state without
 * retaining pointers into caller stack frames. Copies cross the ABI by value. */
mf_str mfnet_state_get(size_t id,size_t slot) {
 pthread_mutex_lock(&mu); endpoint *e=find_ep(id); size_t n=e&&slot<16?e->state_length[slot]:0;
 char *p=malloc(n+1); if(p) { if(n) memcpy(p,e->state[slot],n); p[n]=0; } pthread_mutex_unlock(&mu);
 return p?encore_from_owned_buffer(p,n):encore_from_cstr_copy("");
}
bool mfnet_state_set(size_t id,size_t slot,mf_str value) {
 if(slot>=16 || slen(value)>67174414) return false;
 char *p=malloc(slen(value)+1); if(!p) return false; memcpy(p,sdata(value),slen(value)); p[slen(value)]=0;
 pthread_mutex_lock(&mu); endpoint *e=find_ep(id); bool ok=e&&!e->closed;
 if(ok) { free(e->state[slot]); e->state[slot]=p; e->state_length[slot]=slen(value); } else free(p);
 pthread_mutex_unlock(&mu); return ok;
}
size_t mfnet_flag_get(size_t id,size_t slot) { pthread_mutex_lock(&mu); endpoint *e=find_ep(id); size_t n=e&&!e->closed&&slot<16?e->flags[slot]:SIZE_MAX; pthread_mutex_unlock(&mu); return n; }
void mfnet_flag_set(size_t id,size_t slot,size_t value) { pthread_mutex_lock(&mu); endpoint *e=find_ep(id); if(e&&!e->closed&&slot<16) e->flags[slot]=value; pthread_mutex_unlock(&mu); }

size_t mfnet_mailbox_new(size_t capacity) {
 pthread_once(&once,initialize); if(init_error || !capacity || capacity>65536) return 0;
 pthread_mutex_lock(&mu); endpoint *e=new_ep(-1,false); if(e) { e->mailbox=true; e->capacity=capacity; } size_t id=e?e->id:0; pthread_mutex_unlock(&mu); return id;
}
bool mfnet_mailbox_push(size_t id,mf_str value) {
 size_t length=slen(value); if(length>16777216) return false;
 message *m=calloc(1,sizeof(*m)); if(!m) return false; m->bytes=malloc(length+1); if(!m->bytes) { free(m); return false; }
 memcpy(m->bytes,sdata(value),length); m->bytes[length]=0; m->length=length;
 pthread_mutex_lock(&mu); endpoint *e=find_ep(id); bool okay=e&&!e->closed&&e->mailbox&&!e->finished&&e->queued_count<e->capacity&&e->queued_bytes<=16777216-length;
 if(okay) { if(e->last) e->last->next=m; else e->first=m; e->last=m; e->queued_count++; e->queued_bytes+=length; }
 else { if(e&&!e->closed) { e->flags[15]=1; e->finished=true; } free(m->bytes); free(m); }
 pthread_mutex_unlock(&mu); notify(); return okay;
}
void mfnet_mailbox_finish(size_t id) { pthread_mutex_lock(&mu); endpoint *e=find_ep(id); if(e) e->finished=true; pthread_mutex_unlock(&mu); notify(); }
size_t mfnet_flag_increment(size_t id,size_t slot) { pthread_mutex_lock(&mu); endpoint *e=find_ep(id); size_t value=0; if(e&&!e->closed&&slot<16) value=++e->flags[slot]; pthread_mutex_unlock(&mu); return value; }
bool mfnet_state_cas(size_t id,size_t slot,mf_str expected,mf_str next) {
 if(slot>=16 || slen(next)>67174414) return false;
 char *copy=malloc(slen(next)+1); if(!copy) return false; memcpy(copy,sdata(next),slen(next)); copy[slen(next)]=0;
 pthread_mutex_lock(&mu); endpoint *e=find_ep(id); bool okay=e&&!e->closed&&e->state_length[slot]==slen(expected)&&(!slen(expected)||memcmp(e->state[slot],sdata(expected),slen(expected))==0);
 if(okay) { free(e->state[slot]); e->state[slot]=copy; e->state_length[slot]=slen(next); } else free(copy);
 pthread_mutex_unlock(&mu); return okay;
}

/* Groups use a mailbox as an ownership scope. Closing it cancels outstanding
 * connects and closes every connected child, including suspended HTTP reads. */
void mfnet_operation_group(size_t id,size_t group) {
 pthread_mutex_lock(&mu); operation *o=find_op(id); endpoint *g=find_ep(group);
 if(o) {
   o->group=group; if(o->ep) o->ep->group=group;
   endpoint *result=find_ep(o->result_id); if(result) result->group=group;
   if(!g || g->closed || !g->mailbox) { close_ep(o->ep); close_ep(result); done(o,3,"operation group is closed"); }
 }
 pthread_mutex_unlock(&mu); notify();
}
