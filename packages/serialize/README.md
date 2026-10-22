# serialize

Format-independent `Serializer[Output]` and `Deserializer[Value]` contracts.
Codec objects own their source values or encoded input. Formats implement their
own representation and expose convenient `encode` / `decode` functions.

The package also provides structured `Error` values and configurable `Limits`.
It depends only on the compiler-provided core library and does not prescribe a
wire format or require traits on application data types.

```encore
pub trait Serializer[Output] {
    fn serialize(self: Self) -> Result[Output, Error]
}
pub trait Deserializer[Value] {
    fn deserialize(self: Self) -> Result[Value, Error]
}
```

`json::JsonSerializer[Value]` owns a value and produces a string;
`json::JsonDeserializer[Value]` owns a string and constructs `Value`.
The `binary` package follows the same pattern with `Vec[u8]`.
Their `encode` / `decode` helpers construct and run these codec objects.

A user format can implement the same two traits and inspect fields through
`core::reflect`. See the standalone
[comma codec](../../tests/fixtures/reflection_codecs/custom/src/lib.enq) for
encoding and typed construction with `reflect::Builder`, without JSON or a
common format backend.
