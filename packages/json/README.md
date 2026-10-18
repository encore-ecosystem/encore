# json

Reusable JSON parser and formatter for Encore.

The package exposes a small DOM-like API:

- `Json` values: `Null`, `Bool`, `Number`, `String`, `Array`, `Object`.
- `parse(input) -> Result[Json, ParseError]`.
- `stringify(value) -> str`.
- Object/array accessors through `get`, `index`, `as_str`, `as_bool`, `as_number`.

Numbers are stored as source text to avoid lossy coercion at parse time.

Typed values can use `encode(value)` and `decode[MyType](text)` without a derive
or a trait implementation on `MyType`:

```encore
let text = json::encode_with(value, json::EncodeOptions::new().pretty(2))?
let restored = json::decode[MyType](text)?
```

`JsonSerializer[Value]::new(value)` implements `serialize::Serializer[str]`;
`JsonDeserializer[Value]::new(text)` implements `serialize::Deserializer[Value]`.
Formats own their traversal through `core::reflect`. `encode_with` and
`decode_with` accept options with configurable `serialize::Limits`.

Records are objects; tuples and vectors are arrays. `Option` uses a value or
`null`. Enums use an external tag: unit variants are strings and payload
variants are single-entry objects. Dictionaries require string keys. Missing
optional fields become `None`, unknown fields are skipped, and duplicate known
fields are errors. Shared owning handles are serialized by contents.

Integer decoding checks the requested width. Float conversion uses the C
numeric locale and directly rounds to the requested float width. JSON rejects
NaN and infinity; use `binary` when their exact IEEE representations matter.
Typed decoding checks input, depth, collection and conservative allocation
budgets before the parser builds its tree. The existing `Json`, `parse` and
`stringify` APIs remain available.

A field can use `#serialize(rename = "stored_name")` to override its JSON name.
Duplicate serialized names are schema errors.
