#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#if defined(__linux__)
#include <dlfcn.h>
#endif

typedef struct {
    size_t ref_count;
    size_t len;
    char data[];
} encore_str_object;

typedef struct {
    encore_str_object *object;
} encore_str;

static char *cad_str_data(encore_str value) {
    if (value.object == NULL) {
        return NULL;
    }
    return value.object->data;
}

static size_t cad_str_len(encore_str value) {
    if (value.object == NULL) {
        return 0;
    }
    return value.object->len;
}

static char *cad_to_cstr(encore_str value) {
    size_t len = cad_str_len(value);
    char *out = malloc(len + 1);
    if (out == NULL) {
        return NULL;
    }
    char *data = cad_str_data(value);
    if (len > 0 && data != NULL) {
        memcpy(out, data, len);
    }
    out[len] = '\0';
    return out;
}

#if defined(__linux__)
typedef struct _XDisplay CadDisplay;
typedef void *CadGc;
typedef unsigned long CadWindowId;
typedef unsigned long CadAtom;
typedef unsigned long CadFont;

enum {
    CAD_EVENT_NONE = 0,
    CAD_EVENT_KEY = 1,
    CAD_EVENT_MOUSE_DOWN = 2,
    CAD_EVENT_MOUSE_UP = 3,
    CAD_EVENT_MOUSE_MOVE = 4
};

typedef struct {
    void *lib;
    bool initialized;
    bool available;

    CadDisplay *(*XOpenDisplay)(const char *);
    int (*XDefaultScreen)(CadDisplay *);
    CadWindowId (*XRootWindow)(CadDisplay *, int);
    unsigned long (*XBlackPixel)(CadDisplay *, int);
    unsigned long (*XWhitePixel)(CadDisplay *, int);
    CadWindowId (*XCreateSimpleWindow)(
        CadDisplay *,
        CadWindowId,
        int,
        int,
        unsigned int,
        unsigned int,
        unsigned int,
        unsigned long,
        unsigned long);
    int (*XStoreName)(CadDisplay *, CadWindowId, const char *);
    int (*XSelectInput)(CadDisplay *, CadWindowId, long);
    int (*XMapWindow)(CadDisplay *, CadWindowId);
    CadGc (*XCreateGC)(CadDisplay *, CadWindowId, unsigned long, void *);
    int (*XFreeGC)(CadDisplay *, CadGc);
    int (*XSetForeground)(CadDisplay *, CadGc, unsigned long);
    int (*XSetLineAttributes)(CadDisplay *, CadGc, unsigned int, int, int, int);
    int (*XSetFont)(CadDisplay *, CadGc, CadFont);
    void *(*XLoadQueryFont)(CadDisplay *, const char *);
    int (*XFreeFont)(CadDisplay *, void *);
    int (*XFillRectangle)(CadDisplay *, CadWindowId, CadGc, int, int, unsigned int, unsigned int);
    int (*XDrawLine)(CadDisplay *, CadWindowId, CadGc, int, int, int, int);
    int (*XDrawString)(CadDisplay *, CadWindowId, CadGc, int, int, const char *, int);
    int (*XLookupString)(void *, char *, int, unsigned long *, void *);
    int (*XFlush)(CadDisplay *);
    int (*XPending)(CadDisplay *);
    int (*XNextEvent)(CadDisplay *, void *);
    int (*XDestroyWindow)(CadDisplay *, CadWindowId);
    int (*XCloseDisplay)(CadDisplay *);
    CadAtom (*XInternAtom)(CadDisplay *, const char *, int);
    int (*XSetWMProtocols)(CadDisplay *, CadWindowId, CadAtom *, int);
} CadX11Api;

typedef struct {
    CadDisplay *display;
    CadWindowId window;
    CadGc gc;
    CadAtom wm_delete;
    void *font_info;
    bool open;
    uint32_t width;
    uint32_t height;
    uint32_t last_event_kind;
    int32_t last_event_x;
    int32_t last_event_y;
    uint32_t last_event_key;
} CadWindow;

typedef struct {
    void *ext_data;
    CadFont fid;
} CadXFontStructHeader;

typedef struct {
    int type;
    unsigned long serial;
    int send_event;
    CadDisplay *display;
    CadWindowId window;
    CadAtom message_type;
    int format;
    union {
        char b[20];
        short s[10];
        long l[5];
    } data;
} CadXClientMessageEvent;

typedef struct {
    int type;
    unsigned long serial;
    int send_event;
    CadDisplay *display;
    CadWindowId window;
    CadWindowId root;
    CadWindowId subwindow;
    unsigned long time;
    int x;
    int y;
    int x_root;
    int y_root;
    unsigned int state;
    unsigned int keycode;
    int same_screen;
} CadXKeyEvent;

typedef struct {
    int type;
    unsigned long serial;
    int send_event;
    CadDisplay *display;
    CadWindowId window;
    CadWindowId root;
    CadWindowId subwindow;
    unsigned long time;
    int x;
    int y;
    int x_root;
    int y_root;
    unsigned int state;
    unsigned int button;
    int same_screen;
} CadXButtonEvent;

typedef struct {
    int type;
    unsigned long serial;
    int send_event;
    CadDisplay *display;
    CadWindowId window;
    CadWindowId root;
    CadWindowId subwindow;
    unsigned long time;
    int x;
    int y;
    int x_root;
    int y_root;
    unsigned int state;
    char is_hint;
    int same_screen;
} CadXMotionEvent;

static CadX11Api g_cad_x11 = {0};

#define CAD_X11_LOAD(field)                                                               \
    do {                                                                                  \
        *(void **)(&g_cad_x11.field) = dlsym(g_cad_x11.lib, #field);                      \
        if (g_cad_x11.field == NULL) {                                                    \
            dlclose(g_cad_x11.lib);                                                       \
            memset(&g_cad_x11, 0, sizeof(g_cad_x11));                                     \
            g_cad_x11.initialized = true;                                                 \
            return false;                                                                 \
        }                                                                                 \
    } while (0)

static bool cad_x11_load(void) {
    if (g_cad_x11.initialized) {
        return g_cad_x11.available;
    }

    g_cad_x11.initialized = true;
    g_cad_x11.lib = dlopen("libX11.so.6", RTLD_LAZY | RTLD_LOCAL);
    if (g_cad_x11.lib == NULL) {
        g_cad_x11.lib = dlopen("libX11.so", RTLD_LAZY | RTLD_LOCAL);
    }
    if (g_cad_x11.lib == NULL) {
        return false;
    }

    CAD_X11_LOAD(XOpenDisplay);
    CAD_X11_LOAD(XDefaultScreen);
    CAD_X11_LOAD(XRootWindow);
    CAD_X11_LOAD(XBlackPixel);
    CAD_X11_LOAD(XWhitePixel);
    CAD_X11_LOAD(XCreateSimpleWindow);
    CAD_X11_LOAD(XStoreName);
    CAD_X11_LOAD(XSelectInput);
    CAD_X11_LOAD(XMapWindow);
    CAD_X11_LOAD(XCreateGC);
    CAD_X11_LOAD(XFreeGC);
    CAD_X11_LOAD(XSetForeground);
    CAD_X11_LOAD(XSetLineAttributes);
    CAD_X11_LOAD(XSetFont);
    CAD_X11_LOAD(XLoadQueryFont);
    CAD_X11_LOAD(XFreeFont);
    CAD_X11_LOAD(XFillRectangle);
    CAD_X11_LOAD(XDrawLine);
    CAD_X11_LOAD(XDrawString);
    CAD_X11_LOAD(XLookupString);
    CAD_X11_LOAD(XFlush);
    CAD_X11_LOAD(XPending);
    CAD_X11_LOAD(XNextEvent);
    CAD_X11_LOAD(XDestroyWindow);
    CAD_X11_LOAD(XCloseDisplay);
    CAD_X11_LOAD(XInternAtom);
    CAD_X11_LOAD(XSetWMProtocols);

    g_cad_x11.available = true;
    return true;
}

#undef CAD_X11_LOAD

static CadWindow *cad_window_from_handle(size_t handle) {
    if (handle == 0) {
        return NULL;
    }
    return (CadWindow *)(uintptr_t)handle;
}

size_t cad_gui_window_create(encore_str title, uint32_t width, uint32_t height) {
    if (width == 0 || height == 0 || !cad_x11_load()) {
        return 0;
    }

    CadDisplay *display = g_cad_x11.XOpenDisplay(NULL);
    if (display == NULL) {
        return 0;
    }

    CadWindow *state = calloc(1, sizeof(CadWindow));
    if (state == NULL) {
        g_cad_x11.XCloseDisplay(display);
        return 0;
    }

    int screen = g_cad_x11.XDefaultScreen(display);
    CadWindowId root = g_cad_x11.XRootWindow(display, screen);
    unsigned long black = g_cad_x11.XBlackPixel(display, screen);
    unsigned long white = g_cad_x11.XWhitePixel(display, screen);

    CadWindowId window = g_cad_x11.XCreateSimpleWindow(display, root, 80, 80, width, height, 0, black, white);
    if (window == 0) {
        free(state);
        g_cad_x11.XCloseDisplay(display);
        return 0;
    }

    CadGc gc = g_cad_x11.XCreateGC(display, window, 0, NULL);
    if (gc == NULL) {
        g_cad_x11.XDestroyWindow(display, window);
        free(state);
        g_cad_x11.XCloseDisplay(display);
        return 0;
    }

    char *title_c = cad_to_cstr(title);
    if (title_c != NULL) {
        g_cad_x11.XStoreName(display, window, title_c);
        free(title_c);
    }

    const long event_mask = (1L << 15) | (1L << 17) | (1L << 0) | (1L << 2) | (1L << 3) | (1L << 6);
    g_cad_x11.XSelectInput(display, window, event_mask);

    CadAtom wm_delete = g_cad_x11.XInternAtom(display, "WM_DELETE_WINDOW", 0);
    if (wm_delete != 0) {
        g_cad_x11.XSetWMProtocols(display, window, &wm_delete, 1);
    }

    g_cad_x11.XMapWindow(display, window);
    g_cad_x11.XSetLineAttributes(display, gc, 1, 0, 0, 0);
    g_cad_x11.XFlush(display);

    state->display = display;
    state->window = window;
    state->gc = gc;
    state->wm_delete = wm_delete;
    state->open = true;
    state->width = width;
    state->height = height;

    return (size_t)(uintptr_t)state;
}

bool cad_gui_window_is_open(size_t handle) {
    CadWindow *state = cad_window_from_handle(handle);
    return state != NULL && state->open;
}

bool cad_gui_window_poll(size_t handle) {
    CadWindow *state = cad_window_from_handle(handle);
    if (state == NULL || !state->open) {
        return false;
    }

    state->last_event_kind = CAD_EVENT_NONE;
    state->last_event_key = 0;

    while (g_cad_x11.XPending(state->display) > 0) {
        long event_storage[24];
        memset(event_storage, 0, sizeof(event_storage));
        g_cad_x11.XNextEvent(state->display, event_storage);

        int type = *((int *)event_storage);
        if (type == 2) {
            CadXKeyEvent *key_event = (CadXKeyEvent *)event_storage;
            char key_text[8];
            memset(key_text, 0, sizeof(key_text));
            unsigned long keysym = 0;
            int count = g_cad_x11.XLookupString(key_event, key_text, (int)sizeof(key_text) - 1, &keysym, NULL);
            state->last_event_kind = CAD_EVENT_KEY;
            state->last_event_x = key_event->x;
            state->last_event_y = key_event->y;
            state->last_event_key = count > 0 ? (uint32_t)(unsigned char)key_text[0] : (uint32_t)keysym;
        } else if (type == 4) {
            CadXButtonEvent *button_event = (CadXButtonEvent *)event_storage;
            state->last_event_kind = CAD_EVENT_MOUSE_DOWN;
            state->last_event_x = button_event->x;
            state->last_event_y = button_event->y;
            state->last_event_key = button_event->button;
        } else if (type == 5) {
            CadXButtonEvent *button_event = (CadXButtonEvent *)event_storage;
            state->last_event_kind = CAD_EVENT_MOUSE_UP;
            state->last_event_x = button_event->x;
            state->last_event_y = button_event->y;
            state->last_event_key = button_event->button;
        } else if (type == 6) {
            CadXMotionEvent *motion_event = (CadXMotionEvent *)event_storage;
            state->last_event_kind = CAD_EVENT_MOUSE_MOVE;
            state->last_event_x = motion_event->x;
            state->last_event_y = motion_event->y;
            state->last_event_key = 0;
        } else if (type == 17) {
            state->open = false;
        } else if (type == 33 && state->wm_delete != 0) {
            CadXClientMessageEvent *client = (CadXClientMessageEvent *)event_storage;
            if (client->format == 32 && (CadAtom)client->data.l[0] == state->wm_delete) {
                state->open = false;
            }
        }
    }

    return state->open;
}

bool cad_gui_window_clear(size_t handle, uint32_t color_rgb) {
    CadWindow *state = cad_window_from_handle(handle);
    if (state == NULL || !state->open) {
        return false;
    }

    g_cad_x11.XSetForeground(state->display, state->gc, (unsigned long)color_rgb);
    g_cad_x11.XFillRectangle(state->display, state->window, state->gc, 0, 0, state->width, state->height);
    return true;
}

bool cad_gui_window_fill_rect(size_t handle, int32_t x, int32_t y, uint32_t width, uint32_t height, uint32_t color_rgb) {
    CadWindow *state = cad_window_from_handle(handle);
    if (state == NULL || !state->open || width == 0 || height == 0) {
        return false;
    }

    g_cad_x11.XSetForeground(state->display, state->gc, (unsigned long)color_rgb);
    g_cad_x11.XFillRectangle(state->display, state->window, state->gc, x, y, width, height);
    return true;
}

bool cad_gui_window_line(size_t handle, int32_t x0, int32_t y0, int32_t x1, int32_t y1, uint32_t color_rgb) {
    CadWindow *state = cad_window_from_handle(handle);
    if (state == NULL || !state->open) {
        return false;
    }

    g_cad_x11.XSetForeground(state->display, state->gc, (unsigned long)color_rgb);
    g_cad_x11.XDrawLine(state->display, state->window, state->gc, x0, y0, x1, y1);
    return true;
}

bool cad_gui_window_text(size_t handle, int32_t x, int32_t y, encore_str value, uint32_t color_rgb) {
    CadWindow *state = cad_window_from_handle(handle);
    if (state == NULL || !state->open) {
        return false;
    }

    char *text = cad_to_cstr(value);
    if (text == NULL) {
        return false;
    }

    g_cad_x11.XSetForeground(state->display, state->gc, (unsigned long)color_rgb);
    g_cad_x11.XDrawString(state->display, state->window, state->gc, x, y, text, (int)cad_str_len(value));
    free(text);
    return true;
}

bool cad_gui_window_set_font(size_t handle, encore_str value) {
    CadWindow *state = cad_window_from_handle(handle);
    if (state == NULL || !state->open) {
        return false;
    }

    char *font_name = cad_to_cstr(value);
    if (font_name == NULL) {
        return false;
    }

    void *font_info = g_cad_x11.XLoadQueryFont(state->display, font_name);
    free(font_name);
    if (font_info == NULL) {
        return false;
    }

    CadXFontStructHeader *font_header = (CadXFontStructHeader *)font_info;
    g_cad_x11.XSetFont(state->display, state->gc, font_header->fid);

    if (state->font_info != NULL) {
        g_cad_x11.XFreeFont(state->display, state->font_info);
    }
    state->font_info = font_info;
    return true;
}

uint32_t cad_gui_window_event_kind(size_t handle) {
    CadWindow *state = cad_window_from_handle(handle);
    if (state == NULL || !state->open) {
        return CAD_EVENT_NONE;
    }
    return state->last_event_kind;
}

int32_t cad_gui_window_event_x(size_t handle) {
    CadWindow *state = cad_window_from_handle(handle);
    if (state == NULL || !state->open) {
        return 0;
    }
    return state->last_event_x;
}

int32_t cad_gui_window_event_y(size_t handle) {
    CadWindow *state = cad_window_from_handle(handle);
    if (state == NULL || !state->open) {
        return 0;
    }
    return state->last_event_y;
}

uint32_t cad_gui_window_event_key(size_t handle) {
    CadWindow *state = cad_window_from_handle(handle);
    if (state == NULL || !state->open) {
        return 0;
    }
    return state->last_event_key;
}

bool cad_gui_window_present(size_t handle) {
    CadWindow *state = cad_window_from_handle(handle);
    if (state == NULL || !state->open) {
        return false;
    }
    g_cad_x11.XFlush(state->display);
    return true;
}

bool cad_gui_window_destroy(size_t handle) {
    CadWindow *state = cad_window_from_handle(handle);
    if (state == NULL) {
        return false;
    }

    if (state->display != NULL) {
        if (state->font_info != NULL) {
            g_cad_x11.XFreeFont(state->display, state->font_info);
        }
        if (state->gc != NULL) {
            g_cad_x11.XFreeGC(state->display, state->gc);
        }
        if (state->window != 0) {
            g_cad_x11.XDestroyWindow(state->display, state->window);
        }
        g_cad_x11.XCloseDisplay(state->display);
    }

    free(state);
    return true;
}
#else
size_t cad_gui_window_create(encore_str title, uint32_t width, uint32_t height) {
    (void)title;
    (void)width;
    (void)height;
    return 0;
}

bool cad_gui_window_is_open(size_t handle) {
    (void)handle;
    return false;
}

bool cad_gui_window_poll(size_t handle) {
    (void)handle;
    return false;
}

bool cad_gui_window_clear(size_t handle, uint32_t color_rgb) {
    (void)handle;
    (void)color_rgb;
    return false;
}

bool cad_gui_window_fill_rect(size_t handle, int32_t x, int32_t y, uint32_t width, uint32_t height, uint32_t color_rgb) {
    (void)handle;
    (void)x;
    (void)y;
    (void)width;
    (void)height;
    (void)color_rgb;
    return false;
}

bool cad_gui_window_line(size_t handle, int32_t x0, int32_t y0, int32_t x1, int32_t y1, uint32_t color_rgb) {
    (void)handle;
    (void)x0;
    (void)y0;
    (void)x1;
    (void)y1;
    (void)color_rgb;
    return false;
}

bool cad_gui_window_text(size_t handle, int32_t x, int32_t y, encore_str value, uint32_t color_rgb) {
    (void)handle;
    (void)x;
    (void)y;
    (void)value;
    (void)color_rgb;
    return false;
}

bool cad_gui_window_set_font(size_t handle, encore_str value) {
    (void)handle;
    (void)value;
    return false;
}

uint32_t cad_gui_window_event_kind(size_t handle) {
    (void)handle;
    return 0;
}

int32_t cad_gui_window_event_x(size_t handle) {
    (void)handle;
    return 0;
}

int32_t cad_gui_window_event_y(size_t handle) {
    (void)handle;
    return 0;
}

uint32_t cad_gui_window_event_key(size_t handle) {
    (void)handle;
    return 0;
}

bool cad_gui_window_present(size_t handle) {
    (void)handle;
    return false;
}

bool cad_gui_window_destroy(size_t handle) {
    (void)handle;
    return false;
}
#endif
