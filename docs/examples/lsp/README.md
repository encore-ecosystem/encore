# Encore LSP

An Encore language server implemented in Encore.

Current server capabilities:

- JSON-RPC framing over stdio.
- `initialize`, `shutdown`, `exit`.
- `textDocument/didOpen`, `textDocument/didChange`, `textDocument/didSave`, `textDocument/didClose`.
- `textDocument/definition` and `textDocument/declaration` for symbols in open documents, indexed workspace files and resolved workspace imports.
- `textDocument/implementation` for `impl Type` / `impl Trait` symbols in open documents and indexed workspace files.
- `textDocument/hover` for identifiers and declarations from open documents, indexed workspace files and resolved workspace imports.
- `textDocument/signatureHelp` for function calls in open documents and indexed workspace files.
- `textDocument/references` across open documents and indexed workspace files, using workspace import resolution for top-level symbols.
- `textDocument/documentHighlight` for same-document identifiers.
- `textDocument/prepareRename` and `textDocument/rename` across open documents and indexed workspace files, including import-based top-level symbol usages.
- `textDocument/documentSymbol` for `fn`, `struct`, `enum`, `trait`, `impl`.
- `workspace/symbol` over open documents and indexed workspace project sources discovered from `encore.toml`.
- `textDocument/completion` with Encore keywords and declarations from open documents and indexed workspace files.
- `textDocument/documentLink` for import paths, including file targets resolved through workspace project/module discovery.
- `textDocument/foldingRange` for brace-delimited blocks.
- `textDocument/selectionRange` for identifier selections.
- `textDocument/semanticTokens/full` for lexical semantic highlighting.
- `textDocument/formatting` and `textDocument/rangeFormatting` for trailing whitespace cleanup.
- Push and pull diagnostics for lexer, structural and basic semantic errors, including unresolved imports, unresolved calls, unknown types and call arity mismatches.
- `textDocument/prepareCallHierarchy`, `callHierarchy/outgoingCalls`, `callHierarchy/incomingCalls` for callable symbols.

## Source Layout

- `src/main.enq`: JSON-RPC server loop, request dispatch and feature handlers.
- `src/protocol.enq`: LSP framing, response/notification writers and JSON/LSP builders.
- `src/paths.enq`: file URI and path helpers.
- `src/text.enq`: text scanning, range support and identifier utilities.
- `src/tokens.enq`: Encore token classification helpers for semantic tokens.

Run from this directory:

```sh
uv run encore-py build
./target/debug/lsp
```
