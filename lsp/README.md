# Encore LSP

An Encore language server implemented in Encore.

Current server capabilities:

- JSON-RPC framing over stdio.
- `initialize`, `shutdown`, `exit`.
- `textDocument/didOpen`, `textDocument/didChange`, `textDocument/didClose`.
- `textDocument/documentSymbol` for `fn`, `struct`, `enum`, `trait`, `impl`.
- `textDocument/completion` with Encore keywords and common declarations.
- Basic diagnostics for unmatched braces.

Run from this directory:

```sh
encore build
./target/debug/encore_lsp
```

