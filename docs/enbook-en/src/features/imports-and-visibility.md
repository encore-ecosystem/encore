# Imports and Visibility

Items are private unless marked `pub`. Import a module path, one item, a
group, or `*`; `as` assigns a local alias. Package dependencies still belong
in `encore.toml`—an import never downloads a package implicitly.

```encore
{{#include ../../examples/guide/src/features/mod.enq:imports}}
```

