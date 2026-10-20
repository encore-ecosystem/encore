# Imports and Visibility

Items are private unless marked `pub`. Import a module path, one item, a
group, or `*`; `as` assigns a local alias. Package dependencies still belong
in `encore.toml`—an import never downloads a package implicitly.

Private top-level declarations are visible within their module. Inherent
methods have a narrower boundary: without `pub`, they are accessible only
inside an `impl` of their declaring type. Being in the same file does not
grant another type or a free function access to a private method.

```encore
{{#include ../../examples/guide/src/features/mod.enq:imports}}
```
