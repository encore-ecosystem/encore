#include "../../runtime/build_identity_index.h"
#include <assert.h>
#include <stdio.h>

static void check(const char *text, const char *needle, bool protected) {
    const char *position = strstr(text, needle);
    assert(position != NULL);
    unsigned char *mask = encore_build_generic_mask(text, strlen(text), "T", 1);
    assert(mask != NULL);
    assert((mask[(size_t)(position - text)] != 0) == protected);
    free(mask);
}

static void check_admission(void) {
    char owned[] = "Value";
    const encore_identity_name names[] = {
        {owned, 5}, {"Next", 4}, {"Value", 5}, {"é", 2}, {"a.b", 3}, {"", 0}
    };
    const char *absent = "__encore_t6c656674__Value ValueSuffix _Value Value_";
    encore_identity_index *index = encore_identity_index_new(absent, strlen(absent), names, 6);
    assert(index != NULL);
    owned[0] = 'X'; /* The index owns its keys independently of the caller. */
    assert(!encore_identity_index_contains(index, "Value", 5));
    assert(!encore_identity_index_contains(index, "Next", 4));
    assert(encore_identity_index_contains(index, "é", 2));
    assert(encore_identity_index_contains(index, "a.b", 3));
    assert(encore_identity_index_contains(index, "", 0));
    assert(encore_identity_index_contains(index, "unknown", 7));
    encore_identity_index_note(index, "Box[Next]", 9);
    assert(encore_identity_index_contains(index, "Next", 4));
    assert(!encore_identity_index_contains(index, "Value", 5));
    encore_identity_index_note(index, "Value", 5);
    assert(encore_identity_index_contains(index, "Value", 5));
    encore_identity_index_free(index);
    const char *corpus[] = {"Value", "Vec[Value]", "Value::read", "\"Value\"",
        "// Value", "getfield obj > Value", "fn f[Value](x: Value)", "éValue", "Valueé"};
    const encore_identity_name value = {"Value", 5};
    for (size_t i = 0; i < sizeof(corpus) / sizeof(*corpus); ++i) {
        index = encore_identity_index_new(corpus[i], strlen(corpus[i]), &value, 1);
        assert(index != NULL && encore_identity_index_contains(index, "Value", 5));
        encore_identity_index_free(index);
    }
    const char binary[] = {'x', '\0', 'V', 'a', 'l', 'u', 'e'};
    index = encore_identity_index_new(binary, sizeof(binary), &value, 1);
    assert(index != NULL && encore_identity_index_contains(index, "Value", 5));
    encore_identity_index_free(index);
    index = encore_identity_index_new("", 0, &value, 1);
    assert(index != NULL && !encore_identity_index_contains(index, "Value", 5));
    encore_identity_index_free(index);
    assert(encore_identity_index_new("", 0, NULL, 0) == NULL);
    assert(encore_identity_index_new("", 0, NULL, SIZE_MAX) == NULL);
    const encore_identity_name huge = {"", SIZE_MAX};
    assert(encore_identity_index_new("", 0, &huge, 1) == NULL);
    assert(encore_identity_index_contains(NULL, "Value", 5));
    encore_identity_index_note(NULL, "Value", 5);
    encore_identity_index_free(NULL);
}

int main(void) {
    check_admission();
    const char *text = "struct T {\n n: u32\n}\nstruct Box[T] {\n value: T\n}\n"
        "fn identity[T](value: T) -> T {\n entry {\n ret value: T\n }\n}\n"
        "fn plain(value: T) -> T {\n entry {\n ret value: T\n }\n}\n"
        "impl[T] Box[T] {\n fn get(self: Box[T]) -> T {\n ret self: T\n }\n}\n"
        "impl Box[T] {\n fn nominal(value: T) -> T\n}\n";
    check(text, "T {", false);
    check(text, "T] {\n value", true);
    check(text, "T) -> T {\n entry {\n ret value: T\n }\n}\nfn plain", true);
    check(text, "T) -> T {\n entry {\n ret value: T\n }\n}\nimpl", false);
    check(text, "T]) -> T", true);
    check(text, "T) -> T\n}", false);
    // A quoted brace or a comment cannot terminate an active lexical scope.
    check("fn quoted[T](value: T) -> T {\n // }\n str = \"}\"\n ret value: T\n}\n", "T\n}", true);
    const char *members = "struct T {\n T: T\n}\nenum Json {\n T(T)\n Empty\n}\n";
    check(members, "T(T)", true);
    check(members, "T)\n", false);
    assert(encore_build_member_identifier("Json::T", 7, 6, 1));
    assert(encore_build_member_identifier("T: T", 4, 0, 1));
    assert(!encore_build_member_identifier("T: T", 4, 3, 1));
    assert(!encore_build_member_identifier("T::read", 7, 0, 1));
    assert(encore_build_member_identifier("getfield value > T", 18, 17, 1));
    assert(encore_build_member_identifier("v = ieq value, T", 16, 15, 1));
    assert(!encore_build_member_identifier("v = ieq value: T, other", 23, 15, 1));
    puts("generic identity scopes passed");
    return 0;
}
