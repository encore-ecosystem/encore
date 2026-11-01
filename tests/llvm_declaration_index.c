#include <assert.h>
#include <stdio.h>
#include <pthread.h>
#include "../packages/ehir-llvm-backend/runtime_ir.h"

static const char declarations[] =
    "%A = type { %B* }\n%B = type { %A*, i32 }\n%Dead = type { i64 }\n"
    "declare %A @sink(%A*)\n"
    "declare i32 @dead(%Dead*)\n"
    "declare i32 @self()\n"
    "declare void @address()\n"
    "@literal = private constant [10 x i8] c\"@dead %De\\00\"\n"
    "%\"quoted type\" = type { i32 }\n"
    "declare void @\"quoted\\22callee\"(%\"quoted type\"*)\n";
static void *exercise(void *raw) {
    const ehir_ir_index *index = raw;
    const char body[] =
        "; @dead(%Dead*)\n"
        "define %A @self() {\nentry:\n"
        "  %A = alloca %A\n"
        "  %x = call %A @sink(%A* %A)\n"
        "  %p = bitcast void ()* @address to i8*\n"
        "  %s = getelementptr [10 x i8], [10 x i8]* @literal, i32 0, i32 0\n"
        "  ret %A %x\n}\n";
    for (unsigned i = 0; i < 100; ++i) {
        size_t len = 0;
        char *output = ehir_ir_emit(index, body, strlen(body), &len);
        assert(output && len == strlen(output));
        assert(strstr(output, "%A = type")); assert(strstr(output, "%B = type"));
        assert(strstr(output, "declare %A @sink")); assert(strstr(output, "declare void @address"));
        assert(strstr(output, "@literal = private"));
        assert(!strstr(output, "%Dead = type")); assert(!strstr(output, "declare i32 @dead"));
        assert(!strstr(output, "declare i32 @self")); assert(!strstr(output, "%\"quoted type\" = type"));
        assert(strstr(output, body)); free(output);
    }
    return NULL;
}
int main(void) {
    ehir_ir_index *index = ehir_ir_index_new(declarations, strlen(declarations)); assert(index);
    pthread_t threads[4];
    for (unsigned i = 0; i < 4; ++i) assert(pthread_create(&threads[i], NULL, exercise, index) == 0);
    for (unsigned i = 0; i < 4; ++i) assert(pthread_join(threads[i], NULL) == 0);
    const char quoted[] = "define void @other() {\n call void @\"quoted\\22callee\"(%\"quoted type\"* null)\n ret void\n}\n";
    size_t len; char *output = ehir_ir_emit(index, quoted, strlen(quoted), &len); assert(output);
    assert(strstr(output, "declare void @\"quoted\\22callee\"")); assert(strstr(output, "%\"quoted type\" = type"));
    free(output);
    const char external[] = "declare %A @sink(%A*)\n";
    output = ehir_ir_emit(index, external, strlen(external), &len); assert(output);
    char *first = strstr(output, "declare %A @sink"); assert(first && !strstr(first + 1, "declare %A @sink"));
    assert(strstr(output, "%B = type")); free(output);
    ehir_ir_index_free(index);
    assert(!ehir_ir_index_new("not a declaration", 17));
    assert(!ehir_ir_index_new("define void @bad() {}", 21));
    index = ehir_ir_index_new("", 0); assert(index); output = ehir_ir_emit(index, "", 0, &len); assert(output && len == 0);
    free(output); ehir_ir_index_free(index); puts("LLVM declaration closure: ok");
}
