# `core::reflect`

Reflection describes resolved Encore types during compilation. A normal `for`
over fields or variants specializes its body for each concrete member type.
Application types do not need a derive or a serialization trait.

```encore
import core::reflect
import std::io::println

struct Position { x: f32 y: f32 }

fn describe[T](value: T) -> () {
    let info = reflect::type_info[T]()
    println(info.name())
    for field in info.fields() {
        println(field.name())
        println(field.type().name())
    }
}
```

`TypeInfo` exposes `name`, `kind`, `fields`, `variants`, `is_template[Template]`,
`argument(index)` and a conservative inline `size_bound`. `Kind` distinguishes
scalar widths, strings, structs, tuples, enums, owning nodes and pointers.
Type-dependent `match info.kind()` and `if info.is_template[...]()` branches
are selected before their concrete bodies are checked.

A `FieldInfo[Owner, Value]` has `name`, `type`, `index`, `get(owner)` and
`attribute(key)`. Field reads follow ordinary typed ownership rules. Indices
describe declaration order; they are not persistent asset identifiers.
String annotations such as `#serialize(rename = "stored_name")` are available
as `field.attribute("serialize.rename")`.

`VariantInfo[Owner, Value]` exposes `name`, `type`, `has_payload`,
`is_active(owner)`, `get(owner)` and `construct(payload)`. `get` returns an
`Option[Value]`; variants without a payload use `()`.

Decoders use a `Builder[T]` to collect fields. `set(field, value)` checks the
field's concrete value type. `finish()` returns `Result[T, BuildError]`, with
`BuildError::MissingField(name)` if a field was never supplied. A partially
initialized value is never exposed.

Metadata and heterogeneous sequences are compile-time values. They cannot be
stored as runtime collections or returned as runtime type descriptors. Generic
functions using reflection retain their structured bodies in package metadata
and are specialized when called with concrete types, including across packages.

The `serialize` package supplies `Serializer[Output]`, `Deserializer[Value]`,
`Error` and `Limits`. Each format implements its own traversal using reflection;
there is no shared visitor protocol. The `json` and `binary` packages provide
`encode(value)`, `decode[T](input)` and configurable `encode_with` / `decode_with`.
See their package READMEs for wire representations and limits.
