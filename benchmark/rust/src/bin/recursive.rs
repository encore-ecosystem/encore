#[inline(never)]
fn fibonacci(n: u32) -> u64 {
    if n < 2 {
        return n as u64;
    }
    fibonacci(n - 1) + fibonacci(n - 2)
}

fn main() {
    let n = std::hint::black_box(40_u32);
    println!("{}", fibonacci(n));
}
