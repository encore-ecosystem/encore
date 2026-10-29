# EHIR core

Backend-independent IR, validation, preparation, typed values and serialization.
The core has no dependency on Encore's frontend, the compiler facade or LLVM.

The canonical `ModuleBundle` contains values whose `Variable.typ` is a mandatory
`Type`, including its representation and generic arguments. SSA references are
bound while parsing; instruction results require explicit types. There is no
post-parse type propagation or indexed graph conversion in preparation or LLVM.
`FieldSelector` is separate from SSA values; enum tags and unit literals have
explicit value kinds. Validation rejects undefined, duplicate and inconsistently
typed SSA values. The optional indexed `TypedProgram` export remains available
for clients that need stable value and type IDs.

Fallible `try_parse_*` entrypoints return errors. Legacy parser names remain as
compatibility wrappers. The compiler facade uses the fallible entrypoints.
`Backend`, `CompileOptions`, `PreparedProgram` and diagnostics define the common
extension boundary. Backend capabilities decide which target layouts are valid.

Prepared function records use versioned typed binary serialization with bounded
decoding, context identities and SSA validation. Storage adapters implement
`PreparedFunctionStore`; the adapter owns locks, integrity checks and pruning.
