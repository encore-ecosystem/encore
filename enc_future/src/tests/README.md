Each `.enq` file in this folder is an executable unit test.

Contract:
- file must define `fn main() -> u32`
- `0_u32` means PASS
- non-zero means FAIL

Run with:
`encore test`
