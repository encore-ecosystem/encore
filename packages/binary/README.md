# binary

A portable, versioned value codec using `core::reflect` and `serialize`.

```encore
let bytes = binary::encode(value)?
let restored = binary::decode[MyType](bytes)?
```

`encode_with` and `decode_with` accept options with `serialize::Limits`.
`BinarySerializer[Value]` owns its input value; `BinaryDeserializer[Value]`
owns a `Vec[u8]`. They implement the two `serialize` contracts.

The header is `EBS1`, version `u16(1)`, flags `u16(0)`. All numbers are little
endian. Every value has a one-byte logical type and an eight-byte payload length.
Records contain a field count followed by `(name hash, value block)` entries.
Names use FNV-1a 64-bit with offset `14695981039346656037`; schema collisions are
errors. Unknown fields can be skipped using block lengths. Optional missing
fields become `None`; other missing fields are errors. Declaration order does
not serve as a field identifier. Renaming a field changes its wire identity.

Numeric vectors use a single element tag and packed numeric payload. Floats
retain every IEEE bit, including signed zero and NaN payloads. Strings are
validated UTF-8. Pointer values are unsupported. Owning handles serialize their
contents; sharing and cycles are not a wire-level identity protocol.

Decoding validates block lengths, counts, duplicate known fields, type tags,
version, UTF-8 and resource limits before allocating collections. Increase the
limits explicitly for large assets. This format is for values; it is not a raw
memory image of Encore objects.

Preserve a field's stored name while renaming its Encore member:

```encore
struct Asset {
    #serialize(rename = "old_name")
    name: str
}
```
