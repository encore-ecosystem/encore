/* Encore paths are UTF-8, independent of the Windows ANSI code page. */
#ifdef _WIN32
#include "windows_unicode.h"
static int encore_windows_mkdir(const char *path) {
    wchar_t *wide = encore_windows_utf16(path);
    if (wide == NULL) return -1;
    int status = _wmkdir(wide);
    free(wide);
    return status;
}
static int encore_windows_open_exclusive(const char *path) {
    wchar_t *wide = encore_windows_utf16(path);
    if (wide == NULL) return -1;
    int descriptor = _wopen(wide, _O_CREAT | _O_EXCL | _O_WRONLY | _O_BINARY, _S_IREAD | _S_IWRITE);
    free(wide);
    return descriptor;
}
static DWORD encore_windows_attributes(const char *path) {
    wchar_t *wide = encore_windows_utf16(path);
    if (wide == NULL) return INVALID_FILE_ATTRIBUTES;
    DWORD attributes = GetFileAttributesW(wide);
    free(wide);
    return attributes;
}
static int encore_windows_move(const char *source, const char *destination, DWORD flags) {
    wchar_t *from = encore_windows_utf16(source), *to = encore_windows_utf16(destination);
    int status = from != NULL && to != NULL && MoveFileExW(from, to, flags) ? 0 : -1;
    free(from); free(to);
    return status;
}
#endif

static FILE *encore_path_fopen(const char *path, const char *mode) {
#ifdef _WIN32
    wchar_t *wide_path = encore_windows_utf16(path), *wide_mode = encore_windows_utf16(mode);
    FILE *stream = wide_path != NULL && wide_mode != NULL ? _wfopen(wide_path, wide_mode) : NULL;
    free(wide_path); free(wide_mode);
    return stream;
#else
    return fopen(path, mode);
#endif
}
static int encore_path_remove(const char *path) {
#ifdef _WIN32
    wchar_t *wide = encore_windows_utf16(path);
    if (wide == NULL) return -1;
    int status = _wremove(wide);
    free(wide);
    return status;
#else
    return remove(path);
#endif
}
