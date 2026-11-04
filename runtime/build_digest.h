#ifndef ENCORE_BUILD_DIGEST_H
#define ENCORE_BUILD_DIGEST_H
#include <stdatomic.h>

extern encore_compiler_str encore_fs_sha256(encore_compiler_str path);

#ifndef _WIN32
/* Command-local memoization only: each fresh process hashes contents first.
 * Changed inode, size, mtime OR ctime invalidates a memo, including equal-size
 * edits whose original mtime was restored. No persistent timestamp receipt. */
typedef struct {
  char *path;
  struct stat fact;
  char digest[65];
} encore_build_digest_entry;
static encore_build_digest_entry encore_build_digests[32];
static size_t encore_build_digest_next;
static atomic_flag encore_build_digest_lock = ATOMIC_FLAG_INIT;
static void encore_build_digest_acquire(void) {
  while (atomic_flag_test_and_set_explicit(&encore_build_digest_lock,
                                           memory_order_acquire)) {
  }
}
static void encore_build_digest_unlock(void) {
  atomic_flag_clear_explicit(&encore_build_digest_lock, memory_order_release);
}
static bool encore_build_digest_same(const struct stat *a,
                                     const struct stat *b) {
  if (a->st_dev != b->st_dev || a->st_ino != b->st_ino ||
      a->st_size != b->st_size || a->st_mode != b->st_mode)
    return false;
#if defined(__APPLE__)
  return a->st_mtimespec.tv_sec == b->st_mtimespec.tv_sec &&
         a->st_mtimespec.tv_nsec == b->st_mtimespec.tv_nsec &&
         a->st_ctimespec.tv_sec == b->st_ctimespec.tv_sec &&
         a->st_ctimespec.tv_nsec == b->st_ctimespec.tv_nsec;
#else
  return a->st_mtim.tv_sec == b->st_mtim.tv_sec &&
         a->st_mtim.tv_nsec == b->st_mtim.tv_nsec &&
         a->st_ctim.tv_sec == b->st_ctim.tv_sec &&
         a->st_ctim.tv_nsec == b->st_ctim.tv_nsec;
#endif
}
#endif

encore_compiler_str encore_compiler_file_digest(encore_compiler_str path) {
#ifdef _WIN32
  return encore_fs_sha256(path);
#else
  char *name = encore_compiler_cstr(path);
  struct stat before, after;
  if (name == NULL || stat(name, &before) != 0 || !S_ISREG(before.st_mode)) {
    free(name);
    return encore_fs_sha256(path);
  }
  char found[65] = {0};
  encore_build_digest_acquire();
  for (size_t index = 0; index < 32; ++index) {
    encore_build_digest_entry *entry = &encore_build_digests[index];
    if (entry->path != NULL && strcmp(entry->path, name) == 0 &&
        encore_build_digest_same(&before, &entry->fact)) {
      memcpy(found, entry->digest, sizeof(found));
      break;
    }
  }
  encore_build_digest_unlock();
  if (found[0] != 0) {
    char *copy = malloc(65);
    if (copy != NULL)
      memcpy(copy, found, 65);
    free(name);
    return copy == NULL ? (encore_compiler_str){NULL}
                        : encore_compiler_owned_string(copy, 64);
  }
  encore_compiler_str digest = encore_fs_sha256(path);
  if (digest.object != NULL && digest.object->len == 64 &&
      stat(name, &after) == 0 && encore_build_digest_same(&before, &after)) {
    encore_build_digest_acquire();
    encore_build_digest_entry *entry =
        &encore_build_digests[encore_build_digest_next++ % 32];
    free(entry->path);
    entry->path = name;
    name = NULL;
    entry->fact = after;
    memcpy(entry->digest, digest.object->data, 64);
    entry->digest[64] = 0;
    encore_build_digest_unlock();
  }
  free(name);
  return digest;
#endif
}
#endif
