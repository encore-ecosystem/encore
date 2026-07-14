typedef void (*encore_handler)(void);

extern unsigned int main(void);
extern unsigned int _stack_top;

void reset_handler(void) {
    volatile unsigned int status = main();
    (void)status;
    for (;;) {
    }
}

__attribute__((section(".vectors"), used))
const encore_handler encore_vectors[] = {
    (encore_handler)&_stack_top,
    reset_handler,
};
