# EHIR core

Backend-independent IR, validation, preparation, typed values and serialization.
The core has no dependency on Encore's frontend, the compiler facade or LLVM.

`TypedProgram` contains modules with indexed functions, types, symbols and SSA
values. A value has a mandatory `TypeId`; field selectors and enum variants have
distinct operand forms. Conversion from textual/legacy inputs rejects missing,
inconsistent and undefined values. Backend conversion checks reference bounds.

Fallible `try_parse_*` entrypoints return errors. Legacy parser names remain as
compatibility wrappers. The compiler facade uses the fallible entrypoints.
`Backend`, `CompileOptions`, `PreparedProgram` and diagnostics define the common
extension boundary. Backend capabilities decide which target layouts are valid.

Prepared function records use versioned typed binary serialization with bounded
decoding, context identities and reference checks. Storage adapters implement
`PreparedFunctionStore`; the adapter owns locks, integrity checks and pruning.
