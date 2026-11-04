#ifndef ENCORE_COMPILER_COMMAND_TIMING_H
#define ENCORE_COMPILER_COMMAND_TIMING_H
extern uint64_t encore_clock_ns(uint8_t);
static uint64_t encore_compiler_command_started_ns;
void encore_compiler_command_begin(void) {
  encore_compiler_command_started_ns = encore_clock_ns(1);
}
uint64_t encore_compiler_command_elapsed_ms(void) {
  uint64_t now = encore_clock_ns(1);
  return encore_compiler_command_started_ns != 0 &&
                 now >= encore_compiler_command_started_ns
             ? (now - encore_compiler_command_started_ns) / 1000000
             : 0;
}
#endif
