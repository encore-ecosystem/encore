# EHIR Examples

Examples are packaged as standalone refrain projects. From inside any example directory you can run:

```sh
ehir
```

Each example contains `src/main.ehir`. `refrains/` is optional.

Examples are ordered from simple to low-level:

- `01_basics`: imports, externs, structs, calls, literals
- `02_control_flow`: `cbr`, `br`, `phi`, `switch`
- `03_enums_and_match`: enum construction and `match`
- `04_traits_and_impls`: traits, impls and trait dispatch
- `05_memory_and_pointers`: `salloc`, `store`, `load`, `getfieldptr`, `gep`, `hrealloc`, `hfree`, `pcast`
- `06_capture_and_smart_pointers`: `cap*` instructions, `cpos`, and `Box[T]`
- `07_trait_bounds`: `where` bounds on traits and impls
- `08_reflection`: current runtime reflection lowering shape in textual EHIR
- `09_print`: tiny smoke example with builtin `print`
- `latest`: current latest smoke example

Notes:

- EHIR source entrypoint is `src/main.ehir`.
- `;` starts a one-line comment in textual EHIR.
- These examples are parser-valid showcases of the language surface.
