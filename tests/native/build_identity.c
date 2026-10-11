#include "../../runtime/build_identity.h"
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

int main(void) {
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
