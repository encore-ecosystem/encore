fn matrix_value(i: usize, j: usize) -> f64 {
    let sum = i + j;
    1.0 / (sum * (sum + 1) / 2 + i + 1) as f64
}

fn multiply_av(values: &[f64]) -> Vec<f64> {
    (0..values.len())
        .map(|i| {
            values
                .iter()
                .enumerate()
                .map(|(j, value)| matrix_value(i, j) * value)
                .sum()
        })
        .collect()
}

fn multiply_atv(values: &[f64]) -> Vec<f64> {
    (0..values.len())
        .map(|i| {
            values
                .iter()
                .enumerate()
                .map(|(j, value)| matrix_value(j, i) * value)
                .sum()
        })
        .collect()
}

fn multiply_ata(values: &[f64]) -> Vec<f64> {
    multiply_atv(&multiply_av(values))
}

fn main() {
    let size = std::hint::black_box(900_usize);
    let mut u = vec![1.0_f64; size];
    let mut v = u.clone();
    for _ in 0..10 {
        v = multiply_ata(&u);
        u = multiply_ata(&v);
    }
    let vbv: f64 = u.iter().zip(&v).map(|(left, right)| left * right).sum();
    let vv: f64 = v.iter().map(|value| value * value).sum();
    println!("{}", (vbv * 1_000_000.0 / vv) as u64);
}
