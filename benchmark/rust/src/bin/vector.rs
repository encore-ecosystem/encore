fn main() {
    const LENGTH: usize = 5_000_000;
    let mut values = Vec::with_capacity(LENGTH);
    for index in 0..LENGTH {
        values.push((index as u64).wrapping_mul(2_654_435_761_u64) ^ 0xa5a5_a5a5_u64);
    }

    let mut checksum = 0_u64;
    for round in 0_u64..8_u64 {
        for value in &mut values {
            let next = value
                .wrapping_mul(1_664_525_u64)
                .wrapping_add(1_013_904_223_u64)
                .wrapping_add(round);
            *value = next;
            checksum = checksum.wrapping_add(next);
        }
    }

    println!("{checksum}");
}
