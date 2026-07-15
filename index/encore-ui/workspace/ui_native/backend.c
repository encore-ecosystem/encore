#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#if defined(_WIN32)
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#else
#include <dlfcn.h>
#endif

typedef struct { size_t ref_count; size_t len; char data[]; } encore_str_object;
typedef struct { encore_str_object *object; } encore_str;
extern void *encore_str_from_cstr(const char *value);

typedef struct UiSdlWindow UiSdlWindow;
typedef struct UiSdlRenderer UiSdlRenderer;
typedef struct { float x, y, w, h; } UiSdlFRect;

typedef union {
    uint32_t type;
    uint8_t padding[128];
} UiSdlEvent;

typedef struct {
    uint32_t type;
    uint32_t reserved;
    uint64_t timestamp;
    uint32_t window_id;
    uint32_t which;
    uint64_t state;
    float x;
    float y;
    float xrel;
    float yrel;
} UiSdlMouseMotionEvent;

typedef struct {
    uint32_t type;
    uint32_t reserved;
    uint64_t timestamp;
    uint32_t window_id;
    uint32_t which;
    uint8_t button;
    bool down;
    uint8_t clicks;
    uint8_t padding;
    float x;
    float y;
} UiSdlMouseButtonEvent;

typedef struct {
    uint32_t type;
    uint32_t reserved;
    uint64_t timestamp;
    uint32_t window_id;
    uint32_t which;
    float x;
    float y;
    uint32_t direction;
    float mouse_x;
    float mouse_y;
} UiSdlMouseWheelEvent;

typedef struct {
    uint32_t type;
    uint32_t reserved;
    uint64_t timestamp;
    uint32_t window_id;
    uint32_t which;
    uint32_t scancode;
    uint32_t key;
    uint16_t mod;
    uint16_t raw;
    bool down;
    bool repeat;
} UiSdlKeyboardEvent;

enum {
    UI_SDL_INIT_VIDEO = 0x00000020u,
    UI_SDL_EVENT_QUIT = 0x100,
    UI_SDL_EVENT_WINDOW_CLOSE = 0x210,
    UI_SDL_EVENT_KEY_DOWN = 0x300,
    UI_SDL_EVENT_KEY_UP = 0x301,
    UI_SDL_EVENT_MOUSE_MOTION = 0x400,
    UI_SDL_EVENT_MOUSE_BUTTON_DOWN = 0x401,
    UI_SDL_EVENT_MOUSE_BUTTON_UP = 0x402,
    UI_SDL_EVENT_MOUSE_WHEEL = 0x403
};

enum {
    UI_EVENT_NONE = 0,
    UI_EVENT_CLOSE = 1,
    UI_EVENT_KEY_DOWN = 2,
    UI_EVENT_KEY_UP = 3,
    UI_EVENT_POINTER_DOWN = 4,
    UI_EVENT_POINTER_UP = 5,
    UI_EVENT_POINTER_MOVE = 6,
    UI_EVENT_SCROLL = 7
};

typedef struct {
    void *library;
    bool attempted;
    bool ready;
    bool (*Init)(uint32_t);
    void (*Quit)(void);
    bool (*CreateWindowAndRenderer)(const char *, int, int, uint64_t, UiSdlWindow **, UiSdlRenderer **);
    void (*DestroyRenderer)(UiSdlRenderer *);
    void (*DestroyWindow)(UiSdlWindow *);
    bool (*PollEvent)(UiSdlEvent *);
    bool (*SetRenderDrawColor)(UiSdlRenderer *, uint8_t, uint8_t, uint8_t, uint8_t);
    bool (*RenderClear)(UiSdlRenderer *);
    bool (*RenderFillRect)(UiSdlRenderer *, const UiSdlFRect *);
    bool (*RenderRect)(UiSdlRenderer *, const UiSdlFRect *);
    bool (*RenderLine)(UiSdlRenderer *, float, float, float, float);
    bool (*RenderDebugText)(UiSdlRenderer *, float, float, const char *);
    bool (*RenderPresent)(UiSdlRenderer *);
    const char *(*GetError)(void);
} UiSdlApi;

typedef struct {
    UiSdlWindow *window;
    UiSdlRenderer *renderer;
    bool open;
    uint32_t event_kind;
    float event_x;
    float event_y;
    float wheel_x;
    float wheel_y;
    uint32_t event_key;
} UiWindow;

static UiSdlApi g_sdl;
static char g_error[256];
static size_t g_window_count;

static encore_str ui_string(const char *value) {
    encore_str result = {(encore_str_object *)encore_str_from_cstr(value == NULL ? "" : value)};
    return result;
}

static char *ui_to_cstr(encore_str value) {
    size_t len = value.object == NULL ? 0 : value.object->len;
    char *result = (char *)malloc(len + 1);
    if (result == NULL) return NULL;
    if (len > 0) memcpy(result, value.object->data, len);
    result[len] = '\0';
    return result;
}

static void ui_set_error(const char *message) {
    const char *value = message == NULL ? "unknown SDL3 error" : message;
    size_t len = strlen(value);
    if (len >= sizeof(g_error)) len = sizeof(g_error) - 1;
    memcpy(g_error, value, len);
    g_error[len] = '\0';
}

#if defined(_WIN32)
static void *ui_open_library(void) {
    const char *names[] = {"SDL3.dll", NULL};
    for (size_t i = 0; names[i] != NULL; ++i) {
        HMODULE lib = LoadLibraryA(names[i]);
        if (lib != NULL) return (void *)lib;
    }
    return NULL;
}
static void *ui_symbol(void *library, const char *name) {
    return (void *)GetProcAddress((HMODULE)library, name);
}
#else
static void *ui_open_library(void) {
#if defined(__APPLE__)
    const char *names[] = {"libSDL3.0.dylib", "libSDL3.dylib", "/opt/homebrew/lib/libSDL3.dylib", NULL};
#else
    const char *names[] = {"libSDL3.so.0", "libSDL3.so", NULL};
#endif
    for (size_t i = 0; names[i] != NULL; ++i) {
        void *lib = dlopen(names[i], RTLD_NOW | RTLD_LOCAL);
        if (lib != NULL) return lib;
    }
    return NULL;
}
static void *ui_symbol(void *library, const char *name) { return dlsym(library, name); }
#endif

#define UI_LOAD(field, symbol) do { \
    *(void **)(&g_sdl.field) = ui_symbol(g_sdl.library, symbol); \
    if (g_sdl.field == NULL) { ui_set_error("SDL3 is missing required rendering symbols"); return false; } \
} while (0)

static bool ui_load_sdl(void) {
    if (g_sdl.attempted) return g_sdl.ready;
    g_sdl.attempted = true;
    g_sdl.library = ui_open_library();
    if (g_sdl.library == NULL) {
        ui_set_error("SDL3 runtime was not found");
        return false;
    }
    UI_LOAD(Init, "SDL_Init");
    UI_LOAD(Quit, "SDL_Quit");
    UI_LOAD(CreateWindowAndRenderer, "SDL_CreateWindowAndRenderer");
    UI_LOAD(DestroyRenderer, "SDL_DestroyRenderer");
    UI_LOAD(DestroyWindow, "SDL_DestroyWindow");
    UI_LOAD(PollEvent, "SDL_PollEvent");
    UI_LOAD(SetRenderDrawColor, "SDL_SetRenderDrawColor");
    UI_LOAD(RenderClear, "SDL_RenderClear");
    UI_LOAD(RenderFillRect, "SDL_RenderFillRect");
    UI_LOAD(RenderRect, "SDL_RenderRect");
    UI_LOAD(RenderLine, "SDL_RenderLine");
    UI_LOAD(RenderDebugText, "SDL_RenderDebugText");
    UI_LOAD(RenderPresent, "SDL_RenderPresent");
    UI_LOAD(GetError, "SDL_GetError");
    if (!g_sdl.Init(UI_SDL_INIT_VIDEO)) {
        ui_set_error(g_sdl.GetError());
        return false;
    }
    g_sdl.ready = true;
    return true;
}

#undef UI_LOAD

static UiWindow *ui_window(size_t handle) {
    return handle == 0 ? NULL : (UiWindow *)(uintptr_t)handle;
}

static void ui_color(UiWindow *window, uint32_t color) {
    g_sdl.SetRenderDrawColor(window->renderer,
        (uint8_t)(color >> 24), (uint8_t)(color >> 16),
        (uint8_t)(color >> 8), (uint8_t)color);
}

size_t encore_ui_window_create(encore_str title, uint32_t width, uint32_t height) {
    if (width == 0 || height == 0 || !ui_load_sdl()) return 0;
    UiWindow *state = (UiWindow *)calloc(1, sizeof(UiWindow));
    char *name = ui_to_cstr(title);
    if (state == NULL || name == NULL) {
        free(state); free(name); ui_set_error("Unable to allocate UI window"); return 0;
    }
    bool created = g_sdl.CreateWindowAndRenderer(name, (int)width, (int)height, 0, &state->window, &state->renderer);
    free(name);
    if (!created) {
        ui_set_error(g_sdl.GetError()); free(state); return 0;
    }
    state->open = true;
    g_window_count += 1;
    return (size_t)(uintptr_t)state;
}

bool encore_ui_window_destroy(size_t handle) {
    UiWindow *state = ui_window(handle);
    if (state == NULL) return false;
    if (state->renderer != NULL) g_sdl.DestroyRenderer(state->renderer);
    if (state->window != NULL) g_sdl.DestroyWindow(state->window);
    free(state);
    if (g_window_count > 0) g_window_count -= 1;
    if (g_window_count == 0 && g_sdl.ready) { g_sdl.Quit(); g_sdl.ready = false; g_sdl.attempted = false; }
    return true;
}

bool encore_ui_window_open(size_t handle) {
    UiWindow *state = ui_window(handle);
    return state != NULL && state->open;
}

uint32_t encore_ui_window_poll(size_t handle) {
    UiWindow *state = ui_window(handle);
    if (state == NULL || !state->open) return UI_EVENT_CLOSE;
    state->event_kind = UI_EVENT_NONE;
    state->wheel_x = 0.0f;
    state->wheel_y = 0.0f;
    UiSdlEvent event;
    while (g_sdl.PollEvent(&event)) {
        if (event.type == UI_SDL_EVENT_QUIT || event.type == UI_SDL_EVENT_WINDOW_CLOSE) {
            state->open = false;
            state->event_kind = UI_EVENT_CLOSE;
        } else if (event.type == UI_SDL_EVENT_KEY_DOWN || event.type == UI_SDL_EVENT_KEY_UP) {
            UiSdlKeyboardEvent *key = (UiSdlKeyboardEvent *)&event;
            state->event_kind = event.type == UI_SDL_EVENT_KEY_DOWN ? UI_EVENT_KEY_DOWN : UI_EVENT_KEY_UP;
            state->event_key = key->key;
        } else if (event.type == UI_SDL_EVENT_MOUSE_MOTION) {
            UiSdlMouseMotionEvent *motion = (UiSdlMouseMotionEvent *)&event;
            state->event_kind = UI_EVENT_POINTER_MOVE;
            state->event_x = motion->x;
            state->event_y = motion->y;
        } else if (event.type == UI_SDL_EVENT_MOUSE_BUTTON_DOWN || event.type == UI_SDL_EVENT_MOUSE_BUTTON_UP) {
            UiSdlMouseButtonEvent *button = (UiSdlMouseButtonEvent *)&event;
            state->event_kind = event.type == UI_SDL_EVENT_MOUSE_BUTTON_DOWN ? UI_EVENT_POINTER_DOWN : UI_EVENT_POINTER_UP;
            state->event_x = button->x;
            state->event_y = button->y;
            state->event_key = button->button;
        } else if (event.type == UI_SDL_EVENT_MOUSE_WHEEL) {
            UiSdlMouseWheelEvent *wheel = (UiSdlMouseWheelEvent *)&event;
            state->event_kind = UI_EVENT_SCROLL;
            state->event_x = wheel->mouse_x;
            state->event_y = wheel->mouse_y;
            state->wheel_x = wheel->x;
            state->wheel_y = wheel->y;
        }
    }
    return state->event_kind;
}

float encore_ui_event_x(size_t handle) { UiWindow *s = ui_window(handle); return s == NULL ? 0.0f : s->event_x; }
float encore_ui_event_y(size_t handle) { UiWindow *s = ui_window(handle); return s == NULL ? 0.0f : s->event_y; }
uint32_t encore_ui_event_key(size_t handle) { UiWindow *s = ui_window(handle); return s == NULL ? 0 : s->event_key; }
float encore_ui_event_wheel_x(size_t handle) { UiWindow *s = ui_window(handle); return s == NULL ? 0.0f : s->wheel_x; }
float encore_ui_event_wheel_y(size_t handle) { UiWindow *s = ui_window(handle); return s == NULL ? 0.0f : s->wheel_y; }

bool encore_ui_frame_begin(size_t handle, uint32_t color) {
    UiWindow *state = ui_window(handle); if (state == NULL || !state->open) return false;
    ui_color(state, color); return g_sdl.RenderClear(state->renderer);
}
bool encore_ui_fill_rect(size_t handle, float x, float y, float width, float height, uint32_t color) {
    UiWindow *state = ui_window(handle); if (state == NULL || !state->open) return false;
    if ((color & 0xffu) == 0) return true;
    UiSdlFRect rect = {x, y, width, height}; ui_color(state, color); return g_sdl.RenderFillRect(state->renderer, &rect);
}
bool encore_ui_stroke_rect(size_t handle, float x, float y, float width, float height, uint32_t color) {
    UiWindow *state = ui_window(handle); if (state == NULL || !state->open) return false;
    UiSdlFRect rect = {x, y, width, height}; ui_color(state, color); return g_sdl.RenderRect(state->renderer, &rect);
}
bool encore_ui_line(size_t handle, float x0, float y0, float x1, float y1, uint32_t color) {
    UiWindow *state = ui_window(handle); if (state == NULL || !state->open) return false;
    ui_color(state, color); return g_sdl.RenderLine(state->renderer, x0, y0, x1, y1);
}
bool encore_ui_text(size_t handle, float x, float y, encore_str value, uint32_t color) {
    UiWindow *state = ui_window(handle); if (state == NULL || !state->open) return false;
    char *text = ui_to_cstr(value); if (text == NULL) return false;
    ui_color(state, color); bool result = g_sdl.RenderDebugText(state->renderer, x, y, text); free(text); return result;
}
bool encore_ui_frame_end(size_t handle) {
    UiWindow *state = ui_window(handle); return state != NULL && state->open && g_sdl.RenderPresent(state->renderer);
}
encore_str encore_ui_backend_name(void) { return ui_string(g_sdl.ready ? "SDL3" : "unavailable"); }
encore_str encore_ui_backend_error(void) { return ui_string(g_error); }
