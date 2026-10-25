/* Thread-safe live terminal state. Only the command owner starts/stops the
   renderer; reporters copy strings and never retain Encore-managed objects. */
#ifndef ENCORE_RICH_LIVE_PROGRESS_H
#define ENCORE_RICH_LIVE_PROGRESS_H

#ifndef _WIN32
#include <sys/ioctl.h>
#endif

/* Published target kits can carry an older platform runtime. The optional
   observer must never make an otherwise compatible library fail to link. */
typedef void (*rich_write_observer)(int32_t, const char *, size_t, bool);
#ifdef _MSC_VER
void encore_rich_no_write_observer(rich_write_observer observer) { (void)observer; }
extern void encore_io_set_write_observer(rich_write_observer observer);
#ifdef _M_IX86
#pragma comment(linker, "/alternatename:_encore_io_set_write_observer=_encore_rich_no_write_observer")
#else
#pragma comment(linker, "/alternatename:encore_io_set_write_observer=encore_rich_no_write_observer")
#endif
static bool live_io_available(void) {
    /* The linker supplies the alias. A volatile load keeps the compiler from
       assuming two differently named functions must have distinct addresses. */
    void (*volatile setter)(rich_write_observer) = encore_io_set_write_observer;
    return setter != encore_rich_no_write_observer;
}
#else
extern void encore_io_set_write_observer(rich_write_observer observer) __attribute__((weak));
static bool live_io_available(void) { return encore_io_set_write_observer != NULL; }
#endif

typedef struct {
    size_t id;
    char *label;
    char *stage;
    bool complete;
} rich_live_task;

static _Atomic size_t g_live_session;
static size_t g_live_generation;
static rich_live_task *g_live_tasks;
static size_t g_live_count, g_live_capacity, g_live_total, g_live_completed;
static size_t g_live_rows;
static uint64_t g_live_started;
static bool g_live_partial, g_live_color;
#ifdef _WIN32
static DWORD g_live_console_mode;
static bool g_live_restore_console;
#endif

static uint64_t live_clock_ms(void) {
#ifdef _WIN32
    return GetTickCount64();
#else
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    return (uint64_t)now.tv_sec * 1000 + (uint64_t)now.tv_nsec / 1000000;
#endif
}

static bool live_terminal_supported(void) {
    const char *term = getenv("TERM");
    if (!live_io_available() || !encore_rich_is_terminal(2) ||
        (term != NULL && strcmp(term, "dumb") == 0)) return false;
#ifdef _WIN32
    HANDLE output = GetStdHandle(STD_ERROR_HANDLE);
    DWORD mode;
    if (!GetConsoleMode(output, &mode)) return false;
#endif
    return true;
}

static bool live_enable_terminal(void) {
#ifdef _WIN32
    HANDLE output = GetStdHandle(STD_ERROR_HANDLE);
    DWORD mode;
    if (!GetConsoleMode(output, &mode)) return false;
    if (!(mode & ENABLE_VIRTUAL_TERMINAL_PROCESSING)) {
        if (!SetConsoleMode(output, mode | ENABLE_VIRTUAL_TERMINAL_PROCESSING)) return false;
        g_live_console_mode = mode;
        g_live_restore_console = true;
    }
#endif
    return true;
}

static void live_restore_terminal(void) {
#ifdef _WIN32
    if (g_live_restore_console) {
        SetConsoleMode(GetStdHandle(STD_ERROR_HANDLE), g_live_console_mode);
        g_live_restore_console = false;
    }
#endif
}

static void live_dimensions(size_t *width, size_t *height) {
    *width = 80;
    *height = 24;
#ifdef _WIN32
    CONSOLE_SCREEN_BUFFER_INFO info;
    if (GetConsoleScreenBufferInfo(GetStdHandle(STD_ERROR_HANDLE), &info)) {
        *width = (size_t)(info.srWindow.Right - info.srWindow.Left + 1);
        *height = (size_t)(info.srWindow.Bottom - info.srWindow.Top + 1);
    }
#else
    struct winsize size;
    if (ioctl(2, TIOCGWINSZ, &size) == 0) {
        if (size.ws_col != 0) *width = size.ws_col;
        if (size.ws_row != 0) *height = size.ws_row;
    }
#endif
}

/* Keep complete UTF-8 sequences, discard terminal controls, and account for
   combining marks and common wide/emoji ranges without changing process locale. */
static size_t live_text(const char *text, size_t available) {
    size_t used = 0;
    const unsigned char *cursor = (const unsigned char *)(text == NULL ? "" : text);
    while (*cursor != 0) {
        unsigned int point = *cursor;
        size_t bytes = 1;
        if (point >= 0xc2 && point <= 0xf4) {
            bytes = point < 0xe0 ? 2 : point < 0xf0 ? 3 : 4;
            point &= bytes == 2 ? 0x1f : bytes == 3 ? 0xf : 7;
            size_t index;
            for (index = 1; index < bytes; ++index) {
                if ((cursor[index] & 0xc0) != 0x80) break;
                point = (point << 6) | (cursor[index] & 0x3f);
            }
            if (index != bytes) { ++cursor; continue; }
        } else if (point >= 0x80) {
            ++cursor;
            continue;
        }
        if (point < 0x20 || (point >= 0x7f && point < 0xa0)) {
            ++cursor;
            continue;
        }
        size_t cells = 1;
        if ((point >= 0x300 && point <= 0x36f) || (point >= 0x1ab0 && point <= 0x1aff) ||
            (point >= 0x1dc0 && point <= 0x1dff) || (point >= 0xfe00 && point <= 0xfe0f) ||
            (point >= 0xfe20 && point <= 0xfe2f) || point == 0x200d) cells = 0;
        else if (point >= 0x1100 && (point <= 0x115f || point == 0x2329 || point == 0x232a ||
                 (point >= 0x2e80 && point <= 0xa4cf && point != 0x303f) ||
                 (point >= 0xac00 && point <= 0xd7a3) || (point >= 0xf900 && point <= 0xfaff) ||
                 (point >= 0xfe10 && point <= 0xfe19) || (point >= 0xfe30 && point <= 0xfe6f) ||
                 (point >= 0xff00 && point <= 0xff60) || (point >= 0xffe0 && point <= 0xffe6) ||
                 (point >= 0x1f300 && point <= 0x1faff) || (point >= 0x20000 && point <= 0x3fffd))) cells = 2;
        if (used + cells > available) break;
        fwrite(cursor, 1, bytes, stderr);
        used += cells;
        cursor += bytes;
    }
    return used;
}

/* Cursor stays visible; an uncatchable termination cannot leave it hidden. */
static void live_clear_locked(void) {
    if (g_live_rows == 0) return;
    fputs("\r\x1b[2K", stderr);
    while (--g_live_rows != 0) fputs("\x1b[1A\r\x1b[2K", stderr);
}

static void live_render_locked(size_t tick) {
    if (g_live_partial) return;
    size_t width, height;
    live_dimensions(&width, &height);
    live_clear_locked();
    fputs("\r\x1b[2K", stderr);
    if (width < 4 || height < 2) { fflush(stderr); return; }
    --width; /* Never trigger automatic line wrapping. */
    if (g_live_color) fputs("\x1b[36m", stderr);
    write_frame(tick);
    if (g_live_color) fputs("\x1b[0m", stderr);
    fputc(' ', stderr);
    char suffix[100];
    uint64_t elapsed = live_clock_ms() - g_live_started;
    if (g_live_total != 0)
        snprintf(suffix, sizeof(suffix), " [%zu/%zu] %llu.%llus", g_live_completed, g_live_total,
                 (unsigned long long)(elapsed / 1000), (unsigned long long)(elapsed % 1000 / 100));
    else
        snprintf(suffix, sizeof(suffix), " %llu.%llus", (unsigned long long)(elapsed / 1000),
                 (unsigned long long)(elapsed % 1000 / 100));
    size_t used = live_text(g_message, width > strlen(suffix) + 2 ? width - strlen(suffix) - 2 : 0);
    live_text(suffix, width - used - 2);
    g_live_rows = 1;
    size_t limit = height > 3 ? height - 3 : 0;
    if (limit > 6) limit = 6;
    size_t active = 0, shown = 0;
    for (size_t index = 0; index < g_live_count; ++index) if (!g_live_tasks[index].complete) ++active;
    size_t task_limit = active > limit && limit != 0 ? limit - 1 : limit;
    for (size_t index = 0; index < g_live_count && shown < task_limit; ++index) {
        rich_live_task *task = &g_live_tasks[index];
        if (task->complete) continue;
        fputs("\r\n  ", stderr);
        size_t available = width > 2 ? width - 2 : 0;
        used = live_text(task->label, available > 18 ? available - 18 : available);
        if (used + 2 < available) {
            fputs("  ", stderr);
            live_text(task->stage, available - used - 2);
        }
        ++shown;
        ++g_live_rows;
    }
    if (active > shown && limit != 0) {
        fputs("\r\n", stderr);
        snprintf(suffix, sizeof(suffix), "  ... %zu more active", active - shown);
        live_text(suffix, width);
        ++g_live_rows;
    }
    fflush(stderr);
}

static void live_observe_write(int32_t fd, const char *data, size_t length, bool begin) {
    if (begin) {
        lock_spinner();
        live_clear_locked();
        fflush(stderr);
    } else {
        if ((fd == 2 || encore_rich_is_terminal(fd)) && data != NULL && length != 0)
            g_live_partial = data[length - 1] != '\n';
        unlock_spinner();
    }
}

static void live_free_tasks_locked(void) {
    for (size_t index = 0; index < g_live_count; ++index) {
        free(g_live_tasks[index].label);
        free(g_live_tasks[index].stage);
    }
    free(g_live_tasks);
    g_live_tasks = NULL;
    g_live_count = g_live_capacity = g_live_completed = g_live_total = 0;
}

size_t encore_rich_live_current(void) { return atomic_load(&g_live_session); }

void encore_rich_live_stage(size_t session, encore_str label, size_t total) {
    if (session == 0 || session != atomic_load(&g_live_session)) return;
    char *copy = copy_string(label);
    if (copy == NULL) return;
    lock_spinner();
    if (session == atomic_load(&g_live_session)) {
        free(g_message);
        g_message = copy;
        copy = NULL;
        live_free_tasks_locked();
        g_live_total = total;
    }
    unlock_spinner();
    free(copy);
}

void encore_rich_live_task(size_t session, size_t id, encore_str label, encore_str stage, bool complete) {
    if (session == 0 || session != atomic_load(&g_live_session)) return;
    /* Cache-lock polling can report an unchanged state repeatedly. Avoid
       allocation on those observations, and ignore duplicate completions. */
    bool unchanged = false;
    lock_spinner();
    for (size_t index = 0; index < g_live_count; ++index) {
        rich_live_task *task = &g_live_tasks[index];
        if (task->id != id) continue;
        size_t label_len = label.object == NULL ? 0 : label.object->len;
        size_t stage_len = stage.object == NULL ? 0 : stage.object->len;
        unchanged = task->complete || (!complete && strlen(task->label) == label_len &&
                    strlen(task->stage) == stage_len &&
                    (label_len == 0 || memcmp(task->label, label.object->data, label_len) == 0) &&
                    (stage_len == 0 || memcmp(task->stage, stage.object->data, stage_len) == 0));
        break;
    }
    unlock_spinner();
    if (unchanged) return;
    char *label_copy = copy_string(label), *stage_copy = copy_string(stage);
    if (label_copy == NULL || stage_copy == NULL) { free(label_copy); free(stage_copy); return; }
    lock_spinner();
    if (session == atomic_load(&g_live_session)) {
        size_t index = 0;
        while (index < g_live_count && g_live_tasks[index].id != id) ++index;
        if (index == g_live_count && g_live_count == g_live_capacity) {
            size_t capacity = g_live_capacity == 0 ? 16 : g_live_capacity * 2;
            rich_live_task *tasks = (rich_live_task *)realloc(g_live_tasks, capacity * sizeof(*tasks));
            if (tasks != NULL) { g_live_tasks = tasks; g_live_capacity = capacity; }
        }
        if (index < g_live_capacity) {
            if (index == g_live_count) {
                g_live_tasks[index] = (rich_live_task){id, NULL, NULL, false};
                ++g_live_count;
            }
            rich_live_task *task = &g_live_tasks[index];
            if (!task->complete) {
                free(task->label);
                free(task->stage);
                task->label = label_copy;
                task->stage = stage_copy;
                label_copy = stage_copy = NULL;
                task->complete = complete;
                if (complete) ++g_live_completed;
            }
        }
    }
    unlock_spinner();
    free(label_copy);
    free(stage_copy);
}

#endif
