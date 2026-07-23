# Language Construct Examples

This chapter is a syntax-oriented companion to [Language Basics](language-basics.md).
It gives a small example of every source-language construct accepted by the
Encore frontend. Examples are intentionally independent: names such as
`Option`, `Vec`, and `println` require the corresponding import when copied
into a program.

## Comments and documentation

Encore supports line comments, block comments, module documentation, and item
documentation:

```enq
//! Documentation for this module.

/* A block comment. */
/// Documentation for `answer`.
pub fn answer() -> u32 {
    // A line comment.
    ret 42_u32
}
```

## Imports and visibility

```enq
import std::io::println
import core::option::Option as Maybe
import std::{fmt::Debug, vec::Vec}
import core::testing::*

pub import std::string::String
```

`pub` also exports declarations and methods:

```enq
pub struct PublicValue {
    value: u32
}

pub fn make_value() -> PublicValue {
    ret PublicValue{1_u32}
}
```

## Attributes

Attributes precede functions. Multiple values may appear in one attribute:

```enq
#attr(test)
fn addition_works() -> bool {
    ret 2_u32 + 2_u32 == 4_u32
}

#attr(safe, inline)
fn small_helper(value: u32) -> u32 {
    ret value + 1_u32
}
```

## Bindings, assignment, and return

Bindings may be inferred or explicitly typed. Only `mut` bindings may be
reassigned:

```enq
fn count() -> u32 {
    let inferred = 1_u32
    let explicit: u32 = 2_u32
    let mut total = inferred

    total = total + explicit
    total += 1_u32
    total -= 1_u32
    total *= 2_u32
    total **= 2_u32
    total /= 2_u32
    total %= 3_u32
    total &= 255_u32
    total |= 1_u32
    total ^= 1_u32
    total <<= 1_u32
    total >>= 1_u32
    ret total
}
```

An expression may also be evaluated only for its effects:

```enq
println("done")
```

## Literals

```enq
let enabled = true
let disabled = false

let unsigned = 255_u8
let count = 12_u32
let large = 12_u64
let index = 12_usize
let signed = -12_i32
let ratio = 1.5_f32
let precise = 1.5_f64

let text = "Encore"
let escaped = "line one\nline two"
let unit = ()
let pair = ("Encore", 14_u32)

let array = [1_u32, 2_u32, 3_u32]
let repeated = [0_u8; 16]
let vector = vec![1_u32, 2_u32, 3_u32]
```

Tuples and arrays support indexing:

```enq
let name = pair.0
let second = array[1_usize]
```

## String formatting

Formatted strings interpolate expressions. `format!` accepts positional
arguments:

```enq
let language = "Encore"
let version = 14_u32
let label = f"{language} 0.1.{version}"
let same = format!("{} 0.1.{}", language, version)
```

## Declarative macros

`macro_rules!` defines token-based expression macros. A rule can capture an
expression with `expr` or an identifier with `ident`:

```enq
macro_rules! add_one {
    ($value:expr) => ($value + 1_u32);
}

macro_rules! twice {
    ($value:ident) => ($value + $value);
}

let answer = add_one!(41_u32)
let half = 21_u32
let whole = twice!(half)
```

## Unary, binary, and cast expressions

```enq
let negated = -4_i32
let unchanged = +4_i32
let inverted = !false
let complemented = ~0_u32
let mut cursor = 0_usize
let next = ++cursor
let previous = --cursor

let arithmetic = (2_u32 + 3_u32) * 4_u32 / 2_u32
let remainder = arithmetic % 3_u32
let power = 2_u32 ** 8_u32

let equal = arithmetic == 10_u32
let different = arithmetic != remainder
let ordered = arithmetic > remainder && remainder <= 2_u32
let either = equal || different

let bits = (1_u32 << 4_u32) | 3_u32
let shifted = bits >> 1_u32
let masked = shifted & 7_u32
let toggled = masked ^ 1_u32

let widened = arithmetic as u64
```

Parentheses override normal precedence.

## Type forms

Types include primitives, paths, generic applications, tuples, fixed-size
arrays, dynamic traits, and the low-level pointer/reference forms used by
runtime-facing code:

```enq
let flag: bool = true
let byte: u8 = 1_u8
let number: u32 = 2_u32
let signed: i32 = -2_i32
let size: usize = 3_usize
let text: str = "text"

let pair: (u32, str) = (1_u32, "one")
let bytes: [u8; 4] = [0_u8; 4]
let values: Vec[u32] = Vec[u32]::new()
let callback: dyn Handler = handler as dyn Handler
```

Raw pointer types (`T*`), graph handles (`T<H>`), stack handles (`T<S>`), and
borrow/reference spellings (`T&` or `&T`) are primarily compiler and runtime
building blocks. Use safe library abstractions unless implementing such a
building block:

```enq
extern fn inspect_raw(value: u8*) -> u32
extern fn inspect_graph(value: Node<H>) -> u32
extern fn inspect_stack(value: Node<S>) -> u32
extern fn inspect_borrow(value: str&) -> u32
```

## Functions and calls

```enq
fn add(lhs: u32, rhs: u32) -> u32 {
    ret lhs + rhs
}

fn identity[T](value: T) -> T {
    ret value
}

let sum = add(2_u32, 3_u32)
let word = identity[str]("generic")
```

Functions returning unit may use `()`:

```enq
fn announce() -> () {
    println("ready")
    ret ()
}
```

Native functions are declared without a body:

```enq
extern fn native_clock() -> u64
```

## Structs

Encore supports named-field, tuple, and unit structs:

```enq
struct Point {
    x: i32
    y: i32
}

struct Pair(u32, u32)
struct Marker;

let point = Point{10_i32, 20_i32}
let pair = Pair{1_u32, 2_u32}
let marker = Marker{}

let x = point.x
let first = pair.0
```

Generic structs put their parameters after the name:

```enq
struct Box[T] {
    value: T
}

let boxed = Box[u32]{7_u32}
```

## Enums and patterns

Variants may be unit, tuple-like, or named-field shapes:

```enq
enum Message[T] {
    Quit
    Write(T)
    Move {
        x: i32
        y: i32
    }
}
```

`match` accepts enum patterns, literal patterns, and `_`:

```enq
fn describe(message: Message[u32]) -> str {
    match message {
        Message[u32]::Quit => { ret "quit" }
        Message[u32]::Write(value) => {
            if value == 0_u32 { ret "zero" }
            ret "value"
        }
        Message[u32]::Move(position) => {
            let _ignored = position
            ret "move"
        }
    }
}

fn classify(value: i32) -> str {
    match value {
        -1_i32 => { ret "negative one" }
        0_i32 => { ret "zero" }
        _ => { ret "other" }
    }
}
```

A match arm may be a single expression when `match` itself is used as an
expression:

```enq
let label = match enabled {
    true => "on"
    false => "off"
}
```

String and floating-point literal patterns are also syntactically supported:

```enq
match name {
    "Encore" => println("language")
    _ => println("other")
}

match ratio {
    1.5_f32 => println("one and a half")
    _ => println("another value")
}
```

## Methods and associated functions

An inherent implementation uses `impl for Type`. `Self` names its target:

```enq
struct Counter {
    value: usize
}

impl for Counter {
    pub fn new(value: usize) -> Self {
        ret Self{value}
    }

    pub fn increment(mut self: Self) -> Self {
        self.value += 1_usize
        ret self
    }

    pub fn get(self: Self) -> usize {
        ret self.value
    }
}

let counter = Counter::new(0_usize)
let next = counter.increment()
let value = Counter::get(next)
```

Calls may supply method generic arguments:

```enq
let converted = value.convert[u64]()
```

## Traits, bounds, and trait objects

```enq
trait Named {
    fn name(self: Self) -> str
}

trait Identified: Named {
    fn id(self: Self) -> u64
}

struct User {
    id: u64
    name: str
}

impl Named for User {
    fn name(self: User) -> str {
        ret self.name
    }
}

impl Identified for User {
    fn id(self: User) -> u64 {
        ret self.id
    }
}
```

Generic parameters may have one or several bounds:

```enq
fn render[T:Named](value: T) -> str {
    ret value.name()
}

fn same_and_named[T:Named + Eq[T]](lhs: T, rhs: T) -> bool {
    ret lhs == rhs
}
```

Use `dyn Trait` for dynamic dispatch:

```enq
fn dynamic_name(value: dyn Named) -> str {
    ret value.name()
}

let erased = User{7_u64, "Ada"} as dyn Named
let name = dynamic_name(erased)
```

## Conditional statements

```enq
if score > 90_u32 {
    println("excellent")
} elif score > 60_u32 {
    println("pass")
} else {
    println("retry")
}
```

`if` may produce a value when every branch has a tail expression:

```enq
let grade = if score > 90_u32 {
    "A"
} elif score > 60_u32 {
    "C"
} else {
    "F"
}
```

Blocks can be expressions too:

```enq
let value = {
    let base = 40_u32
    base + 2_u32
}
```

## Loops

```enq
let mut index = 0_usize
while index < 3_usize {
    index += 1_usize
}

do {
    index -= 1_usize
} while index > 0_usize

loop {
    break
}

for value in vec![1_u32, 2_u32, 3_u32] {
    if value == 2_u32 { continue }
}

for value in 0_usize..10_usize {
    println(f"{value}")
}

for value in 0_usize..=10_usize {
    println(f"{value}")
}
```

Labels select an enclosing loop:

```enq
'outer: loop {
    loop {
        continue 'outer
    }
}

'search: while true {
    break 'search
}

'items: for item in items {
    if item.done() { break 'items }
}
```

## Context managers

`with` invokes the `ContextManager` implementation and binds the value returned
by `with_enter`:

```enq
import core::ops::ContextManager

struct Resource {
    value: u32
}

impl ContextManager for Resource {
    fn with_enter(self: Resource) -> Resource { ret self }
    fn with_exit(self: Resource) -> bool { ret true }
}

with Resource{7_u32} as resource {
    println(f"value = {resource.value}")
}
```

## Error propagation

Postfix `?` returns an error-like value from the current function when the
operation fails:

```enq
fn load() -> Result[str, IoError] {
    let text = read_to_string("settings.toml")?
    ret Result[str, IoError]::Ok(text)
}
```

The exact success and error types are determined by the core operation traits.

## Asynchronous functions and `await`

```enq
async fn fetch() -> u32 {
    let first = await request_value()
    let second = await request_value()
    ret first + second
}
```

`await` is valid only in an asynchronous function. Calling an `async fn`
creates a future; it does not eagerly run the body.

Traits and implementations may also declare asynchronous methods:

```enq
trait Producer {
    async fn produce(self: Self) -> u32
}

impl Producer for Source {
    async fn produce(self: Source) -> u32 {
        ret await self.next()
    }
}
```

## Threads and `spawn`

```enq
fn worker(value: u32) -> u32 {
    ret value * 2_u32
}

let handle = spawn worker(21_u32)
let answer = handle.join()
```

Values moved to a spawned function must satisfy the thread-safety rules.

## Unsafe expressions and blocks

An unsafe operation can be scoped to one expression or a block:

```enq
let ticks = unsafe { native_clock() }

unsafe {
    let first = native_clock()
    let second = native_clock()
    println(f"elapsed = {second - first}")
}
```

Keep unsafe regions small and expose safe wrappers to application code.

## Embedded EHIR

EHIR blocks are a low-level compiler/runtime facility. A checked block starts
with `ehir`; operations that bypass safety checks require `unsafe ehir`:

```enq
fn constant() -> u32 {
    ehir {
        value: u32 = add 40_u32: u32, 2_u32: u32
    }
    ret value
}

fn raw_load(mut source: u32) -> u32 {
    unsafe ehir {
        loaded: u32 = load source: u32*
    }
    ret loaded
}
```

EHIR has its own instruction grammar; see
[Compiler Logic](compiler-logic.md) before using it. Prefer ordinary Encore
and library wrappers in application code.

## Paths, fields, calls, and indexing

These postfix forms may be chained:

```enq
let value = module::Type[u32]::new()
    .transform[str]("value")
    .items[0_usize]
    .name
```

Paths use `::`, generic arguments use `[...]`, member access uses `.`, calls
use `(...)`, and indexing uses `[...]`.
