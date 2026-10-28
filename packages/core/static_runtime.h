#ifndef ENCORE_STATIC_RUNTIME_H
#define ENCORE_STATIC_RUNTIME_H

/* Process-lifetime roots for language statics. Typed allocation and ownership
 * stay in Encore lowering; this boundary only coordinates publication. User
 * initializers run outside the lock and may initialize other cells. */
typedef struct encore_static_cell encore_static_cell;
typedef struct encore_static_thread {
    encore_static_cell *waiting;
} encore_static_thread;
struct encore_static_cell {
    unsigned state; /* 0 empty, 1 initializing, 2 published */
    size_t value;
    void (*drop)(size_t);
    encore_static_cell *next_created, *next_published;
    encore_static_thread *owner;
#ifdef _WIN32
    CONDITION_VARIABLE ready;
#else
    pthread_cond_t ready;
#endif
};

static void *encore_static_cells;
static encore_static_cell *encore_static_created, *encore_static_published;
static _Thread_local encore_static_thread encore_static_current_thread;
#ifdef _WIN32
static SRWLOCK encore_static_lock = SRWLOCK_INIT;
static void encore_static_lock_enter(void) { AcquireSRWLockExclusive(&encore_static_lock); }
static void encore_static_lock_leave(void) { ReleaseSRWLockExclusive(&encore_static_lock); }
#else
static pthread_mutex_t encore_static_lock = PTHREAD_MUTEX_INITIALIZER;
static void encore_static_lock_enter(void) { if (pthread_mutex_lock(&encore_static_lock)) abort(); }
static void encore_static_lock_leave(void) { if (pthread_mutex_unlock(&encore_static_lock)) abort(); }
#endif

static void encore_static_fail(const char *message) {
    fprintf(stderr, "panic: %s\n", message);
    fflush(stderr);
    exit(1);
}

void *encore_static_cell_get(encore_str key) {
    encore_static_lock_enter();
    if (encore_static_cells == NULL) encore_static_cells = encore_strmap_new();
    if (encore_static_cells == NULL) encore_static_fail("cannot allocate static registry");
    encore_static_cell *cell = (void *)encore_strmap_get(encore_static_cells, key);
    if (cell == NULL) {
        cell = calloc(1, sizeof(*cell));
        if (cell == NULL) encore_static_fail("cannot allocate static cell");
#ifdef _WIN32
        InitializeConditionVariable(&cell->ready);
#else
        if (pthread_cond_init(&cell->ready, NULL)) encore_static_fail("cannot initialize static cell");
#endif
        cell->next_created = encore_static_created; encore_static_created = cell;
        encore_strmap_put(encore_static_cells, key, (size_t)cell);
        if (encore_strmap_get(encore_static_cells, key) != (size_t)cell)
            encore_static_fail("cannot register static cell");
    }
    encore_static_lock_leave();
    return cell;
}

bool encore_static_begin(void *raw) {
    encore_static_cell *cell = raw;
    if (cell == NULL) encore_static_fail("invalid static cell");
    encore_static_thread *thread = &encore_static_current_thread;
    encore_static_lock_enter();
    while (cell->state == 1) {
        /* Detect recursion and wait cycles between different native threads. */
        thread->waiting = cell;
        encore_static_thread *owner = cell->owner;
        while (owner != NULL) {
            if (owner == thread) encore_static_fail("cyclic static initialization");
            owner = owner->waiting == NULL ? NULL : owner->waiting->owner;
        }
#ifdef _WIN32
        if (!SleepConditionVariableSRW(&cell->ready, &encore_static_lock, INFINITE, 0))
            encore_static_fail("cannot wait for static initialization");
#else
        if (pthread_cond_wait(&cell->ready, &encore_static_lock))
            encore_static_fail("cannot wait for static initialization");
#endif
        thread->waiting = NULL;
    }
    bool initialize = cell->state == 0;
    if (initialize) { cell->state = 1; cell->owner = thread; }
    encore_static_lock_leave();
    return initialize;
}

void encore_static_publish_owned(void *raw, size_t value, uintptr_t drop_address) {
    encore_static_cell *cell = raw;
    encore_static_lock_enter();
    if (cell == NULL || cell->state != 1 || cell->owner != &encore_static_current_thread)
        encore_static_fail("invalid static publication");
    cell->value = value;
    _Static_assert(sizeof(cell->drop) == sizeof(drop_address), "static destructor pointer size");
    memcpy(&cell->drop, &drop_address, sizeof(cell->drop));
    cell->next_published = encore_static_published; encore_static_published = cell;
    cell->owner = NULL;
    cell->state = 2;
#ifdef _WIN32
    WakeAllConditionVariable(&cell->ready);
#else
    if (pthread_cond_broadcast(&cell->ready)) encore_static_fail("cannot publish static value");
#endif
    encore_static_lock_leave();
}

void encore_static_publish(void *raw, size_t value) { encore_static_publish_owned(raw, value, 0); }

size_t encore_static_value(void *raw) {
    encore_static_cell *cell = raw;
    encore_static_lock_enter();
    if (cell == NULL || cell->state != 2) encore_static_fail("static value is not initialized");
    size_t value = cell->value;
    encore_static_lock_leave();
    return value;
}
/* Called only after a plugin generation has drained all users. Destructors run
 * in reverse publication order, before any generated code is unloaded. Normal
 * executables retain their process-lifetime static behavior. */
void encore_static_shutdown(void) {
    encore_static_lock_enter();
    encore_static_cell *published = encore_static_published;
    encore_static_cell *created = encore_static_created;
    void *registry = encore_static_cells;
    encore_static_published = encore_static_created = NULL;
    encore_static_cells = NULL;
    for (encore_static_cell *cell = created; cell; cell = cell->next_created)
        if (cell->state == 1) encore_static_fail("static shutdown during initialization");
    encore_static_lock_leave();
    for (encore_static_cell *cell = published; cell; cell = cell->next_published)
        if (cell->drop) cell->drop(cell->value);
    while (created) {
        encore_static_cell *next = created->next_created;
#ifndef _WIN32
        if (pthread_cond_destroy(&created->ready)) abort();
#endif
        free(created); created = next;
    }
    encore_strmap_free(registry);
}
#endif
