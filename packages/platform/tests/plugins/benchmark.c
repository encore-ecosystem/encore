/* Compare the manager with the same DSO's direct C ABI, on the same object. */
#include "../../plugin_runtime.c"
#ifdef _WIN32
#include <shellapi.h>
#include <psapi.h>
#else
#include <sys/resource.h>
#endif

static double nanoseconds(void) {
#ifdef _WIN32
    LARGE_INTEGER value, frequency; QueryPerformanceCounter(&value); QueryPerformanceFrequency(&frequency);
    return (double)value.QuadPart * 1e9 / (double)frequency.QuadPart;
#else
    struct timespec now; clock_gettime(CLOCK_MONOTONIC, &now);
    return (double)now.tv_sec * 1e9 + (double)now.tv_nsec;
#endif
}
static void benchmark(encore_plugin_binding *binding) {
    const size_t iterations = 500000;
    encore_plugin_value arg = {.kind=ENCORE_PLUGIN_U64,.bits=1}, value;
    encore_plugin_error error = {0};
    encore_plugin_object object = binding->object;
    encore_plugin_method method = object.interface->methods[0];
    double direct_start = nanoseconds();
    for (size_t i=0;i<iterations;++i) {
        assert(method.invoke(method.context,object.data,&arg,1,NULL,&value,&error)==ENCORE_PLUGIN_OK);
    }
    double direct = (nanoseconds()-direct_start)/(double)iterations;
    double checked_start = nanoseconds();
    for (size_t i=0;i<iterations;++i) {
        encore_plugin_call frame;
        assert(encore_plugin_invoke(binding,0,&arg,1,&frame)==ENCORE_PLUGIN_OK);
        assert(frame.allocations==NULL); /* Scalar manager path never allocates. */
        encore_plugin_call_clear(&frame);
    }
    double checked = (nanoseconds()-checked_start)/(double)iterations;
    size_t rss;
#ifdef _WIN32
    PROCESS_MEMORY_COUNTERS counters; assert(GetProcessMemoryInfo(GetCurrentProcess(),&counters,sizeof(counters)));
    rss=(size_t)counters.PeakWorkingSetSize;
#else
    struct rusage usage; assert(getrusage(RUSAGE_SELF,&usage)==0);
#ifdef __APPLE__
    rss=(size_t)usage.ru_maxrss;
#else
    rss=(size_t)usage.ru_maxrss*1024;
#endif
#endif
    printf("{\"case\":\"scalar-u64\",\"iterations\":%zu,\"direct_c_abi_ns\":%.2f,\"manager_ns\":%.2f,\"peak_rss_bytes\":%zu}\n",iterations,direct,checked,rss);
}
int main(int argc,char **argv) {
#ifdef _WIN32
    int count; wchar_t **wide=CommandLineToArgvW(GetCommandLineW(),&count); assert(wide && count==argc);
    int bytes=WideCharToMultiByte(CP_UTF8,WC_ERR_INVALID_CHARS,wide[1],-1,NULL,0,NULL,NULL); assert(bytes>0);
    char *path=malloc((size_t)bytes); assert(path);
    assert(WideCharToMultiByte(CP_UTF8,WC_ERR_INVALID_CHARS,wide[1],-1,path,bytes,NULL,NULL)); LocalFree(wide);
#else
    const char *path=argv[1];
#endif
    assert(argc==2); (void)argv;
    encore_plugin_module *module=NULL; encore_plugin_binding *binding=NULL; encore_plugin_diagnostic error;
    assert(encore_plugin_load(path,NULL,&module,&error)==ENCORE_PLUGIN_OK);
    assert(encore_plugin_bind(module,"counter","counter-contract-v1",&binding,&error)==ENCORE_PLUGIN_OK);
    benchmark(binding); encore_plugin_binding_release(binding); encore_plugin_module_release(module);
#ifdef _WIN32
    free(path);
#endif
    return 0;
}
