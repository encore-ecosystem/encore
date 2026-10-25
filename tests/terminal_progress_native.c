/* Exercise the real rich renderer and platform I/O together. stdin provides
   barriers so the PTY test observes frames while work is still in progress. */
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>

typedef struct { size_t refs, len; char data[]; } str_object;
typedef struct { str_object *object; } str;

void *encore_str_from_cstr(const char *text) {
    size_t length = strlen(text);
    str_object *object = malloc(sizeof(*object) + length + 1);
    if (object == NULL) abort();
    object->refs = 1;
    object->len = length;
    memcpy(object->data, text, length + 1);
    return object;
}

char *encore_str_data(str value) { return value.object == NULL ? NULL : value.object->data; }
size_t encore_str_size(str value) { return value.object == NULL ? 0 : value.object->len; }
str encore_str_from_codepoint(size_t point) { (void)point; return (str){encore_str_from_cstr(".")}; }

extern size_t encore_rich_live_start(str, str, size_t);
extern size_t encore_rich_live_current(void);
extern void encore_rich_live_stage(size_t, str, size_t);
extern void encore_rich_live_task(size_t, size_t, str, str, bool);
extern void encore_rich_live_stop(size_t);
extern void encore_rich_terminal_spinner_stop(void);
extern int32_t encore_io_write(int32_t, str);

static str text(const char *value) { return (str){encore_str_from_cstr(value)}; }
static void stage(size_t session, const char *label, size_t total) {
    str value = text(label);
    encore_rich_live_stage(session, value, total);
    free(value.object);
}
static void task(size_t session, size_t id, const char *label, const char *detail, bool complete) {
    str name = text(label), state = text(detail);
    encore_rich_live_task(session, id, name, state, complete);
    free(name.object);
    free(state.object);
}
static void output(int fd, const char *value) {
    str string = text(value);
    if (encore_io_write(fd, string) != 0) abort();
    free(string.object);
}
static void barrier(void) { if (getchar() == EOF) exit(2); }

static void *start_task(void *argument) {
    size_t id = (size_t)(uintptr_t)argument;
    char name[80];
    snprintf(name, sizeof(name), "package-%zu-中文-e\xcc\x81-long-name", id);
    task(encore_rich_live_current(), id, name, "compiling", false);
    return NULL;
}

int main(void) {
    str title = text("Loading project"), frames = text("⠋\n⠙\n⠹\n⠸");
    size_t session = encore_rich_live_start(title, frames, 80);
    free(title.object);
    free(frames.object);
    if (encore_rich_live_current() != session) return 3;
    stage(session, "Compiling packages", 8);
    pthread_t workers[8];
    for (size_t id = 0; id < 8; ++id)
        if (pthread_create(&workers[id], NULL, start_task, (void *)(uintptr_t)id) != 0) return 4;
    for (size_t id = 0; id < 8; ++id) pthread_join(workers[id], NULL);
    /* A legacy suspend must not stop a command-owned session. */
    encore_rich_terminal_spinner_stop();
    output(1, "READY\n");
    barrier();
    task(session, 0, "package-0", "metadata ready; building archive", false);
    task(session, 1, "package-1", "", true);
    task(session, 1, "package-1", "", true);
    output(2, "diagnostic: complete line\n");
    barrier();
    stage(session, "Linking", 0);
    barrier();
    encore_rich_live_stop(session);
    output(1, "USER PROGRAM\n");
    barrier();
    title = text("Second operation");
    frames = text("⠋\n⠙");
    size_t second = encore_rich_live_start(title, frames, 80);
    free(title.object);
    free(frames.object);
    task(session, 99, "STALE REPORTER", "must be ignored", false);
    barrier();
    encore_rich_live_stop(second);
    return 0;
}
