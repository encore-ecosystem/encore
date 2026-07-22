#[derive(Clone, Copy)]
struct Body {
    x: f64,
    y: f64,
    z: f64,
    vx: f64,
    vy: f64,
    vz: f64,
    mass: f64,
}

fn interact(left: &mut Body, right: &mut Body, dt: f64) {
    let dx = right.x - left.x;
    let dy = right.y - left.y;
    let dz = right.z - left.z;
    let scale = dt / (dx * dx + dy * dy + dz * dz + 1.0);
    let left_scale = right.mass * scale;
    let right_scale = left.mass * scale;
    left.vx += dx * left_scale;
    left.vy += dy * left_scale;
    left.vz += dz * left_scale;
    right.vx -= dx * right_scale;
    right.vy -= dy * right_scale;
    right.vz -= dz * right_scale;
}

fn advance(body: &mut Body, dt: f64) {
    body.x += dt * body.vx;
    body.y += dt * body.vy;
    body.z += dt * body.vz;
}

fn main() {
    let mut a = Body {
        x: 0.0,
        y: 0.0,
        z: 0.0,
        vx: 0.001,
        vy: -0.002,
        vz: 0.003,
        mass: 3.0,
    };
    let mut b = Body {
        x: 1.0,
        y: 0.2,
        z: -0.1,
        vx: -0.003,
        vy: 0.001,
        vz: 0.002,
        mass: 1.7,
    };
    let mut c = Body {
        x: -0.4,
        y: 1.1,
        z: 0.3,
        vx: 0.002,
        vy: 0.003,
        vz: -0.001,
        mass: 2.1,
    };
    let mut d = Body {
        x: 0.3,
        y: -0.8,
        z: 1.2,
        vx: -0.001,
        vy: -0.002,
        vz: 0.002,
        mass: 0.9,
    };
    let mut e = Body {
        x: -1.0,
        y: -0.5,
        z: -0.7,
        vx: 0.003,
        vy: -0.001,
        vz: -0.002,
        mass: 1.3,
    };
    let dt = 0.00001_f64;
    let steps = std::hint::black_box(6_000_000_u32);
    for _ in 0..steps {
        interact(&mut a, &mut b, dt);
        interact(&mut a, &mut c, dt);
        interact(&mut a, &mut d, dt);
        interact(&mut a, &mut e, dt);
        interact(&mut b, &mut c, dt);
        interact(&mut b, &mut d, dt);
        interact(&mut b, &mut e, dt);
        interact(&mut c, &mut d, dt);
        interact(&mut c, &mut e, dt);
        interact(&mut d, &mut e, dt);
        advance(&mut a, dt);
        advance(&mut b, dt);
        advance(&mut c, dt);
        advance(&mut d, dt);
        advance(&mut e, dt);
    }
    let total = a.x.abs()
        + a.y.abs()
        + a.z.abs()
        + b.x.abs()
        + b.y.abs()
        + b.z.abs()
        + c.x.abs()
        + c.y.abs()
        + c.z.abs()
        + d.x.abs()
        + d.y.abs()
        + d.z.abs()
        + e.x.abs()
        + e.y.abs()
        + e.z.abs();
    println!("{}", (total * 1_000_000_000.0) as u64);
}
