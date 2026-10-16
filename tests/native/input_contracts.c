/* Real pipes: wait for the prompt before supplying any input. The deadline
 * detects a deadlock, not slow execution or a performance regression. */
#include <assert.h>
#include <poll.h>

static void ci_pipe_write(int fd, const char *text, size_t length) {
    while (length != 0) {
        ssize_t count = write(fd, text, length);
        if (count < 0 && errno == EINTR) continue;
        assert(count > 0);
        text += count; length -= (size_t)count;
    }
}

static char *ci_pipe_read(int fd, size_t *length) {
    size_t capacity = 32768;
    char *text = malloc(capacity);
    assert(text != NULL);
    *length = 0;
    for (;;) {
        struct pollfd ready = {fd, POLLIN, 0};
        assert(poll(&ready, 1, 15000) == 1);
        if (*length + 4096 + 1 > capacity) {
            capacity *= 2; text = realloc(text, capacity); assert(text != NULL);
        }
        ssize_t count = read(fd, text + *length, capacity - *length - 1);
        if (count < 0 && errno == EINTR) continue;
        assert(count >= 0);
        if (count == 0) break;
        *length += (size_t)count;
    }
    text[*length] = 0;
    close(fd);
    return text;
}

static void ci_input_case(const char *binary, const char *data,
    const char *expected, int expected_status, bool prompt, bool full) {
    int input[2], output[2];
    assert(pipe(input) == 0 && pipe(output) == 0);
    pid_t pid = fork(); assert(pid >= 0);
    if (pid == 0) {
        close(input[1]); close(output[0]);
        assert(dup2(input[0], STDIN_FILENO) >= 0);
        if (full) {
            int sink = open("/dev/full", O_WRONLY); assert(sink >= 0);
            assert(dup2(sink, STDOUT_FILENO) >= 0); close(sink);
        } else { assert(dup2(output[1], STDOUT_FILENO) >= 0); }
        assert(dup2(output[1], STDERR_FILENO) >= 0);
        close(input[0]); close(output[1]);
        execl(binary, binary, (char *)NULL); _exit(127);
    }
    close(input[0]); close(output[1]);
    if (prompt) {
        char bytes[6]; size_t count = 0;
        while (count < sizeof(bytes)) {
            struct pollfd ready = {output[0], POLLIN, 0};
            assert(poll(&ready, 1, 15000) == 1);
            ssize_t read_count = read(output[0], bytes + count, sizeof(bytes) - count);
            assert(read_count > 0); count += (size_t)read_count;
        }
        assert(memcmp(bytes, "name> ", sizeof(bytes)) == 0);
    }
    ci_pipe_write(input[1], data, strlen(data)); close(input[1]);
    size_t length = 0;
    char *text = ci_pipe_read(output[0], &length);
    int status = 0;
    assert(waitpid(pid, &status, 0) == pid && WIFEXITED(status));
    if (expected_status >= 0) {
        assert(WEXITSTATUS(status) == expected_status);
        assert(strcmp(text, expected) == 0);
    } else {
        assert(WEXITSTATUS(status) != 0);
        if (!full) assert(strstr(text, "end of input") != NULL);
    }
    free(text);
}

int32_t encore_ci_input(encore_compiler_str executable) {
    char *binary = encore_compiler_cstr(executable); assert(binary != NULL);
    ci_input_case(binary, "привет\r\nмир\n", "name> привет\nnext> мир\n", 0, false, false);
    ci_input_case(binary, "\n\n", "name> \nnext> \n", 0, false, false);
    ci_input_case(binary, "first\nlast", "name> first\nnext> last\n", 0, false, false);
    ci_input_case(binary, "first\n", "name> first\nnext> EOF\n", 2, false, false);
    char *long_data = malloc(16384 + 6), *long_expected = malloc(16384 + 20);
    assert(long_data && long_expected);
    for (size_t i = 0; i < 8192; ++i) memcpy(long_data + 2 * i, "я", 2);
    strcpy(long_data + 16384, "\nend\n");
    strcpy(long_expected, "name> "); memcpy(long_expected + 6, long_data, 16384);
    strcpy(long_expected + 16390, "\nnext> end\n");
    ci_input_case(binary, long_data, long_expected, 0, false, false);
    free(long_data); free(long_expected);
    ci_input_case(binary, "", "", -1, false, false);
    ci_input_case(binary, "unused\n", "", -1, false, true);
    ci_input_case(binary, "ready\n\n", "ready\nnext> \n", 0, true, false);
    free(binary); return 0;
}
