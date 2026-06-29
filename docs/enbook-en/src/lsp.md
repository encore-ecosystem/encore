# Language Server

Encore ships a stdio language server through:

```sh
encore-py lsp
```

or, for local development inside this repository:

```sh
uv run --project /home/meshushkevich/Projects/2E-encore/encore encore-py lsp
```

## Workspace Model

The server uses the same Encore workspace graph as the compiler:

- project root discovery through `encore.toml`;
- `RefrainManager` for import and dependency resolution;
- source overrides for open unsaved editor buffers;
- per-project workspace caching, invalidated only when document contents change.

That keeps interactive requests cheap after the first workspace build.

## Supported Features

Current `encore-py lsp` supports:

- hover;
- declaration and definition;
- implementation lookup for traits, structs, enums and impl methods;
- references;
- document highlights;
- document symbols and workspace symbols;
- completion for visible symbols, local names, import roots and `Type::member`;
- signature help for calls;
- rename with prepare-rename;
- folding ranges;
- selection ranges;
- document links for imports;
- semantic tokens;
- document formatting and range formatting;
- pull diagnostics (`textDocument/diagnostic`, `workspace/diagnostic`);
- push diagnostics on save;
- call hierarchy.

## Resolution Strategy

The server is not a mock layer. It uses real project data:

- top-level navigation is resolved through the Encore symbol table;
- imports are resolved through the workspace import graph;
- references and rename use token positions plus symbol-aware binding matching;
- signature help and call hierarchy use token-level call detection over real
  Encore source.

This means editor features follow the same module graph and symbol visibility
rules as the compiler, instead of relying on string-only heuristics.
