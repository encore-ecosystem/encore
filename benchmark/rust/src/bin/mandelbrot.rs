#[inline(never)]
fn escape_iterations(cx: f64, cy: f64) -> u32 {
    let mut zx = 0.0_f64;
    let mut zy = 0.0_f64;
    let mut iteration = 0_u32;
    while iteration < 120 && zx * zx + zy * zy <= 4.0 {
        let next_x = zx * zx - zy * zy + cx;
        zy = 2.0 * zx * zy + cy;
        zx = next_x;
        iteration += 1;
    }
    iteration
}

fn main() {
    let width = std::hint::black_box(2000_u32);
    let height = 1400_u32;
    let mut checksum = 0_u64;
    for y in 0..height {
        let cy = y as f64 * 2.4 / height as f64 - 1.2;
        for x in 0..width {
            let cx = x as f64 * 3.5 / width as f64 - 2.5;
            checksum += escape_iterations(cx, cy) as u64;
        }
    }
    println!("{checksum}");
}
