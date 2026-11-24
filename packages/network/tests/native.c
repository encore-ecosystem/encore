/* Native ABI, lifetime and real TCP/TLS integration tests. */
#include "../native/runtime.c"
#include <assert.h>
static void (*cleanup_hook)(size_t);
static size_t wake_count;
bool encore_async_register_waker_cleanup(void (*hook)(size_t)) { cleanup_hook=hook; return true; }
void encore_async_waker_wake(size_t token) { assert(token==42); wake_count++; }
mf_str encore_from_owned_buffer(char *bytes,size_t length) {
    mf_str_object *object=malloc(sizeof(*object)+length+1); assert(object);
    object->refs=1; object->len=length; memcpy(object->data,bytes,length); object->data[length]=0; free(bytes); return (mf_str){object};
}
mf_str encore_from_cstr_copy(const char *text) { size_t n=strlen(text); char *p=malloc(n+1); memcpy(p,text,n+1); return encore_from_owned_buffer(p,n); }
static mf_str text(const char *s) { return encore_from_cstr_copy(s); }
static void drop(mf_str s) { free(s.object); }
static void pause_ms(unsigned ms) {
#ifdef _WIN32
    Sleep(ms);
#else
    struct timespec delay={ms/1000,(long)(ms%1000)*1000000};
    nanosleep(&delay,NULL);
#endif
}
static int wait_for(size_t op) {
    assert(op); uint64_t limit=now_ms()+6000;
    for(;;) { int status=mfnet_status(op,0); if(status) return status; assert(now_ms()<limit); pause_ms(1); }
}
static size_t endpoint_op(int kind,const char *host,size_t port,bool tls,const char *ca,const char *cert,const char *key) {
    mf_str h=text(host),c=text(ca),crt=text(cert),k=text(key);
    size_t op=mfnet_endpoint_operation(kind,h,port,tls,c,crt,k,2000);
    drop(h);drop(c);drop(crt);drop(k);return op;
}
static size_t io(int kind,size_t handle,const char *data,size_t max,size_t timeout) {
    mf_str s=text(data); size_t op=mfnet_io_operation(kind,handle,s,max,timeout);drop(s);return op;
}
static size_t completed_handle(size_t op) {
    int status=wait_for(op);
    if(status!=1) { mf_str s=mfnet_error(op); fprintf(stderr,"status=%d: %s\n",status,sdata(s));drop(s); }
    assert(status==1); size_t handle=mfnet_result_handle(op);assert(handle);mfnet_release(op);return handle;
}
static size_t listener(bool tls,const char *cert,const char *key) { return completed_handle(endpoint_op(7,"127.0.0.1",0,tls,"",cert,key)); }
static void roundtrip(bool tls,const char *cert,const char *key) {
    size_t server=listener(tls,cert,key),port=mfnet_port(server);assert(port);
    size_t accept=io(4,server,"",0,2000);
    size_t client=completed_handle(endpoint_op(1,tls?"localhost":"127.0.0.1",port,tls,cert,"",""));
    size_t peer=completed_handle(accept);
    size_t first=io(3,client,"first",0,2000),second=io(3,client,"second",0,2000);
    assert(wait_for(first)==1 && wait_for(second)==1);mfnet_release(first);mfnet_release(second);
    char got[12]="";size_t length=0;
    while(length<11) { size_t op=io(2,peer,"",11-length,2000);assert(wait_for(op)==1);mf_str s=mfnet_data(op);assert(slen(s));memcpy(got+length,sdata(s),slen(s));length+=slen(s);drop(s);mfnet_release(op); }
    assert(strcmp(got,"firstsecond")==0);
    size_t timed=io(2,peer,"",1,20);assert(wait_for(timed)==4);mfnet_release(timed);
    size_t cancelled=io(2,peer,"",1,2000);mfnet_cancel(cancelled);assert(wait_for(cancelled)==3);mfnet_release(cancelled);
    size_t closed=io(2,peer,"",1,2000);mfnet_close(peer);assert(wait_for(closed)==2);mfnet_release(closed);
    mfnet_close(client);mfnet_close(server);mfnet_close(peer);
}
static void test_listener_survives_timeout(void) {
    size_t server=listener(false,"","");size_t op=io(4,server,"",0,20);assert(wait_for(op)==4);mfnet_release(op);assert(mfnet_port(server));mfnet_close(server);
}
static void test_mailbox(void) {
    size_t box=mfnet_mailbox_new(1);assert(box);mf_str hello=text("hello");assert(mfnet_mailbox_push(box,hello));assert(!mfnet_mailbox_push(box,hello));drop(hello);
    size_t op=io(8,box,"",0,1000);assert(wait_for(op)==1);mf_str data=mfnet_data(op);assert(slen(data)==5);drop(data);mfnet_release(op);
    op=io(8,box,"",0,1000);assert(wait_for(op)==2);mfnet_release(op);mfnet_close(box);
    box=mfnet_mailbox_new(1);op=io(8,box,"",0,2000);assert(mfnet_status(op,42)==0);cleanup_hook(42);pause_ms(30);assert(wake_count==0);mfnet_close(box);
}
static void test_groups(void) {
    size_t server=listener(false,"",""),group=mfnet_mailbox_new(1);
    size_t accept=io(4,server,"",0,2000);
    size_t connect=endpoint_op(1,"127.0.0.1",mfnet_port(server),false,"","","");mfnet_operation_group(connect,group);
    size_t client=completed_handle(connect),peer=completed_handle(accept);
    size_t write=io(3,client,"group",0,2000);assert(wait_for(write)==1);mfnet_release(write);
    size_t read=io(2,peer,"",5,2000);assert(wait_for(read)==1);mfnet_release(read);
    read=io(2,client,"",1,2000);mfnet_close(group);assert(wait_for(read)==3);mfnet_release(read);
    mfnet_close(peer);mfnet_close(server);
    server=listener(false,"","");group=mfnet_mailbox_new(1);accept=io(4,server,"",0,2000);
    connect=endpoint_op(1,"127.0.0.1",mfnet_port(server),false,"","","");mfnet_operation_group(connect,group);
    client=completed_handle(connect);peer=completed_handle(accept);
    read=io(2,client,"",1,2000);assert(mfnet_status(read,42)==0);cleanup_hook(42);pause_ms(30);
    pthread_mutex_lock(&mu);endpoint *ep=find_ep(client);assert(!ep || ep->closed);pthread_mutex_unlock(&mu);
    mfnet_close(peer);mfnet_close(server);mfnet_close(group);
}
static void test_bad_certificate(const char *cert,const char *key) {
    size_t server=listener(true,cert,key),port=mfnet_port(server);size_t accept=io(4,server,"",0,2000);
    size_t op=endpoint_op(1,"127.0.0.1",port,true,cert,"","");assert(wait_for(op)==7);mfnet_release(op);
    assert(wait_for(accept)!=1);mfnet_release(accept);mfnet_close(server);
}
static void test_pipe(void) {
    char path[80];
#ifdef _WIN32
    snprintf(path,sizeof(path),"encore-net-%lu",(unsigned long)GetCurrentProcessId());
#else
    char directory[] = "/tmp/encore-ipc.XXXXXX";
    assert(mkdtemp(directory));
    snprintf(path,sizeof(path),"%s/socket",directory);
#endif
    mf_str address=text(path);
    size_t server=completed_handle(mfnet_local_operation(LOCAL_BIND,address,2000));
    size_t pending=io(4,server,"",0,2000);
    size_t client=completed_handle(mfnet_local_operation(LOCAL_CONNECT,address,2000));
    drop(address);
    size_t peer=completed_handle(pending);
    size_t read=io(2,peer,"",10,2000);
    size_t write=io(3,client,"ipc",0,2000);
    assert(wait_for(write)==1 && wait_for(read)==1);
    mf_str message=mfnet_data(read);
    assert(slen(message)==3 && !memcmp(sdata(message),"ipc",3));
    drop(message); mfnet_release(read); mfnet_release(write);
    read=io(2,peer,"",10,20);
    assert(wait_for(read)==4); mfnet_release(read);
    read=io(2,peer,"",10,2000);
    pause_ms(30); mfnet_cancel(read);
    assert(wait_for(read)==3); mfnet_release(read);
    mfnet_close(client);
    read=io(2,peer,"",10,2000);
    assert(wait_for(read)==1);
    message=mfnet_data(read); assert(slen(message)==0); drop(message);
    mfnet_release(read); mfnet_close(peer); mfnet_close(server);
#ifndef _WIN32
    assert(!unlink(path));
    assert(!rmdir(directory));
#endif
}
int main(int argc,char **argv) {
    test_pipe();

    assert(argc==3); roundtrip(false,"","");roundtrip(true,argv[1],argv[2]);test_listener_survives_timeout();test_mailbox();test_groups();test_bad_certificate(argv[1],argv[2]);
    for(int i=0;i<100;i++) { pause_ms(5);pthread_mutex_lock(&mu);bool empty=endpoints==NULL&&operation_count==0;pthread_mutex_unlock(&mu);if(empty) { puts("native TCP/TLS, IPC, timeout, cancellation, queue, certificate and lifetime tests passed");return 0; } }
    assert(!"native resource leak");return 1;
}
