#ifndef ENCORE_WINDOWS_UNICODE_H
#define ENCORE_WINDOWS_UNICODE_H
#include <windows.h>
#include <errno.h>
#include <stdlib.h>
#include <wchar.h>
static inline wchar_t *encore_windows_utf16(const char *text) {
    if (text == NULL) return NULL;
    int count = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text, -1, NULL, 0);
    if (count <= 0) { errno = EINVAL; return NULL; }
    wchar_t *wide = malloc((size_t)count * sizeof(*wide));
    if (wide != NULL && !MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text, -1, wide, count)) {
        free(wide); errno = EINVAL; return NULL;
    }
    return wide;
}
static inline char *encore_windows_utf8(const wchar_t *wide) {
    int count = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, wide, -1, NULL, 0, NULL, NULL);
    if (count <= 0) return NULL;
    char *text = malloc((size_t)count);
    if (text != NULL && !WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, wide, -1, text, count, NULL, NULL)) {
        free(text); return NULL;
    }
    return text;
}
#endif
