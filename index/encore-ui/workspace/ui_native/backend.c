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
#include <signal.h>
#endif

typedef struct { size_t ref_count; size_t len; char data[]; } encore_str_object;
typedef struct { encore_str_object *object; } encore_str;
extern void *encore_str_from_cstr(const char *value);

typedef struct UiSdlWindow UiSdlWindow;
typedef struct UiSdlRenderer UiSdlRenderer;
typedef struct UiSdlTexture UiSdlTexture;
typedef struct UiSdlSurface {
    uint32_t flags;
    uint32_t format;
    int width;
    int height;
    int pitch;
    void *pixels;
    int refcount;
    void *reserved;
} UiSdlSurface;
typedef struct UiTtfFont UiTtfFont;
typedef struct { float x, y, w, h; } UiSdlFRect;
typedef struct { float x, y; } UiSdlFPoint;
typedef struct { int x, y, w, h; } UiSdlRect;
typedef struct { uint8_t r, g, b, a; } UiSdlColor;
typedef struct { float r, g, b, a; } UiSdlFColor;
typedef struct { UiSdlFPoint position; UiSdlFColor color; UiSdlFPoint tex_coord; } UiSdlVertex;

typedef union {
    uint32_t type;
    uint8_t padding[128];
} UiSdlEvent;

typedef struct {
    UiTtfFont *font;
    float size;
    uint32_t weight;
    size_t face;
    uint64_t used_at;
} UiFontVariant;

typedef struct {
    char *family;
    char *path;
} UiFontFace;

typedef struct {
    UiSdlTexture *texture;
    char *text;
    size_t face;
    float font_size;
    uint32_t font_weight;
    uint32_t color;
    int wrap_width;
    int width;
    int height;
    size_t bytes;
    uint64_t used_at;
} UiTextCacheEntry;

typedef struct {
    uint32_t type;
    uint32_t reserved;
    uint64_t timestamp;
    uint32_t window_id;
    uint32_t which;
    uint32_t state;
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

typedef struct {
    uint32_t type;
    uint32_t reserved;
    uint64_t timestamp;
    uint32_t window_id;
    const char *text;
} UiSdlTextInputEvent;

typedef struct {
    uint32_t type;
    uint32_t reserved;
    uint64_t timestamp;
    uint32_t window_id;
    int32_t data1;
    int32_t data2;
} UiSdlWindowEvent;

enum {
    UI_SDL_INIT_VIDEO = 0x00000020u,
    UI_SDL_EVENT_QUIT = 0x100,
    UI_SDL_EVENT_WINDOW_CLOSE = 0x210,
    UI_SDL_EVENT_WINDOW_EXPOSED = 0x204,
    UI_SDL_EVENT_WINDOW_RESIZED = 0x206,
    UI_SDL_EVENT_WINDOW_PIXEL_SIZE_CHANGED = 0x207,
    UI_SDL_EVENT_KEY_DOWN = 0x300,
    UI_SDL_EVENT_KEY_UP = 0x301,
    UI_SDL_EVENT_TEXT_INPUT = 0x303,
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
    UI_EVENT_SCROLL = 7,
    UI_EVENT_TEXT_INPUT = 8,
    UI_EVENT_RESIZE = 9
};

typedef struct {
    void *library;
    bool attempted;
    bool ready;
    bool (*Init)(uint32_t);
    void (*Quit)(void);
    UiSdlWindow *(*CreateWindow)(const char *, int, int, uint64_t);
    bool (*CreateWindowAndRenderer)(const char *, int, int, uint64_t, UiSdlWindow **, UiSdlRenderer **);
    UiSdlSurface *(*CreateSurface)(int, int, uint32_t);
    UiSdlRenderer *(*CreateSoftwareRenderer)(UiSdlSurface *);
    float (*GetWindowPixelDensity)(UiSdlWindow *);
    bool (*GetWindowSizeInPixels)(UiSdlWindow *, int *, int *);
    void (*DestroyRenderer)(UiSdlRenderer *);
    void (*DestroyWindow)(UiSdlWindow *);
    bool (*PollEvent)(UiSdlEvent *);
    bool (*StartTextInput)(UiSdlWindow *);
    bool (*StopTextInput)(UiSdlWindow *);
    bool (*SetClipboardText)(const char *);
    char *(*GetClipboardText)(void);
    void (*Free)(void *);
    bool (*SetRenderDrawColor)(UiSdlRenderer *, uint8_t, uint8_t, uint8_t, uint8_t);
    bool (*SetRenderDrawBlendMode)(UiSdlRenderer *, uint32_t);
    bool (*SetRenderClipRect)(UiSdlRenderer *, const UiSdlRect *);
    bool (*SetRenderScale)(UiSdlRenderer *, float, float);
    bool (*RenderClear)(UiSdlRenderer *);
    bool (*RenderFillRect)(UiSdlRenderer *, const UiSdlFRect *);
    bool (*RenderRect)(UiSdlRenderer *, const UiSdlFRect *);
    bool (*RenderLine)(UiSdlRenderer *, float, float, float, float);
    bool (*RenderGeometry)(UiSdlRenderer *, UiSdlTexture *, const UiSdlVertex *, int, const int *, int);
    bool (*RenderDebugText)(UiSdlRenderer *, float, float, const char *);
    UiSdlTexture *(*CreateTextureFromSurface)(UiSdlRenderer *, UiSdlSurface *);
    UiSdlTexture *(*CreateTexture)(UiSdlRenderer *, uint32_t, int, int, int);
    bool (*UpdateTexture)(UiSdlTexture *, const UiSdlRect *, const void *, int);
    bool (*SetRenderTarget)(UiSdlRenderer *, UiSdlTexture *);
    bool (*RenderTexture)(UiSdlRenderer *, UiSdlTexture *, const UiSdlFRect *, const UiSdlFRect *);
    void (*DestroyTexture)(UiSdlTexture *);
    void (*DestroySurface)(UiSdlSurface *);
    bool (*RenderPresent)(UiSdlRenderer *);
    const char *(*GetError)(void);
} UiSdlApi;

typedef struct {
    void *library;
    bool attempted;
    bool ready;
    bool (*Init)(void);
    void (*Quit)(void);
    UiTtfFont *(*OpenFont)(const char *, float);
    void (*CloseFont)(UiTtfFont *);
    void (*SetFontStyle)(UiTtfFont *, uint32_t);
    bool (*SetFontSize)(UiTtfFont *, float);
    bool (*GetStringSize)(UiTtfFont *, const char *, size_t, int *, int *);
    bool (*GetStringSizeWrapped)(UiTtfFont *, const char *, size_t, int, int *, int *);
    bool (*MeasureString)(UiTtfFont *, const char *, size_t, int, int *, size_t *);
    UiSdlSurface *(*RenderTextBlended)(UiTtfFont *, const char *, size_t, UiSdlColor);
    UiSdlSurface *(*RenderTextBlendedWrapped)(UiTtfFont *, const char *, size_t, UiSdlColor, int);
} UiTtfApi;

typedef struct {
    UiSdlWindow *window;
    UiSdlRenderer *renderer;
    bool open;
    bool text_input_started;
    uint32_t event_kind;
    float event_x;
    float event_y;
    float wheel_x;
    float wheel_y;
    uint32_t event_key;
    uint32_t event_modifiers;
    char event_text[32];
    uint32_t width;
    uint32_t height;
    float pixel_density;
    UiTtfFont *font;
    float font_size;
    uint32_t font_weight;
    UiFontFace font_faces[32];
    size_t font_face_count;
    size_t current_face;
    UiFontVariant font_variants[32];
    size_t font_variant_count;
    uint64_t font_tick;
    UiTextCacheEntry text_cache[128];
    size_t text_cache_count;
    size_t text_cache_bytes;
    uint64_t text_cache_tick;
    UiSdlFPoint vector_path[4096];
    size_t vector_path_count;
    UiSdlTexture *pixels_texture;
    uint32_t pixels_width;
    uint32_t pixels_height;
    UiSdlTexture *layout_texture;
    uint32_t layout_width;
    uint32_t layout_height;
    UiSdlSurface *software_surface;
    bool external_presentation;
} UiWindow;

static UiSdlApi g_sdl;
static UiTtfApi g_ttf;
static char g_error[256];
static size_t g_window_count;
#if !defined(_WIN32)
static volatile sig_atomic_t g_terminate_requested;
static void ui_termination_signal(int signal_number) {
    (void)signal_number;
    g_terminate_requested = 1;
}
#endif

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

static char *ui_copy_cstr(const char *value) {
    size_t length = strlen(value);
    char *result = (char *)malloc(length + 1);
    if (result != NULL) memcpy(result, value, length + 1);
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
static void *ui_open_ttf_library(void) {
    const char *names[] = {"SDL3_ttf.dll", NULL};
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
static void *ui_open_ttf_library(void) {
#if defined(__APPLE__)
    const char *names[] = {"libSDL3_ttf.0.dylib", "libSDL3_ttf.dylib", "/opt/homebrew/lib/libSDL3_ttf.dylib", NULL};
#else
    const char *names[] = {"libSDL3_ttf.so.0", "libSDL3_ttf.so", NULL};
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
#if !defined(_WIN32) && !defined(__APPLE__)
    if (getenv("SDL_VIDEODRIVER") == NULL && getenv("WAYLAND_DISPLAY") != NULL) {
        setenv("SDL_VIDEODRIVER", "wayland", 0);
    }
#endif
    g_sdl.library = ui_open_library();
    if (g_sdl.library == NULL) {
        ui_set_error("SDL3 runtime was not found");
        return false;
    }
    UI_LOAD(Init, "SDL_Init");
    UI_LOAD(Quit, "SDL_Quit");
    UI_LOAD(CreateWindow, "SDL_CreateWindow");
    UI_LOAD(CreateWindowAndRenderer, "SDL_CreateWindowAndRenderer");
    UI_LOAD(CreateSurface, "SDL_CreateSurface");
    UI_LOAD(CreateSoftwareRenderer, "SDL_CreateSoftwareRenderer");
    UI_LOAD(GetWindowPixelDensity, "SDL_GetWindowPixelDensity");
    UI_LOAD(GetWindowSizeInPixels, "SDL_GetWindowSizeInPixels");
    UI_LOAD(DestroyRenderer, "SDL_DestroyRenderer");
    UI_LOAD(DestroyWindow, "SDL_DestroyWindow");
    UI_LOAD(PollEvent, "SDL_PollEvent");
    UI_LOAD(StartTextInput, "SDL_StartTextInput");
    UI_LOAD(StopTextInput, "SDL_StopTextInput");
    UI_LOAD(SetClipboardText, "SDL_SetClipboardText");
    UI_LOAD(GetClipboardText, "SDL_GetClipboardText");
    UI_LOAD(Free, "SDL_free");
    UI_LOAD(SetRenderDrawColor, "SDL_SetRenderDrawColor");
    UI_LOAD(SetRenderDrawBlendMode, "SDL_SetRenderDrawBlendMode");
    UI_LOAD(SetRenderClipRect, "SDL_SetRenderClipRect");
    UI_LOAD(SetRenderScale, "SDL_SetRenderScale");
    UI_LOAD(RenderClear, "SDL_RenderClear");
    UI_LOAD(RenderFillRect, "SDL_RenderFillRect");
    UI_LOAD(RenderRect, "SDL_RenderRect");
    UI_LOAD(RenderLine, "SDL_RenderLine");
    UI_LOAD(RenderGeometry, "SDL_RenderGeometry");
    UI_LOAD(RenderDebugText, "SDL_RenderDebugText");
    UI_LOAD(CreateTextureFromSurface, "SDL_CreateTextureFromSurface");
    UI_LOAD(CreateTexture, "SDL_CreateTexture");
    UI_LOAD(UpdateTexture, "SDL_UpdateTexture");
    UI_LOAD(SetRenderTarget, "SDL_SetRenderTarget");
    UI_LOAD(RenderTexture, "SDL_RenderTexture");
    UI_LOAD(DestroyTexture, "SDL_DestroyTexture");
    UI_LOAD(DestroySurface, "SDL_DestroySurface");
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

#define UI_TTF_LOAD(field, symbol) do { \
    *(void **)(&g_ttf.field) = ui_symbol(g_ttf.library, symbol); \
    if (g_ttf.field == NULL) { ui_set_error("SDL3_ttf is missing required font symbols"); return false; } \
} while (0)

static bool ui_load_ttf(void) {
    if (g_ttf.attempted) return g_ttf.ready;
    g_ttf.attempted = true;
    g_ttf.library = ui_open_ttf_library();
    if (g_ttf.library == NULL) {
        ui_set_error("SDL3_ttf runtime was not found");
        return false;
    }
    UI_TTF_LOAD(Init, "TTF_Init");
    UI_TTF_LOAD(Quit, "TTF_Quit");
    UI_TTF_LOAD(OpenFont, "TTF_OpenFont");
    UI_TTF_LOAD(CloseFont, "TTF_CloseFont");
    UI_TTF_LOAD(SetFontStyle, "TTF_SetFontStyle");
    UI_TTF_LOAD(SetFontSize, "TTF_SetFontSize");
    UI_TTF_LOAD(GetStringSize, "TTF_GetStringSize");
    UI_TTF_LOAD(GetStringSizeWrapped, "TTF_GetStringSizeWrapped");
    UI_TTF_LOAD(MeasureString, "TTF_MeasureString");
    UI_TTF_LOAD(RenderTextBlended, "TTF_RenderText_Blended");
    UI_TTF_LOAD(RenderTextBlendedWrapped, "TTF_RenderText_Blended_Wrapped");
    if (!g_ttf.Init()) {
        ui_set_error(g_sdl.GetError());
        return false;
    }
    g_ttf.ready = true;
    return true;
}

#undef UI_TTF_LOAD

static UiWindow *ui_window(size_t handle) {
    return handle == 0 ? NULL : (UiWindow *)(uintptr_t)handle;
}

static bool ui_select_font(UiWindow *state, size_t face, float size, uint32_t weight);

static void ui_clear_text_cache(UiWindow *state) {
    if (state == NULL) return;
    for (size_t i = 0; i < state->text_cache_count; ++i) {
        if (state->text_cache[i].texture != NULL) g_sdl.DestroyTexture(state->text_cache[i].texture);
        free(state->text_cache[i].text);
    }
    state->text_cache_count = 0;
    state->text_cache_bytes = 0;
    state->text_cache_tick = 0;
}

static bool ui_resize_software_surface(UiWindow *state) {
    if (state == NULL || !state->external_presentation || state->window == NULL) return true;
    int width = 0, height = 0;
    /* Wayland compositors may temporarily report no extent while a window is
       minimized, moved between tags, or passing through a resize animation. */
    if (!g_sdl.GetWindowSizeInPixels(state->window, &width, &height) || width <= 0 || height <= 0) return true;
    state->width = (uint32_t)((float)width / state->pixel_density);
    state->height = (uint32_t)((float)height / state->pixel_density);
    if (state->software_surface != NULL && state->software_surface->width == width &&
        state->software_surface->height == height) return true;
    ui_clear_text_cache(state);
    if (state->pixels_texture != NULL) { g_sdl.DestroyTexture(state->pixels_texture); state->pixels_texture = NULL; }
    if (state->layout_texture != NULL) { g_sdl.DestroyTexture(state->layout_texture); state->layout_texture = NULL; }
    if (state->renderer != NULL) g_sdl.DestroyRenderer(state->renderer);
    if (state->software_surface != NULL) g_sdl.DestroySurface(state->software_surface);
    state->renderer = NULL;
    state->software_surface = g_sdl.CreateSurface(width, height, 0x16362004u);
    state->renderer = state->software_surface == NULL ? NULL : g_sdl.CreateSoftwareRenderer(state->software_surface);
    if (state->renderer == NULL || !g_sdl.SetRenderDrawBlendMode(state->renderer, 1u) ||
        !g_sdl.SetRenderScale(state->renderer, state->pixel_density, state->pixel_density)) {
        ui_set_error(g_sdl.GetError()); return false;
    }
    state->layout_width = 0;
    state->layout_height = 0;
    return true;
}

static void ui_remove_text_cache_entry(UiWindow *state, size_t index) {
    if (state == NULL || index >= state->text_cache_count) return;
    UiTextCacheEntry *entry = &state->text_cache[index];
    if (entry->texture != NULL) g_sdl.DestroyTexture(entry->texture);
    free(entry->text);
    if (state->text_cache_bytes >= entry->bytes) state->text_cache_bytes -= entry->bytes;
    size_t last = state->text_cache_count - 1;
    if (index != last) state->text_cache[index] = state->text_cache[last];
    --state->text_cache_count;
}

static size_t ui_oldest_text_cache_entry(UiWindow *state) {
    size_t oldest = 0;
    for (size_t i = 1; i < state->text_cache_count; ++i) {
        if (state->text_cache[i].used_at < state->text_cache[oldest].used_at) oldest = i;
    }
    return oldest;
}

static void ui_clear_fonts(UiWindow *state) {
    if (state == NULL) return;
    ui_clear_text_cache(state);
    if (g_ttf.ready) {
        for (size_t i = 0; i < state->font_variant_count; ++i) {
            if (state->font_variants[i].font != NULL) g_ttf.CloseFont(state->font_variants[i].font);
        }
    }
    for (size_t i = 0; i < state->font_face_count; ++i) {
        free(state->font_faces[i].family);
        free(state->font_faces[i].path);
    }
    state->font_face_count = 0;
    state->current_face = 0;
    state->font = NULL;
    state->font_size = 0.0f;
    state->font_weight = 0;
    state->font_variant_count = 0;
    state->font_tick = 0;
}

static void ui_clear_font_variants(UiWindow *state) {
    if (state == NULL) return;
    ui_clear_text_cache(state);
    if (g_ttf.ready) {
        for (size_t i = 0; i < state->font_variant_count; ++i) {
            if (state->font_variants[i].font != NULL) g_ttf.CloseFont(state->font_variants[i].font);
        }
    }
    state->font = NULL;
    state->font_size = 0.0f;
    state->font_weight = 0;
    state->font_variant_count = 0;
    state->font_tick = 0;
}

static void ui_refresh_pixel_density(UiWindow *state) {
    if (state == NULL || state->window == NULL || state->renderer == NULL) return;
    float density = g_sdl.GetWindowPixelDensity(state->window);
    if (density < 1.0f) density = 1.0f;
    if (state->pixel_density != density && state->pixel_density > 0.0f) {
        size_t face = state->current_face;
        float size = state->font_size;
        uint32_t weight = state->font_weight;
        ui_clear_font_variants(state);
        state->pixel_density = density;
        if (size > 0.0f && face < state->font_face_count) ui_select_font(state, face, size, weight);
    }
    state->pixel_density = density;
    g_sdl.SetRenderScale(state->renderer, density, density);
}

static bool ui_color(UiWindow *window, uint32_t color) {
    return g_sdl.SetRenderDrawColor(window->renderer,
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
    bool created = g_sdl.CreateWindowAndRenderer(name, (int)width, (int)height, 0x20u | 0x2000u, &state->window, &state->renderer);
    free(name);
    if (!created) {
        ui_set_error(g_sdl.GetError()); free(state); return 0;
    }
    if (!g_sdl.SetRenderDrawBlendMode(state->renderer, 1u) || !g_sdl.StartTextInput(state->window)) {
        ui_set_error(g_sdl.GetError());
        if (state->renderer != NULL) g_sdl.DestroyRenderer(state->renderer);
        if (state->window != NULL) g_sdl.DestroyWindow(state->window);
        free(state);
        return 0;
    }
    state->text_input_started = true;
    state->open = true;
    state->width = width;
    state->height = height;
    ui_refresh_pixel_density(state);
    g_window_count += 1;
#if !defined(_WIN32)
    if (g_window_count == 1) {
        g_terminate_requested = 0;
        signal(SIGTERM, ui_termination_signal);
        signal(SIGINT, ui_termination_signal);
    }
#endif
    return (size_t)(uintptr_t)state;
}

size_t encore_ui_gpu_window_create(encore_str title, uint32_t width, uint32_t height) {
    if (width == 0 || height == 0 || !ui_load_sdl()) return 0;
    UiWindow *state = (UiWindow *)calloc(1, sizeof(UiWindow));
    char *name = ui_to_cstr(title);
    if (state == NULL || name == NULL) {
        free(state); free(name); ui_set_error("Unable to allocate GPU UI window"); return 0;
    }
    state->window = g_sdl.CreateWindow(name, (int)width, (int)height,
        0x10000000ull | 0x20ull | 0x2000ull);
    free(name);
    if (state->window == NULL) { ui_set_error(g_sdl.GetError()); free(state); return 0; }
    state->pixel_density = g_sdl.GetWindowPixelDensity(state->window);
    if (state->pixel_density < 1.0f) state->pixel_density = 1.0f;
    int pixel_width = (int)((float)width * state->pixel_density);
    int pixel_height = (int)((float)height * state->pixel_density);
    state->software_surface = g_sdl.CreateSurface(pixel_width, pixel_height, 0x16362004u);
    state->renderer = state->software_surface == NULL ? NULL : g_sdl.CreateSoftwareRenderer(state->software_surface);
    if (state->renderer == NULL || !g_sdl.SetRenderDrawBlendMode(state->renderer, 1u) ||
        !g_sdl.SetRenderScale(state->renderer, state->pixel_density, state->pixel_density) ||
        !g_sdl.StartTextInput(state->window)) {
        ui_set_error(g_sdl.GetError());
        if (state->renderer != NULL) g_sdl.DestroyRenderer(state->renderer);
        if (state->software_surface != NULL) g_sdl.DestroySurface(state->software_surface);
        g_sdl.DestroyWindow(state->window); free(state); return 0;
    }
    state->external_presentation = true;
    state->text_input_started = true;
    state->open = true;
    state->width = width;
    state->height = height;
    g_window_count += 1;
#if !defined(_WIN32)
    if (g_window_count == 1) {
        g_terminate_requested = 0;
        signal(SIGTERM, ui_termination_signal);
        signal(SIGINT, ui_termination_signal);
    }
#endif
    return (size_t)(uintptr_t)state;
}

bool encore_ui_window_destroy(size_t handle) {
    UiWindow *state = ui_window(handle);
    if (state == NULL) return false;
    if (state->window != NULL && state->text_input_started) g_sdl.StopTextInput(state->window);
    ui_clear_fonts(state);
    if (state->pixels_texture != NULL) g_sdl.DestroyTexture(state->pixels_texture);
    if (state->layout_texture != NULL) g_sdl.DestroyTexture(state->layout_texture);
    if (state->renderer != NULL) g_sdl.DestroyRenderer(state->renderer);
    if (state->software_surface != NULL) g_sdl.DestroySurface(state->software_surface);
    if (state->window != NULL) g_sdl.DestroyWindow(state->window);
    free(state);
    if (g_window_count > 0) g_window_count -= 1;
    if (g_window_count == 0) {
        if (g_ttf.ready) { g_ttf.Quit(); g_ttf.ready = false; g_ttf.attempted = false; }
        if (g_sdl.ready) { g_sdl.Quit(); g_sdl.ready = false; g_sdl.attempted = false; }
    }
    return true;
}

bool encore_ui_window_open(size_t handle) {
    UiWindow *state = ui_window(handle);
    return state != NULL && state->open;
}

uint32_t encore_ui_window_poll(size_t handle) {
    UiWindow *state = ui_window(handle);
    if (state == NULL || !state->open) return UI_EVENT_CLOSE;
#if !defined(_WIN32)
    if (g_terminate_requested) {
        state->open = false;
        state->event_kind = UI_EVENT_CLOSE;
        return state->event_kind;
    }
#endif
    int previous_surface_width = state->software_surface == NULL ? 0 : state->software_surface->width;
    int previous_surface_height = state->software_surface == NULL ? 0 : state->software_surface->height;
    if (!ui_resize_software_surface(state)) {
        state->open = false; state->event_kind = UI_EVENT_CLOSE; return state->event_kind;
    }
    bool surface_resized = state->software_surface != NULL &&
        (state->software_surface->width != previous_surface_width ||
         state->software_surface->height != previous_surface_height);
    state->event_kind = UI_EVENT_NONE;
    state->event_key = 0;
    state->event_modifiers = 0;
    state->event_text[0] = '\0';
    state->wheel_x = 0.0f;
    state->wheel_y = 0.0f;
    UiSdlEvent event;
    bool had_motion = false;
    bool had_resize = surface_resized;
    while (g_sdl.PollEvent(&event)) {
        if (event.type == UI_SDL_EVENT_QUIT || event.type == UI_SDL_EVENT_WINDOW_CLOSE) {
            state->event_kind = UI_EVENT_CLOSE;
            return state->event_kind;
        } else if (event.type == UI_SDL_EVENT_WINDOW_EXPOSED) {
            state->event_kind = UI_EVENT_RESIZE;
            had_resize = true;
        } else if (event.type == UI_SDL_EVENT_WINDOW_RESIZED) {
            UiSdlWindowEvent *window = (UiSdlWindowEvent *)&event;
            if (window->data1 > 0 && window->data2 > 0) {
                state->width = (uint32_t)window->data1;
                state->height = (uint32_t)window->data2;
                state->event_kind = UI_EVENT_RESIZE;
                had_resize = true;
            }
        } else if (event.type == UI_SDL_EVENT_WINDOW_PIXEL_SIZE_CHANGED) {
            ui_refresh_pixel_density(state);
            state->event_kind = UI_EVENT_RESIZE;
            had_resize = true;
        } else if (event.type == UI_SDL_EVENT_KEY_DOWN || event.type == UI_SDL_EVENT_KEY_UP) {
            UiSdlKeyboardEvent *key = (UiSdlKeyboardEvent *)&event;
            state->event_kind = event.type == UI_SDL_EVENT_KEY_DOWN ? UI_EVENT_KEY_DOWN : UI_EVENT_KEY_UP;
            state->event_key = key->key;
            state->event_modifiers = key->mod;
            return state->event_kind;
        } else if (event.type == UI_SDL_EVENT_TEXT_INPUT) {
            UiSdlTextInputEvent *input = (UiSdlTextInputEvent *)&event;
            if (input->text == NULL) { state->event_text[0] = '\0'; }
            else { strncpy(state->event_text, input->text, sizeof(state->event_text) - 1); }
            state->event_text[sizeof(state->event_text) - 1] = '\0';
            state->event_kind = UI_EVENT_TEXT_INPUT;
            return state->event_kind;
        } else if (event.type == UI_SDL_EVENT_MOUSE_MOTION) {
            UiSdlMouseMotionEvent *motion = (UiSdlMouseMotionEvent *)&event;
            state->event_kind = UI_EVENT_POINTER_MOVE;
            state->event_x = motion->x;
            state->event_y = motion->y;
            had_motion = true;
        } else if (event.type == UI_SDL_EVENT_MOUSE_BUTTON_DOWN || event.type == UI_SDL_EVENT_MOUSE_BUTTON_UP) {
            UiSdlMouseButtonEvent *button = (UiSdlMouseButtonEvent *)&event;
            state->event_kind = event.type == UI_SDL_EVENT_MOUSE_BUTTON_DOWN ? UI_EVENT_POINTER_DOWN : UI_EVENT_POINTER_UP;
            state->event_x = button->x;
            state->event_y = button->y;
            state->event_key = button->button;
            return state->event_kind;
        } else if (event.type == UI_SDL_EVENT_MOUSE_WHEEL) {
            UiSdlMouseWheelEvent *wheel = (UiSdlMouseWheelEvent *)&event;
            state->event_kind = UI_EVENT_SCROLL;
            state->event_x = wheel->mouse_x;
            state->event_y = wheel->mouse_y;
            state->wheel_x = wheel->x;
            state->wheel_y = wheel->y;
            return state->event_kind;
        }
    }
    if (had_resize) {
        if (!ui_resize_software_surface(state)) state->open = false;
        return state->open ? UI_EVENT_RESIZE : UI_EVENT_CLOSE;
    }
    if (had_motion) { return UI_EVENT_POINTER_MOVE; }
    return state->event_kind;
}

float encore_ui_event_x(size_t handle) { UiWindow *s = ui_window(handle); return s == NULL ? 0.0f : s->event_x; }
float encore_ui_event_y(size_t handle) { UiWindow *s = ui_window(handle); return s == NULL ? 0.0f : s->event_y; }
uint32_t encore_ui_event_key(size_t handle) { UiWindow *s = ui_window(handle); return s == NULL ? 0 : s->event_key; }
uint32_t encore_ui_event_modifiers(size_t handle) { UiWindow *s = ui_window(handle); return s == NULL ? 0 : s->event_modifiers; }
encore_str encore_ui_event_text(size_t handle) { UiWindow *s = ui_window(handle); return ui_string(s == NULL ? "" : s->event_text); }
uint32_t encore_ui_window_width(size_t handle) { UiWindow *s = ui_window(handle); return s == NULL ? 0 : s->width; }
uint32_t encore_ui_window_height(size_t handle) { UiWindow *s = ui_window(handle); return s == NULL ? 0 : s->height; }
float encore_ui_window_pixel_density(size_t handle) { UiWindow *s = ui_window(handle); return s == NULL || s->pixel_density <= 0.0f ? 1.0f : s->pixel_density; }
size_t encore_ui_window_platform_handle(size_t handle) { UiWindow *s = ui_window(handle); return s == NULL ? 0 : (size_t)(uintptr_t)s->window; }
size_t encore_ui_window_surface_pixels(size_t handle) { UiWindow *s = ui_window(handle); return s == NULL || s->software_surface == NULL ? 0 : (size_t)(uintptr_t)s->software_surface->pixels; }
uint32_t encore_ui_window_surface_width(size_t handle) { UiWindow *s = ui_window(handle); return s == NULL || s->software_surface == NULL ? 0 : (uint32_t)s->software_surface->width; }
uint32_t encore_ui_window_surface_height(size_t handle) { UiWindow *s = ui_window(handle); return s == NULL || s->software_surface == NULL ? 0 : (uint32_t)s->software_surface->height; }
uint32_t encore_ui_window_surface_pitch(size_t handle) { UiWindow *s = ui_window(handle); return s == NULL || s->software_surface == NULL ? 0 : (uint32_t)s->software_surface->pitch; }
float encore_ui_event_wheel_x(size_t handle) { UiWindow *s = ui_window(handle); return s == NULL ? 0.0f : s->wheel_x; }
float encore_ui_event_wheel_y(size_t handle) { UiWindow *s = ui_window(handle); return s == NULL ? 0.0f : s->wheel_y; }

bool encore_ui_clipboard_set(encore_str value) {
    if (!ui_load_sdl()) return false;
    char *text = ui_to_cstr(value);
    if (text == NULL) return false;
    bool result = g_sdl.SetClipboardText(text);
    free(text);
    return result;
}

encore_str encore_ui_clipboard_text(void) {
    if (!ui_load_sdl()) return ui_string("");
    char *text = g_sdl.GetClipboardText();
    encore_str result = ui_string(text == NULL ? "" : text);
    if (text != NULL) g_sdl.Free(text);
    return result;
}

bool encore_ui_frame_begin(size_t handle, uint32_t color) {
    UiWindow *state = ui_window(handle); if (state == NULL || !state->open) return false;
    g_sdl.SetRenderClipRect(state->renderer, NULL);
    return ui_color(state, color) && g_sdl.RenderClear(state->renderer);
}

bool encore_ui_layout_cache_begin(size_t handle, uint32_t color) {
    UiWindow *state = ui_window(handle);
    if (state == NULL || !state->open || state->renderer == NULL) return false;
    uint32_t width = (uint32_t)((float)state->width * state->pixel_density);
    uint32_t height = (uint32_t)((float)state->height * state->pixel_density);
    if (width == 0 || height == 0) return false;
    if (state->layout_texture == NULL || state->layout_width != width || state->layout_height != height) {
        if (state->layout_texture != NULL) g_sdl.DestroyTexture(state->layout_texture);
        state->layout_texture = g_sdl.CreateTexture(state->renderer, 0x16362004u, 2, (int)width, (int)height);
        state->layout_width = width;
        state->layout_height = height;
    }
    if (state->layout_texture == NULL || !g_sdl.SetRenderTarget(state->renderer, state->layout_texture)) {
        ui_set_error(g_sdl.GetError()); return false;
    }
    g_sdl.SetRenderScale(state->renderer, state->pixel_density, state->pixel_density);
    g_sdl.SetRenderClipRect(state->renderer, NULL);
    return ui_color(state, color) && g_sdl.RenderClear(state->renderer);
}

bool encore_ui_layout_cache_end(size_t handle) {
    UiWindow *state = ui_window(handle);
    if (state == NULL || state->renderer == NULL || !g_sdl.SetRenderTarget(state->renderer, NULL)) return false;
    return g_sdl.SetRenderScale(state->renderer, state->pixel_density, state->pixel_density);
}

bool encore_ui_cached_frame_begin(size_t handle, uint32_t color) {
    UiWindow *state = ui_window(handle);
    if (state == NULL || state->renderer == NULL || state->layout_texture == NULL) return false;
    if (!g_sdl.SetRenderTarget(state->renderer, NULL)) return false;
    g_sdl.SetRenderScale(state->renderer, state->pixel_density, state->pixel_density);
    g_sdl.SetRenderClipRect(state->renderer, NULL);
    if (!ui_color(state, color) || !g_sdl.RenderClear(state->renderer)) return false;
    UiSdlFRect destination = {0.0f, 0.0f, (float)state->width, (float)state->height};
    return g_sdl.RenderTexture(state->renderer, state->layout_texture, NULL, &destination);
}
bool encore_ui_clip_rect(size_t handle, bool enabled, float x, float y, float width, float height) {
    UiWindow *state = ui_window(handle); if (state == NULL || !state->open) return false;
    if (!enabled) return g_sdl.SetRenderClipRect(state->renderer, NULL);
    int left = (int)x;
    int top = (int)y;
    int right = (int)(x + width);
    int bottom = (int)(y + height);
    UiSdlRect rect = {left, top, right > left ? right - left : 0, bottom > top ? bottom - top : 0};
    return g_sdl.SetRenderClipRect(state->renderer, &rect);
}
bool encore_ui_fill_rect(size_t handle, float x, float y, float width, float height, uint32_t color) {
    UiWindow *state = ui_window(handle); if (state == NULL || !state->open) return false;
    if ((color & 0xffu) == 0) return true;
    UiSdlFRect rect = {x, y, width, height}; return ui_color(state, color) && g_sdl.RenderFillRect(state->renderer, &rect);
}
bool encore_ui_stroke_rect(size_t handle, float x, float y, float width, float height, uint32_t color) {
    UiWindow *state = ui_window(handle); if (state == NULL || !state->open) return false;
    UiSdlFRect rect = {x, y, width, height}; return ui_color(state, color) && g_sdl.RenderRect(state->renderer, &rect);
}
bool encore_ui_line(size_t handle, float x0, float y0, float x1, float y1, uint32_t color) {
    UiWindow *state = ui_window(handle); if (state == NULL || !state->open) return false;
    return ui_color(state, color) && g_sdl.RenderLine(state->renderer, x0, y0, x1, y1);
}

static float ui_sqrt(float value) {
    if (value <= 0.0f) return 0.0f;
    float result = value > 1.0f ? value : 1.0f;
    for (int i = 0; i < 8; ++i) result = (result + value / result) * 0.5f;
    return result;
}

static UiSdlFColor ui_float_color(uint32_t color, float alpha_scale) {
    UiSdlFColor result = {
        (float)((color >> 24) & 0xffu) / 255.0f,
        (float)((color >> 16) & 0xffu) / 255.0f,
        (float)((color >> 8) & 0xffu) / 255.0f,
        ((float)(color & 0xffu) / 255.0f) * alpha_scale
    };
    return result;
}

bool encore_ui_circle(size_t handle, float cx, float cy, float radius, uint32_t color, bool filled);

bool encore_ui_vector_line(size_t handle, float x0, float y0, float x1, float y1, float width, uint32_t color) {
    UiWindow *state = ui_window(handle);
    if (state == NULL || !state->open || width <= 0.0f || (color & 0xffu) == 0) return false;
    float dx = x1 - x0;
    float dy = y1 - y0;
    float length = ui_sqrt(dx * dx + dy * dy);
    if (length <= 0.0001f) return true;
    float px = -dy / length;
    float py = dx / length;
    float inner = width * 0.5f;
    if (inner < 0.5f) inner = 0.5f;
    float outer = inner + 1.0f;
    UiSdlFColor solid = ui_float_color(color, 1.0f);
    UiSdlFColor clear = ui_float_color(color, 0.0f);
    UiSdlVertex vertices[8] = {
        {{x0 + px * outer, y0 + py * outer}, clear, {0, 0}},
        {{x0 + px * inner, y0 + py * inner}, solid, {0, 0}},
        {{x1 + px * outer, y1 + py * outer}, clear, {0, 0}},
        {{x1 + px * inner, y1 + py * inner}, solid, {0, 0}},
        {{x1 - px * inner, y1 - py * inner}, solid, {0, 0}},
        {{x1 - px * outer, y1 - py * outer}, clear, {0, 0}},
        {{x0 - px * inner, y0 - py * inner}, solid, {0, 0}},
        {{x0 - px * outer, y0 - py * outer}, clear, {0, 0}}
    };
    int indices[18] = {0, 2, 1, 1, 2, 3, 1, 3, 6, 6, 3, 4, 6, 4, 7, 7, 4, 5};
    return g_sdl.RenderGeometry(state->renderer, NULL, vertices, 8, indices, 18);
}

bool encore_ui_vector_path_begin(size_t handle, float x, float y) {
    UiWindow *state = ui_window(handle);
    if (state == NULL || !state->open) return false;
    state->vector_path_count = 1;
    state->vector_path[0] = (UiSdlFPoint){x, y};
    return true;
}

bool encore_ui_vector_path_point(size_t handle, float x, float y) {
    UiWindow *state = ui_window(handle);
    if (state == NULL || !state->open || state->vector_path_count == 0) return false;
    UiSdlFPoint last = state->vector_path[state->vector_path_count - 1];
    if ((x - last.x) * (x - last.x) + (y - last.y) * (y - last.y) < 0.000001f) return true;
    if (state->vector_path_count >= 4096) return false;
    state->vector_path[state->vector_path_count++] = (UiSdlFPoint){x, y};
    return true;
}

static UiSdlFPoint ui_path_normal(UiSdlFPoint a, UiSdlFPoint b) {
    float dx = b.x - a.x, dy = b.y - a.y;
    float length = ui_sqrt(dx * dx + dy * dy);
    return length <= 0.0001f ? (UiSdlFPoint){0.0f, 0.0f} : (UiSdlFPoint){-dy / length, dx / length};
}

/* Continuous stroke expansion follows NanoVG's averaged-normal/miter construction. */
bool encore_ui_vector_path_stroke(size_t handle, float width, uint32_t color, bool closed) {
    UiWindow *state = ui_window(handle);
    if (state == NULL || !state->open || state->vector_path_count < 2 || width <= 0.0f) return false;
    size_t count = state->vector_path_count;
    if (closed && count > 2) {
        UiSdlFPoint first = state->vector_path[0], last = state->vector_path[count - 1];
        if ((first.x-last.x)*(first.x-last.x) + (first.y-last.y)*(first.y-last.y) < 0.000001f) count--;
    }
    if (count < 2) return true;
    UiSdlVertex *vertices = (UiSdlVertex *)malloc(sizeof(UiSdlVertex) * count * 4);
    int segments = closed ? (int)count : (int)count - 1;
    int *indices = (int *)malloc(sizeof(int) * (size_t)segments * 18);
    if (vertices == NULL || indices == NULL) { free(vertices); free(indices); return false; }
    UiSdlFColor solid = ui_float_color(color, 1.0f), clear = ui_float_color(color, 0.0f);
    float inner = width * 0.5f, outer = inner + 1.0f;
    for (size_t i = 0; i < count; ++i) {
        size_t prev = i == 0 ? (closed ? count - 1 : 0) : i - 1;
        size_t next = i + 1 == count ? (closed ? 0 : count - 1) : i + 1;
        UiSdlFPoint n0 = ui_path_normal(state->vector_path[prev], state->vector_path[i]);
        UiSdlFPoint n1 = ui_path_normal(state->vector_path[i], state->vector_path[next]);
        if (!closed && i == 0) n0 = n1;
        if (!closed && i + 1 == count) n1 = n0;
        float mx = (n0.x + n1.x) * 0.5f, my = (n0.y + n1.y) * 0.5f;
        float d = mx * mx + my * my;
        if (d > 0.000001f) {
            float scale = 1.0f / d;
            if (scale > 8.0f) scale = 8.0f;
            mx *= scale; my *= scale;
        } else { mx = n1.x; my = n1.y; }
        UiSdlFPoint p = state->vector_path[i];
        vertices[i*4+0] = (UiSdlVertex){{p.x + mx*outer,p.y + my*outer},clear,{0,0}};
        vertices[i*4+1] = (UiSdlVertex){{p.x + mx*inner,p.y + my*inner},solid,{0,0}};
        vertices[i*4+2] = (UiSdlVertex){{p.x - mx*inner,p.y - my*inner},solid,{0,0}};
        vertices[i*4+3] = (UiSdlVertex){{p.x - mx*outer,p.y - my*outer},clear,{0,0}};
    }
    int at = 0;
    for (int i = 0; i < segments; ++i) {
        int a = i, b = (i + 1) % (int)count;
        int ai=a*4, bi=b*4;
        int strip[18] = {ai,bi,ai+1, ai+1,bi,bi+1, ai+1,bi+1,ai+2, ai+2,bi+1,bi+2, ai+2,bi+2,ai+3, ai+3,bi+2,bi+3};
        for (int j = 0; j < 18; ++j) indices[at++] = strip[j];
    }
    bool result = g_sdl.RenderGeometry(state->renderer, NULL, vertices, (int)(count * 4), indices, at);
    free(vertices); free(indices);
    if (!closed) {
        UiSdlFPoint first = state->vector_path[0], last = state->vector_path[count - 1];
        result = encore_ui_circle(handle, first.x, first.y, inner, color, true) && result;
        result = encore_ui_circle(handle, last.x, last.y, inner, color, true) && result;
    }
    state->vector_path_count = 0;
    return result;
}
static int ui_round_boundary(float x, float y, float width, float height, float radius, UiSdlFPoint *points) {
    static const float axis[9] = {0.0f, 0.1950903f, 0.3826834f, 0.5555702f, 0.7071068f, 0.8314696f, 0.9238795f, 0.9807853f, 1.0f};
    static const float inverse[9] = {1.0f, 0.9807853f, 0.9238795f, 0.8314696f, 0.7071068f, 0.5555702f, 0.3826834f, 0.1950903f, 0.0f};
    float r = radius;
    if (r < 0.0f) r = 0.0f;
    if (r > width * 0.5f) r = width * 0.5f;
    if (r > height * 0.5f) r = height * 0.5f;
    float left = x + r, right = x + width - r, top = y + r, bottom = y + height - r;
    int count = 0;
    for (int i = 0; i < 9; ++i) points[count++] = (UiSdlFPoint){left - r * inverse[i], top - r * axis[i]};
    for (int i = 0; i < 9; ++i) points[count++] = (UiSdlFPoint){right + r * axis[i], top - r * inverse[i]};
    for (int i = 0; i < 9; ++i) points[count++] = (UiSdlFPoint){right + r * inverse[i], bottom + r * axis[i]};
    for (int i = 0; i < 9; ++i) points[count++] = (UiSdlFPoint){left - r * axis[i], bottom + r * inverse[i]};
    return count;
}

static bool ui_fill_rounded_geometry(UiWindow *state, float x, float y, float width, float height, float radius, uint32_t color) {
    UiSdlFPoint inner[36], outer[36];
    int count = ui_round_boundary(x, y, width, height, radius, inner);
    ui_round_boundary(x - 1.0f, y - 1.0f, width + 2.0f, height + 2.0f, radius + 1.0f, outer);
    UiSdlFColor solid = ui_float_color(color, 1.0f);
    UiSdlFColor clear = ui_float_color(color, 0.0f);
    UiSdlVertex vertices[73];
    int indices[324];
    vertices[0] = (UiSdlVertex){{x + width * 0.5f, y + height * 0.5f}, solid, {0, 0}};
    for (int i = 0; i < count; ++i) {
        vertices[1 + i] = (UiSdlVertex){inner[i], solid, {0, 0}};
        vertices[1 + count + i] = (UiSdlVertex){outer[i], clear, {0, 0}};
    }
    int at = 0;
    for (int i = 0; i < count; ++i) {
        int next = (i + 1) % count;
        int inner_i = 1 + i, inner_next = 1 + next;
        int outer_i = 1 + count + i, outer_next = 1 + count + next;
        indices[at++] = 0; indices[at++] = inner_i; indices[at++] = inner_next;
        indices[at++] = inner_i; indices[at++] = outer_i; indices[at++] = inner_next;
        indices[at++] = inner_next; indices[at++] = outer_i; indices[at++] = outer_next;
    }
    return g_sdl.RenderGeometry(state->renderer, NULL, vertices, 1 + count * 2, indices, at);
}

static bool ui_fill_rounded_aa(UiWindow *state, float x, float y, float width, float height, float radius, uint32_t color) {
    float r = radius;
    if (r > width * 0.5f) r = width * 0.5f;
    if (r > height * 0.5f) r = height * 0.5f;
    if (r <= 0.0f || !ui_color(state, color)) return false;
    UiSdlFRect horizontal = {x + r, y, width - r * 2.0f, height};
    UiSdlFRect vertical = {x, y + r, width, height - r * 2.0f};
    bool result = true;
    if (horizontal.w > 0.0f) result = g_sdl.RenderFillRect(state->renderer, &horizontal) && result;
    if (vertical.h > 0.0f) result = g_sdl.RenderFillRect(state->renderer, &vertical) && result;
    result = ui_fill_rounded_geometry(state, x, y, r * 2.0f, r * 2.0f, r, color) && result;
    result = ui_fill_rounded_geometry(state, x + width - r * 2.0f, y, r * 2.0f, r * 2.0f, r, color) && result;
    result = ui_fill_rounded_geometry(state, x + width - r * 2.0f, y + height - r * 2.0f, r * 2.0f, r * 2.0f, r, color) && result;
    result = ui_fill_rounded_geometry(state, x, y + height - r * 2.0f, r * 2.0f, r * 2.0f, r, color) && result;
    return result;
}

static bool ui_stroke_rounded_aa(size_t handle, float x, float y, float width, float height, float radius, uint32_t color) {
    UiSdlFPoint points[36];
    int count = ui_round_boundary(x, y, width, height, radius, points);
    for (int i = 0; i < count; ++i) {
        UiSdlFPoint a = points[i], b = points[(i + 1) % count];
        if (!encore_ui_vector_line(handle, a.x, a.y, b.x, b.y, 1.0f, color)) return false;
    }
    return true;
}

bool encore_ui_circle(size_t handle, float cx, float cy, float radius, uint32_t color, bool filled) {
    UiWindow *state = ui_window(handle); if (state == NULL || !state->open || radius <= 0.0f) return false;
    return filled
        ? ui_fill_rounded_aa(state, cx - radius, cy - radius, radius * 2.0f, radius * 2.0f, radius, color)
        : ui_stroke_rounded_aa(handle, cx - radius, cy - radius, radius * 2.0f, radius * 2.0f, radius, color);
}
bool encore_ui_round_rect(size_t handle, float x, float y, float width, float height, float radius, uint32_t color, bool filled) {
    UiWindow *state = ui_window(handle); if (state == NULL || !state->open || width <= 0.0f || height <= 0.0f) return false;
    float r = radius;
    if (r < 0.0f) r = 0.0f;
    if (r > width / 2.0f) r = width / 2.0f;
    if (r > height / 2.0f) r = height / 2.0f;
    if (r < 1.0f) {
        UiSdlFRect rect = {x, y, width, height}; if (!ui_color(state, color)) return false;
        return filled ? g_sdl.RenderFillRect(state->renderer, &rect) : g_sdl.RenderRect(state->renderer, &rect);
    }
    return filled ? ui_fill_rounded_aa(state, x, y, width, height, r, color)
        : ui_stroke_rounded_aa(handle, x, y, width, height, r, color);
}
static UiSdlTexture *ui_text_texture(UiWindow *state, const char *text, uint32_t color,
        int wrap_width, int *width, int *height, bool *transient) {
    *transient = false;
    ++state->text_cache_tick;
    for (size_t i = 0; i < state->text_cache_count; ++i) {
        UiTextCacheEntry *entry = &state->text_cache[i];
        if (entry->face == state->current_face && entry->font_size == state->font_size &&
                entry->font_weight == state->font_weight && entry->color == color &&
                entry->wrap_width == wrap_width && strcmp(entry->text, text) == 0) {
            entry->used_at = state->text_cache_tick;
            *width = entry->width;
            *height = entry->height;
            return entry->texture;
        }
    }
    UiSdlColor foreground = {
        (uint8_t)(color >> 24), (uint8_t)(color >> 16),
        (uint8_t)(color >> 8), (uint8_t)color
    };
    size_t length = strlen(text);
    UiSdlSurface *surface = wrap_width > 0
        ? g_ttf.RenderTextBlendedWrapped(state->font, text, length, foreground, wrap_width)
        : g_ttf.RenderTextBlended(state->font, text, length, foreground);
    bool measured = wrap_width > 0
        ? g_ttf.GetStringSizeWrapped(state->font, text, length, wrap_width, width, height)
        : g_ttf.GetStringSize(state->font, text, length, width, height);
    if (surface == NULL || !measured) {
        if (surface != NULL) g_sdl.DestroySurface(surface);
        ui_set_error(g_sdl.GetError());
        return NULL;
    }
    UiSdlTexture *texture = g_sdl.CreateTextureFromSurface(state->renderer, surface);
    g_sdl.DestroySurface(surface);
    if (texture == NULL) { ui_set_error(g_sdl.GetError()); return NULL; }
    size_t pixel_count = *width > 0 && *height > 0 ? (size_t)*width * (size_t)*height : 0;
    size_t bytes = pixel_count <= SIZE_MAX / 4 ? pixel_count * 4 : SIZE_MAX;
    const size_t byte_limit = 64u * 1024u * 1024u;
    if (bytes > byte_limit) {
        *transient = true;
        return texture;
    }
    char *owned_text = ui_copy_cstr(text);
    if (owned_text == NULL) { g_sdl.DestroyTexture(texture); ui_set_error("Unable to cache rendered text"); return NULL; }
    while (state->text_cache_count > 0 &&
            (state->text_cache_count >= 128 || state->text_cache_bytes + bytes > byte_limit)) {
        ui_remove_text_cache_entry(state, ui_oldest_text_cache_entry(state));
    }
    size_t slot = state->text_cache_count++;
    state->text_cache[slot] = (UiTextCacheEntry){texture, owned_text, state->current_face,
        state->font_size, state->font_weight, color, wrap_width, *width, *height, bytes, state->text_cache_tick};
    state->text_cache_bytes += bytes;
    return texture;
}

bool encore_ui_text(size_t handle, float x, float y, encore_str value, uint32_t color) {
    UiWindow *state = ui_window(handle); if (state == NULL || !state->open) return false;
    char *text = ui_to_cstr(value); if (text == NULL) return false;
    if (state->font == NULL) {
        if (!ui_color(state, color)) { free(text); return false; }
        bool result = g_sdl.RenderDebugText(state->renderer, x, y, text);
        free(text);
        return result;
    }
    int width = 0;
    int height = 0;
    bool transient = false;
    UiSdlTexture *texture = ui_text_texture(state, text, color, 0, &width, &height, &transient);
    free(text);
    if (texture == NULL) return false;
    float density = state->pixel_density > 0.0f ? state->pixel_density : 1.0f;
    UiSdlFRect destination = {x, y, (float)width / density, (float)height / density};
    bool result = g_sdl.RenderTexture(state->renderer, texture, NULL, &destination);
    if (transient) g_sdl.DestroyTexture(texture);
    return result;
}

bool encore_ui_text_wrapped(size_t handle, float x, float y, encore_str value, uint32_t color, float wrap_width) {
    UiWindow *state = ui_window(handle); if (state == NULL || !state->open || wrap_width <= 0.0f) return false;
    char *text = ui_to_cstr(value); if (text == NULL) return false;
    if (state->font == NULL) {
        if (!ui_color(state, color)) { free(text); return false; }
        bool result = g_sdl.RenderDebugText(state->renderer, x, y, text);
        free(text);
        return result;
    }
    float density = state->pixel_density > 0.0f ? state->pixel_density : 1.0f;
    int limit = (int)(wrap_width * density);
    int width = 0;
    int height = 0;
    bool transient = false;
    UiSdlTexture *texture = ui_text_texture(state, text, color, limit, &width, &height, &transient);
    free(text);
    if (texture == NULL) return false;
    UiSdlFRect destination = {x, y, (float)width / density, (float)height / density};
    bool result = g_sdl.RenderTexture(state->renderer, texture, NULL, &destination);
    if (transient) g_sdl.DestroyTexture(texture);
    return result;
}

bool encore_ui_font_load(size_t handle, encore_str path, float size, uint32_t weight) {
    UiWindow *state = ui_window(handle);
    if (state == NULL || !state->open || size <= 0.0f || !ui_load_ttf()) return false;
    char *file = ui_to_cstr(path);
    if (file == NULL) { ui_set_error("Unable to allocate font path"); return false; }
    float density = state->pixel_density > 0.0f ? state->pixel_density : 1.0f;
    UiTtfFont *font = g_ttf.OpenFont(file, size * density);
    if (font == NULL) { free(file); ui_set_error(g_sdl.GetError()); return false; }
    char *default_family = ui_copy_cstr("");
    if (default_family == NULL) { g_ttf.CloseFont(font); free(file); return false; }
    g_ttf.SetFontStyle(font, weight >= 600 ? 0x01u : 0x00u);
    ui_clear_fonts(state);
    state->font = font;
    state->font_size = size;
    state->font_weight = weight;
    state->font_faces[0] = (UiFontFace){default_family, file};
    state->font_face_count = 1;
    state->current_face = 0;
    state->font_tick = 1;
    state->font_variants[0] = (UiFontVariant){font, size, weight, 0, state->font_tick};
    state->font_variant_count = 1;
    return true;
}

bool encore_ui_font_register(size_t handle, encore_str family, encore_str path) {
    UiWindow *state = ui_window(handle);
    if (state == NULL || !state->open || !ui_load_ttf()) return false;
    char *name = ui_to_cstr(family);
    char *file = ui_to_cstr(path);
    if (name == NULL || file == NULL) { free(name); free(file); return false; }
    for (size_t i = 0; i < state->font_face_count; ++i) {
        if (strcmp(state->font_faces[i].family, name) == 0) { free(name); free(file); return true; }
    }
    if (state->font_face_count >= 32) { free(name); free(file); return false; }
    state->font_faces[state->font_face_count++] = (UiFontFace){name, file};
    return true;
}

static bool ui_select_font(UiWindow *state, size_t face, float size, uint32_t weight) {
    if (face >= state->font_face_count || size <= 0.0f) return false;
    ++state->font_tick;
    if (state->font != NULL && state->current_face == face && state->font_size == size && state->font_weight == weight) {
        for (size_t i = 0; i < state->font_variant_count; ++i) {
            if (state->font_variants[i].font == state->font) { state->font_variants[i].used_at = state->font_tick; break; }
        }
        return true;
    }
    for (size_t i = 0; i < state->font_variant_count; ++i) {
        UiFontVariant *variant = &state->font_variants[i];
        if (variant->face == face && variant->size == size && variant->weight == weight) {
            state->font = variant->font;
            state->current_face = face;
            state->font_size = size;
            state->font_weight = weight;
            variant->used_at = state->font_tick;
            return true;
        }
    }
    float density = state->pixel_density > 0.0f ? state->pixel_density : 1.0f;
    UiTtfFont *font = g_ttf.OpenFont(state->font_faces[face].path, size * density);
    if (font == NULL) { ui_set_error(g_sdl.GetError()); return false; }
    g_ttf.SetFontStyle(font, weight >= 600 ? 0x01u : 0x00u);
    size_t slot = state->font_variant_count;
    if (slot < 32) {
        ++state->font_variant_count;
    } else {
        slot = 0;
        for (size_t i = 1; i < state->font_variant_count; ++i) {
            if (state->font_variants[i].used_at < state->font_variants[slot].used_at) slot = i;
        }
        if (state->font_variants[slot].font != NULL) g_ttf.CloseFont(state->font_variants[slot].font);
    }
    state->font_variants[slot] = (UiFontVariant){font, size, weight, face, state->font_tick};
    state->font = font;
    state->current_face = face;
    state->font_size = size;
    state->font_weight = weight;
    return true;
}

bool encore_ui_font_select(size_t handle, encore_str family, float size, uint32_t weight) {
    UiWindow *state = ui_window(handle);
    if (state == NULL || !state->open) return false;
    char *name = ui_to_cstr(family);
    if (name == NULL) return false;
    size_t face = state->font_face_count;
    for (size_t i = 0; i < state->font_face_count; ++i) {
        if (strcmp(state->font_faces[i].family, name) == 0) { face = i; break; }
    }
    free(name);
    return face < state->font_face_count && ui_select_font(state, face, size, weight);
}

bool encore_ui_font_clear(size_t handle) {
    UiWindow *state = ui_window(handle);
    if (state == NULL) return false;
    ui_clear_fonts(state);
    return true;
}

bool encore_ui_font_style(size_t handle, float size, uint32_t weight) {
    UiWindow *state = ui_window(handle);
    if (state == NULL || size <= 0.0f) return false;
    if (state->font == NULL) return true;
    return ui_select_font(state, state->current_face, size, weight);
}

static float ui_text_extent(size_t handle, encore_str value, bool width) {
    UiWindow *state = ui_window(handle);
    if (state == NULL) return 0.0f;
    if (state->font == NULL) return (float)(width ? (value.object == NULL ? 0 : value.object->len * 8) : 8);
    int measured_width = 0;
    int measured_height = 0;
    const char *text = value.object == NULL ? "" : value.object->data;
    size_t length = value.object == NULL ? 0 : value.object->len;
    if (!g_ttf.GetStringSize(state->font, text, length, &measured_width, &measured_height)) return 0.0f;
    float density = state->pixel_density > 0.0f ? state->pixel_density : 1.0f;
    return (float)(width ? measured_width : measured_height) / density;
}

float encore_ui_text_width(size_t handle, encore_str value) { return ui_text_extent(handle, value, true); }
float encore_ui_text_height(size_t handle, encore_str value) { return ui_text_extent(handle, value, false); }
size_t encore_ui_text_index(size_t handle, encore_str value, float max_width) {
    UiWindow *state = ui_window(handle);
    if (state == NULL || value.object == NULL || max_width <= 0.0f) return 0;
    size_t byte_count = 0;
    if (state->font == NULL) {
        byte_count = (size_t)(max_width / 8.0f);
        if (byte_count > value.object->len) byte_count = value.object->len;
    } else {
        int measured_width = 0;
        float density = state->pixel_density > 0.0f ? state->pixel_density : 1.0f;
        if (!g_ttf.MeasureString(state->font, value.object->data, value.object->len,
                (int)(max_width * density), &measured_width, &byte_count)) return 0;
    }
    size_t characters = 0;
    size_t index = 0;
    while (index < byte_count) {
        uint8_t first = (uint8_t)value.object->data[index];
        size_t width = first < 0x80u ? 1u : (first & 0xe0u) == 0xc0u ? 2u :
            (first & 0xf0u) == 0xe0u ? 3u : 4u;
        index += width;
        characters += 1;
    }
    return characters;
}
bool encore_ui_frame_end(size_t handle) {
    UiWindow *state = ui_window(handle);
    if (state == NULL || !state->open) return false;
    /* A software renderer still needs RenderPresent to flush commands into its surface. */
    if (state->external_presentation) return g_sdl.RenderPresent(state->renderer);
    return g_sdl.RenderPresent(state->renderer);
}

bool encore_ui_pixels(size_t handle, size_t pixels_handle, uint32_t source_width, uint32_t source_height,
    uint32_t source_pitch, float x, float y, float width, float height) {
    UiWindow *state = ui_window(handle);
    const void *pixels = (const void *)(uintptr_t)pixels_handle;
    if (state == NULL || state->renderer == NULL || pixels == NULL || source_width == 0 || source_height == 0 ||
        source_pitch < source_width * 4 || width <= 0.0f || height <= 0.0f) return false;
    /* SDL_PIXELFORMAT_ARGB8888 is BGRA byte order on little-endian hosts, matching Vulkan B8G8R8A8. */
    if (state->pixels_texture == NULL || state->pixels_width != source_width || state->pixels_height != source_height) {
        if (state->pixels_texture != NULL) g_sdl.DestroyTexture(state->pixels_texture);
        state->pixels_texture = g_sdl.CreateTexture(state->renderer, 0x16362004u, 1,
            (int)source_width, (int)source_height);
        state->pixels_width = source_width;
        state->pixels_height = source_height;
    }
    if (state->pixels_texture == NULL) { ui_set_error(g_sdl.GetError()); return false; }
    bool updated = g_sdl.UpdateTexture(state->pixels_texture, NULL, pixels, (int)source_pitch);
    UiSdlFRect destination = {x, y, width, height};
    bool rendered = updated && g_sdl.RenderTexture(state->renderer, state->pixels_texture, NULL, &destination);
    if (!rendered) ui_set_error(g_sdl.GetError());
    return rendered;
}
encore_str encore_ui_backend_name(void) { return ui_string(g_sdl.ready ? "SDL3" : "unavailable"); }
encore_str encore_ui_backend_error(void) { return ui_string(g_error); }
