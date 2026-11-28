# EHIR bytecode

The public EHIR library and command-line compiler are in [ehir](ehir/).
The other packages provide typed IR and verification ([ehir-core](ehir-core/)),
LLVM emission ([ehir-llvm-backend](ehir-llvm-backend/)), direct execution
([ehir-interpret](ehir-interpret/)) and native debug objects ([ehir-dbg](ehir-dbg/)).

Build any tool from its package directory with `encore build`. The sources use
the shared libraries in [packages](../packages/). The Encore compiler imports
`ehirlib` through its root manifest.
