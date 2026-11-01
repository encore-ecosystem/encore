/* Exercise real filesystem names, not only lexical Path operations. */
#include "../runtime.c"
#include <assert.h>
extern void encore_str_drop(encore_str);

static void equals(encore_str value, const char *expected) {
    assert(encore_str_size(value) == strlen(expected));
    assert(memcmp(encore_str_data(value), expected, strlen(expected)) == 0);
    encore_str_drop(value);
}

int main(void) {
    encore_str root = encore_from_cstr_copy("unicode пути 📦");
    encore_str nested = encore_from_cstr_copy("unicode пути 📦/каталог");
    encore_str file = encore_from_cstr_copy("unicode пути 📦/каталог/данные.txt");
    encore_str copy = encore_from_cstr_copy("unicode пути 📦/копия.txt");
    encore_str value = encore_from_cstr_copy("payload 📁");
    assert(encore_fs_mkdir(root) == 0);
    assert(encore_fs_mkdir_all(nested) == 0);
    assert(encore_fs_status(nested) == 0 && encore_fs_is_directory(nested));
#ifdef _WIN32
    /* A round trip through the same ANSI APIs can conceal mojibake. */
    assert(GetFileAttributesW(L"unicode пути 📦/каталог") != INVALID_FILE_ATTRIBUTES);
#endif
    assert(encore_fs_write_file(file, value) == 0);
    equals(encore_fs_read_file(file), "payload 📁");
    assert(encore_fs_write_file_atomic(file, value) == 0);
    uint64_t handle = encore_file_open(file, false);
    assert(handle != 0);
    equals(encore_file_read_all(handle), "payload 📁");
    assert(encore_file_close(handle));
    assert(encore_fs_copy_file(file, copy) == 0);
    equals(encore_fs_read_file(copy), "payload 📁");
#ifdef _WIN32
    /* A valid destination must remain copyable when appending a temporary
     * suffix would exceed MAX_PATH (as with content-addressed archives). */
    wchar_t *directory = _wgetcwd(NULL, 0);
    assert(directory != NULL);
    size_t directory_length = wcslen(directory);
    wchar_t near_limit[250];
    assert(directory_length + 2 < 249);
    memcpy(near_limit, directory, directory_length * sizeof(wchar_t));
    near_limit[directory_length] = L'\\';
    for (size_t i = directory_length + 1; i < 249; ++i) near_limit[i] = L'a';
    near_limit[249] = L'\0';
    char *near_limit_utf8 = encore_windows_utf8(near_limit);
    assert(near_limit_utf8 != NULL);
    encore_str long_copy = encore_from_cstr_copy(near_limit_utf8);
    free(near_limit_utf8); free(directory);
#else
    /* The same invariant applies to NAME_MAX on POSIX filesystems. */
    char near_limit[256];
    memset(near_limit, 'a', 255);
    near_limit[255] = '\0';
    encore_str long_copy = encore_from_cstr_copy(near_limit);
#endif
    assert(encore_fs_write_file(long_copy, value) == 0);
    assert(encore_fs_copy_file(file, long_copy) == 0);
    equals(encore_fs_read_file(long_copy), "payload 📁");
    assert(encore_fs_copy_file(file, long_copy) == 0);
    assert(encore_fs_remove_file(long_copy) == 0);
    encore_str_drop(long_copy);
    encore_str digest = encore_fs_sha256(copy), expected = encore_text_sha256(value);
    assert(encore_str_size(digest) == 64 && memcmp(encore_str_data(digest), encore_str_data(expected), 64) == 0);
    encore_str_drop(digest); encore_str_drop(expected);
    equals(encore_fs_read_dir(nested), "данные.txt");
#ifdef _WIN32
    wchar_t *cwd = _wgetcwd(NULL, 0);
    assert(cwd != NULL && _wchdir(L"unicode пути 📦/каталог") == 0);
    encore_str actual = encore_os_cwd();
    wchar_t *wide = _wgetcwd(NULL, 0);
    char *utf8 = encore_windows_utf8(wide);
    equals(actual, utf8);
    assert(_wchdir(cwd) == 0);
    free(utf8); free(wide); free(cwd);
#endif
    assert(encore_fs_remove_file(copy) == 0 && encore_fs_status(copy) != 0);
    assert(encore_fs_remove_dir_all(root) == 0 && encore_fs_status(root) != 0);
    assert(encore_fs_remove_dir_all(root) == 0);
    encore_str_drop(root); encore_str_drop(nested); encore_str_drop(file);
    encore_str_drop(copy); encore_str_drop(value);
    puts("UTF-8 filesystem paths passed");
    return 0;
}
