fn main() {
    let mut value = std::hint::black_box(0x9e37_79b9_7f4a_7c15_u64);
    let mut checksum = 0_u64;

    for index in 0_u64..100_000_000_u64 {
        value ^= value << 13;
        value ^= value >> 7;
        value ^= value << 17;
        value = value.wrapping_add(index.wrapping_mul(0x9e37_79b9_u64));
        checksum = checksum.wrapping_add(value ^ index);
    }

    println!("{checksum}");
}
