struct Node {
    value: i64,
    children: Vec<Node>,
}

fn make_tree(depth: u32, value: i64) -> Node {
    let mut children = Vec::with_capacity(2);
    if depth > 0 {
        children.push(make_tree(depth - 1, value * 2 - 1));
        children.push(make_tree(depth - 1, value * 2));
    }
    Node { value, children }
}

fn check_tree(node: &Node) -> i64 {
    node.value + node.children.iter().map(check_tree).sum::<i64>()
}

fn main() {
    let maximum_depth = std::hint::black_box(15_u32);
    let mut checksum = check_tree(&make_tree(maximum_depth + 1, 0));
    let long_lived = make_tree(maximum_depth, 0);
    let mut depth = 4_u32;
    while depth <= maximum_depth {
        let iterations = 1_usize << (maximum_depth - depth + 2);
        for index in 0..iterations {
            checksum += check_tree(&make_tree(depth, index as i64));
            checksum += check_tree(&make_tree(depth, -(index as i64)));
        }
        depth += 2;
    }
    checksum += check_tree(&long_lived);
    println!("{checksum}");
}
