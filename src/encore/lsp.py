from __future__ import annotations

import hashlib
import json
import re
import sys
import threading
from dataclasses import dataclass
from dataclasses import fields, is_dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

from ehir import EHIR_ProjectCompiler

from encore import __version__
from encore.compiler import EncoreCompiler
from encore.compiler.lexer.lexer import Lexer
from encore.compiler.lexer.tokens import LexerToken, TokenType
from encore.compiler.parser import statements as s
from encore.compiler.translator import EncoreToEHIRTranslator
from encore.utils.diagnostics import CompileDiagnostic, with_diagnostic_context
from encore.utils.manifest import ProjectManifest
from encore.workspace import RefrainData, RefrainManager, SymbolBinding

_KEYWORDS = (
    "as",
    "break",
    "continue",
    "do",
    "dyn",
    "ehir",
    "elif",
    "else",
    "enum",
    "extern",
    "false",
    "fn",
    "for",
    "if",
    "impl",
    "import",
    "in",
    "let",
    "loop",
    "match",
    "mut",
    "pub",
    "ret",
    "struct",
    "trait",
    "true",
    "unsafe",
    "while",
    "with",
)

_SEMANTIC_TOKEN_TYPES = (
    "keyword",
    "function",
    "type",
    "struct",
    "enum",
    "interface",
    "variable",
    "number",
    "string",
    "operator",
    "comment",
    "namespace",
)

SEM_KEYWORD = _SEMANTIC_TOKEN_TYPES.index("keyword")
SEM_FUNCTION = _SEMANTIC_TOKEN_TYPES.index("function")
SEM_TYPE = _SEMANTIC_TOKEN_TYPES.index("type")
SEM_STRUCT = _SEMANTIC_TOKEN_TYPES.index("struct")
SEM_ENUM = _SEMANTIC_TOKEN_TYPES.index("enum")
SEM_INTERFACE = _SEMANTIC_TOKEN_TYPES.index("interface")
SEM_VARIABLE = _SEMANTIC_TOKEN_TYPES.index("variable")
SEM_NUMBER = _SEMANTIC_TOKEN_TYPES.index("number")
SEM_STRING = _SEMANTIC_TOKEN_TYPES.index("string")
SEM_OPERATOR = _SEMANTIC_TOKEN_TYPES.index("operator")
SEM_COMMENT = _SEMANTIC_TOKEN_TYPES.index("comment")
SEM_NAMESPACE = _SEMANTIC_TOKEN_TYPES.index("namespace")

def path_to_uri(path: Path) -> str:
    return path.resolve().as_uri()


def uri_to_path(uri: str) -> Path:
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        raise RuntimeError(f"Unsupported URI scheme for Encore LSP: {uri}")
    return Path(unquote(parsed.path)).resolve()


def make_range(line: int | None, column: int | None, span_length: int | None) -> dict[str, object]:
    start_line = max(line or 0, 0)
    start_col = max(column or 0, 0)
    end_col = start_col + max(span_length or 1, 1)
    return {
        "start": {"line": start_line, "character": start_col},
        "end": {"line": start_line, "character": end_col},
    }


def make_edit_range(line: int, column: int, span_length: int = 0) -> dict[str, object]:
    start_col = max(column, 0)
    return {
        "start": {"line": max(line, 0), "character": start_col},
        "end": {"line": max(line, 0), "character": start_col + max(span_length, 0)},
    }


def symbol_kind(statement: s.Statement_TopLevel) -> int:
    if isinstance(statement, s.Statement_FunctionDefinition | s.FunctionSignature):
        return 12
    if isinstance(statement, s.Statement_StructureDefinition):
        return 23
    if isinstance(statement, s.Statement_EnumDefinition):
        return 10
    if isinstance(statement, s.Statement_Trait):
        return 11
    if isinstance(statement, s.Statement_Global):
        return 13
    return 13


def completion_kind(statement: s.Statement_TopLevel) -> int:
    if isinstance(statement, s.Statement_FunctionDefinition | s.FunctionSignature):
        return 3
    if isinstance(statement, s.Statement_StructureDefinition):
        return 7
    if isinstance(statement, s.Statement_EnumDefinition):
        return 13
    if isinstance(statement, s.Statement_Trait):
        return 8
    if isinstance(statement, s.Statement_Global):
        return 6
    return 9


def statement_name(statement: s.Statement_TopLevel) -> str | None:
    if isinstance(statement, s.Statement_FunctionDefinition):
        return statement.signature.name
    if isinstance(statement, s.FunctionSignature):
        return statement.name
    if isinstance(statement, s.Statement_StructureDefinition):
        return statement.signature.name
    if isinstance(statement, s.Statement_EnumDefinition):
        return statement.name
    if isinstance(statement, s.Statement_Trait):
        return statement.name
    if isinstance(statement, s.Statement_Global):
        return statement.name
    return None


def statement_span(statement: s.Statement_TopLevel | s.Statement) -> tuple[int | None, int | None, int | None]:
    line = getattr(statement, "line", None)
    column = getattr(statement, "column", None)
    span_length = getattr(statement, "span_length", None)
    if line is not None and column is not None:
        return line, column, span_length
    signature = getattr(statement, "signature", None)
    if signature is not None:
        return (
            getattr(signature, "line", None),
            getattr(signature, "column", None),
            getattr(signature, "span_length", None),
        )
    return line, column, span_length


def contains_position(node: object, line: int, character: int) -> bool:
    node_line = getattr(node, "line", None)
    node_col = getattr(node, "column", None)
    if node_line is None or node_col is None:
        return False
    if line != node_line:
        return False
    span_length = max(getattr(node, "span_length", None) or 1, 1)
    return node_col <= character < node_col + span_length


def walk_statement_nodes(value: object):
    if isinstance(value, s.Statement):
        yield value
    if isinstance(value, list):
        for item in value:
            yield from walk_statement_nodes(item)
        return
    if not is_dataclass(value):
        return
    for dataclass_field in fields(value):
        yield from walk_statement_nodes(getattr(value, dataclass_field.name))


def symbol_name_from_node(node: s.Statement) -> str | None:
    if isinstance(node, s.Expression_Path):
        return node.name
    if isinstance(node, s.Expression_Call):
        return node.name
    if isinstance(node, s.Statement_FunctionDefinition):
        return node.signature.name
    if isinstance(node, s.FunctionSignature):
        return node.name
    if isinstance(node, s.Statement_StructureDefinition):
        return node.signature.name
    if isinstance(node, s.Statement_EnumDefinition):
        return node.name
    if isinstance(node, s.Statement_Trait):
        return node.name
    if isinstance(node, s.Statement_Global):
        return node.name
    return None


def find_symbol_node(ast: list[s.Statement], line: int, character: int) -> s.Statement | None:
    candidates: list[s.Statement] = []
    for statement in ast:
        for node in walk_statement_nodes(statement):
            if contains_position(node, line, character) and symbol_name_from_node(node):
                candidates.append(node)
    if not candidates:
        return None
    candidates.sort(key=lambda node: (getattr(node, "span_length", None) or 1, getattr(node, "column", None) or 0))
    return candidates[0]


def find_project_root(path: Path) -> Path | None:
    for parent in [path.parent, *path.parents]:
        manifest_path = parent / ProjectManifest.default_filename()
        if manifest_path.exists():
            return parent.resolve()
    return None


def is_binary_project(root: Path) -> bool:
    return (root / "src" / "main.enq").exists()


def strip_generic_suffix(name: str) -> str:
    return name.split("[", 1)[0]


@dataclass
class _CachedWorkspace:
    root: Path
    target: RefrainData
    manager: RefrainManager


@dataclass(frozen=True)
class _BindingKey:
    module_id: Path
    line: int | None
    column: int | None
    span_length: int | None
    name: str


@dataclass
class _CallInfo:
    name: str
    is_method: bool
    active_parameter: int


@dataclass(frozen=True)
class _ImportTokenContext:
    token: LexerToken
    parts: tuple[str, ...]
    part_index: int

    @property
    def is_final_part(self) -> bool:
        return self.part_index == len(self.parts) - 1


@dataclass
class _SemanticContext:
    declaration_kinds: dict[tuple[int, int], int]
    visible_kinds: dict[str, int]
    import_token_kinds: dict[tuple[int, int], int]
    call_tokens: set[tuple[int, int]]


@dataclass
class _DiagnosticCacheEntry:
    signature: tuple[tuple[Path, str], ...]
    diagnostics: dict[Path, list[dict[str, object]]]


class EncoreLanguageServer:
    def __init__(self):
        self._shutdown_requested = False
        self._open_documents: dict[Path, str] = {}
        self._workspace_cache: dict[Path, _CachedWorkspace] = {}
        self._workspace_fallback_cache: dict[tuple[Path, tuple[Path, ...]], _CachedWorkspace] = {}
        self._token_cache: dict[Path, tuple[str, list[LexerToken]]] = {}
        self._diagnostic_cache: dict[Path, _DiagnosticCacheEntry] = {}
        self._diagnostic_jobs: set[tuple[Path, tuple[tuple[Path, str], ...]]] = set()
        self._state_lock = threading.RLock()
        self._write_lock = threading.Lock()
        self._lexer = Lexer()

    def run(self) -> int:
        while True:
            message = self._read_message()
            if message is None:
                return 0
            if "method" in message:
                self._handle_message(message)

    def _handle_message(self, message: dict[str, object]) -> None:
        method = message["method"]
        params = message.get("params", {})
        req_id = message.get("id")
        try:
            if method == "initialize":
                self._reply(req_id, self._handle_initialize(params))
                return
            if method == "initialized":
                return
            if method == "shutdown":
                self._shutdown_requested = True
                self._reply(req_id, None)
                return
            if method == "exit":
                raise SystemExit(0 if self._shutdown_requested else 1)
            if method == "textDocument/didOpen":
                self._did_open(params)
                return
            if method == "textDocument/didChange":
                self._did_change(params)
                return
            if method == "textDocument/didClose":
                self._did_close(params)
                return
            if method == "textDocument/didSave":
                self._did_save(params)
                return
            if method == "textDocument/definition":
                self._reply(req_id, self._definition(params))
                return
            if method == "textDocument/declaration":
                self._reply(req_id, self._definition(params))
                return
            if method == "textDocument/implementation":
                self._reply(req_id, self._implementation(params))
                return
            if method == "textDocument/hover":
                self._reply(req_id, self._hover(params))
                return
            if method == "textDocument/references":
                self._reply(req_id, self._references(params))
                return
            if method == "textDocument/documentHighlight":
                self._reply(req_id, self._document_highlights(params))
                return
            if method == "textDocument/prepareRename":
                self._reply(req_id, self._prepare_rename(params))
                return
            if method == "textDocument/rename":
                self._reply(req_id, self._rename(params))
                return
            if method == "textDocument/signatureHelp":
                self._reply(req_id, self._signature_help(params))
                return
            if method == "textDocument/documentSymbol":
                self._reply(req_id, self._document_symbols(params))
                return
            if method == "workspace/symbol":
                self._reply(req_id, self._workspace_symbols(params))
                return
            if method == "textDocument/completion":
                self._reply(req_id, self._completion(params))
                return
            if method == "textDocument/foldingRange":
                self._reply(req_id, self._folding_ranges(params))
                return
            if method == "textDocument/selectionRange":
                self._reply(req_id, self._selection_ranges(params))
                return
            if method == "textDocument/documentLink":
                self._reply(req_id, self._document_links(params))
                return
            if method == "textDocument/semanticTokens/full":
                self._reply(req_id, self._semantic_tokens(params))
                return
            if method == "textDocument/formatting":
                self._reply(req_id, self._document_formatting(params))
                return
            if method == "textDocument/rangeFormatting":
                self._reply(req_id, self._document_formatting(params))
                return
            if method == "textDocument/diagnostic":
                self._reply(req_id, self._document_diagnostic(params))
                return
            if method == "workspace/diagnostic":
                self._reply(req_id, self._workspace_diagnostic())
                return
            if method == "textDocument/prepareCallHierarchy":
                self._reply(req_id, self._prepare_call_hierarchy(params))
                return
            if method == "callHierarchy/outgoingCalls":
                self._reply(req_id, self._outgoing_calls(params))
                return
            if method == "callHierarchy/incomingCalls":
                self._reply(req_id, self._incoming_calls(params))
                return
            if req_id is not None:
                self._reply(req_id, None)
        except SystemExit:
            raise
        except Exception as exc:
            if req_id is None:
                self._notify(
                    "window/logMessage",
                    {"type": 1, "message": str(exc)},
                )
                return
            self._reply_error(req_id, code=-32603, message=str(exc))

    def _handle_initialize(self, _params: object) -> dict[str, object]:
        return {
            "capabilities": {
                "textDocumentSync": {
                    "openClose": True,
                    "change": 1,
                    "save": {"includeText": False},
                },
                "definitionProvider": True,
                "declarationProvider": True,
                "implementationProvider": True,
                "hoverProvider": True,
                "referencesProvider": True,
                "documentHighlightProvider": True,
                "documentSymbolProvider": True,
                "workspaceSymbolProvider": True,
                "renameProvider": {"prepareProvider": True},
                "signatureHelpProvider": {"triggerCharacters": ["(", ","]},
                "completionProvider": {
                    "resolveProvider": False,
                    "triggerCharacters": [" ", ":", ".", "_"],
                },
                "foldingRangeProvider": True,
                "selectionRangeProvider": True,
                "documentLinkProvider": {"resolveProvider": False},
                "documentFormattingProvider": True,
                "documentRangeFormattingProvider": True,
                "callHierarchyProvider": True,
                "diagnosticProvider": {"interFileDependencies": True, "workspaceDiagnostics": True},
                "semanticTokensProvider": {
                    "legend": {
                        "tokenTypes": list(_SEMANTIC_TOKEN_TYPES),
                        "tokenModifiers": ["declaration", "definition"],
                    },
                    "full": True,
                },
            },
            "serverInfo": {"name": "encore-py", "version": __version__},
        }

    def _did_open(self, params: dict[str, object]) -> None:
        text_document = params["textDocument"]
        path = uri_to_path(text_document["uri"])
        with self._state_lock:
            self._open_documents[path] = text_document["text"]
            self._invalidate_workspace(path)
            self._token_cache.pop(path.resolve(), None)

    def _did_change(self, params: dict[str, object]) -> None:
        text_document = params["textDocument"]
        path = uri_to_path(text_document["uri"])
        content_changes = params.get("contentChanges", [])
        if not content_changes:
            return
        with self._state_lock:
            self._open_documents[path] = content_changes[-1]["text"]
            self._invalidate_workspace(path)
            self._token_cache.pop(path.resolve(), None)

    def _did_close(self, params: dict[str, object]) -> None:
        text_document = params["textDocument"]
        path = uri_to_path(text_document["uri"])
        with self._state_lock:
            self._open_documents.pop(path, None)
            self._invalidate_workspace(path, invalidate_fallbacks=True)
            self._token_cache.pop(path.resolve(), None)
        self._notify("textDocument/publishDiagnostics", {"uri": path_to_uri(path), "diagnostics": []})

    def _did_save(self, params: dict[str, object]) -> None:
        text_document = params["textDocument"]
        path = uri_to_path(text_document["uri"])
        with self._state_lock:
            self._invalidate_workspace(path, invalidate_fallbacks=True)
        self._publish_project_diagnostics(path)

    def _definition(self, params: dict[str, object]) -> list[dict[str, object]] | None:
        path, line, character = self._request_position(params)
        target, manager = self._build_workspace(path)
        import_location = self._import_location_at_position(target, manager, path, line, character)
        if import_location is not None:
            return [import_location]
        binding = self._binding_at_position(target, path, line, character)
        if binding is None:
            return None
        location = self._binding_location(binding)
        return [location] if location is not None else None

    def _implementation(self, params: dict[str, object]) -> list[dict[str, object]]:
        path, line, character = self._request_position(params)
        target, _ = self._build_workspace(path)
        binding = self._binding_at_position(target, path, line, character)
        if binding is None:
            return []
        locations: list[dict[str, object]] = []
        seen: set[tuple[Path, int | None, int | None]] = set()
        for refrain in self._collect_refrains(target):
            for module_id, statements in refrain.symbols.local_ast_without_imports.items():
                for statement in statements:
                    if not isinstance(statement, s.Statement_Impl):
                        continue
                    if not self._impl_matches_binding(statement, binding):
                        continue
                    impl_binding = SymbolBinding(
                        name=repr(statement.struct),
                        source_name=repr(statement.struct),
                        module_id=module_id.resolve(),
                        statement=statement,
                        is_public=False,
                    )
                    location = self._binding_location(impl_binding)
                    if location is None:
                        continue
                    key = (
                        impl_binding.module_id,
                        location["range"]["start"]["line"],
                        location["range"]["start"]["character"],
                    )
                    if key in seen:
                        continue
                    seen.add(key)
                    locations.append(location)
        return locations

    def _hover(self, params: dict[str, object]) -> dict[str, object] | None:
        path, line, character = self._request_position(params)
        target, _ = self._build_workspace(path)
        binding = self._binding_at_position(target, path, line, character)
        if binding is None:
            return None
        hover_range = self._binding_name_range(binding) or make_range(*statement_span(binding.statement))
        return {
            "contents": {"kind": "plaintext", "value": repr(binding.statement)},
            "range": hover_range,
        }

    def _references(self, params: dict[str, object]) -> list[dict[str, object]]:
        path, line, character = self._request_position(params)
        target, _ = self._build_workspace(path)
        return self._reference_locations(target, path, line, character)

    def _document_highlights(self, params: dict[str, object]) -> list[dict[str, object]]:
        path, line, character = self._request_position(params)
        target, _ = self._build_workspace(path)
        token = self._token_at(path, line, character)
        if token is None or not self._token_can_reference(token):
            return []
        binding = self._binding_at_position(target, path, line, character)
        if binding is not None:
            refs = self._reference_locations(target, path, line, character)
            return [
                {"range": location["range"], "kind": 1}
                for location in refs
                if uri_to_path(location["uri"]).resolve() == path.resolve()
            ]
        return [{"range": self._token_range(token), "kind": 1}] + [
            {"range": self._token_range(other), "kind": 1}
            for other in self._same_document_token_occurrences(path, token.value)
            if other.line != token.line or other.column != token.column
        ]

    def _document_symbols(self, params: dict[str, object]) -> list[dict[str, object]]:
        path = uri_to_path(params["textDocument"]["uri"])
        target, _ = self._build_workspace(path)
        module_id = path.resolve()
        result: list[dict[str, object]] = []
        for statement in target.symbols.local_ast_without_imports.get(module_id, []):
            if not isinstance(statement, s.Statement_TopLevel):
                continue
            name = statement_name(statement)
            if name is None:
                continue
            statement_range = make_range(
                *statement_span(statement),
            )
            result.append(
                {
                    "name": name,
                    "kind": symbol_kind(statement),
                    "range": statement_range,
                    "selectionRange": statement_range,
                }
            )
        return result

    def _workspace_symbols(self, params: dict[str, object]) -> list[dict[str, object]]:
        query = str(params.get("query", "")).strip().lower()
        root = self._guess_root_from_open_docs()
        if root is None:
            return []
        target, _ = self._build_workspace(root / "src" / ("main.enq" if is_binary_project(root) else "lib.enq"))
        result: list[dict[str, object]] = []
        seen: set[tuple[Path, str]] = set()
        for refrain in self._collect_refrains(target):
            for bindings in refrain.symbols.all.values():
                for binding in bindings:
                    if query and query not in binding.name.lower():
                        continue
                    if not isinstance(binding.statement, s.Statement_TopLevel):
                        continue
                    key = (binding.module_id.resolve(), binding.name)
                    if key in seen:
                        continue
                    seen.add(key)
                    location = self._binding_location(binding)
                    if location is None:
                        continue
                    result.append(
                        {
                            "name": binding.name,
                            "kind": symbol_kind(binding.statement),
                            "location": location,
                        }
                    )
        return result

    def _completion(self, params: dict[str, object]) -> dict[str, object]:
        path = uri_to_path(params["textDocument"]["uri"])
        position = params["position"]
        line = int(position["line"])
        character = int(position["character"])
        if self._is_import_completion_context(path, line, character):
            try:
                target, manager = self._build_workspace(path, ignored_open_documents={path.resolve()})
                import_items = self._import_completion_items(target, manager, path, line, character)
                if import_items is not None:
                    return {"isIncomplete": False, "items": import_items}
            except Exception:
                pass
        target = None
        manager = None
        try:
            target, manager = self._build_workspace(path)
        except Exception:
            try:
                target, manager = self._build_workspace(path, ignored_open_documents={path.resolve()})
            except Exception:
                target = None
                manager = None

        if target is not None and manager is not None:
            import_items = self._import_completion_items(target, manager, path, line, character)
            if import_items is not None:
                return {"isIncomplete": False, "items": import_items}
            scope_items = self._scope_completion_items(target, manager, path, line, character)
            if scope_items is not None:
                return {"isIncomplete": False, "items": scope_items}
            method_items = self._method_completion_items(target, path, line, character)
            if method_items is not None:
                return {"isIncomplete": False, "items": method_items}
            local_items = self._local_completion_items(target, path, line, character)
            module_symbols = target.symbols.modules.get(path.resolve(), {})
        else:
            local_items = []
            module_symbols = {}
        items: list[dict[str, object]] = []
        seen: set[str] = set()
        edit_range = self._completion_edit_range(path, line, character)
        for keyword in _KEYWORDS:
            seen.add(keyword)
            items.append({"label": keyword, "kind": 14, "textEdit": {"range": edit_range, "newText": keyword}})
        for item in local_items:
            if item["label"] in seen:
                continue
            seen.add(item["label"])
            items.append(item)
        for binding in sorted(module_symbols.values(), key=lambda item: item.name):
            if binding.name.startswith("impl::"):
                continue
            if binding.name in seen:
                continue
            seen.add(binding.name)
            items.append(
                {
                    "label": binding.name,
                    "kind": completion_kind(binding.statement),
                    "detail": repr(binding.statement),
                    "textEdit": {"range": edit_range, "newText": binding.name},
                }
            )
        return {"isIncomplete": False, "items": items}

    def _prepare_rename(self, params: dict[str, object]) -> dict[str, object] | None:
        path, line, character = self._request_position(params)
        token = self._token_at(path, line, character)
        if token is None or not self._token_can_reference(token):
            return None
        return {"range": self._token_range(token), "placeholder": token.value}

    def _rename(self, params: dict[str, object]) -> dict[str, object]:
        path, line, character = self._request_position(params)
        new_name = str(params.get("newName", "")).strip()
        if not new_name or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", new_name):
            return {"changes": {}}
        target, _ = self._build_workspace(path)
        token = self._token_at(path, line, character)
        if token is None or not self._token_can_reference(token):
            return {"changes": {}}
        binding = self._binding_at_position(target, path, line, character)
        changes: dict[str, list[dict[str, object]]] = {}
        if binding is not None:
            for location in self._reference_locations(target, path, line, character):
                changes.setdefault(location["uri"], []).append({"range": location["range"], "newText": new_name})
            return {"changes": changes}
        changes[path_to_uri(path)] = [
            {"range": self._token_range(other), "newText": new_name}
            for other in self._same_document_token_occurrences(path, token.value)
        ]
        return {"changes": changes}

    def _signature_help(self, params: dict[str, object]) -> dict[str, object]:
        path, line, character = self._request_position(params)
        target, _ = self._build_workspace(path)
        call = self._active_call(path, line, character)
        if call is None:
            return {"signatures": [], "activeSignature": 0, "activeParameter": 0}
        binding = self._binding_for_call(target, path.resolve(), call)
        if binding is None:
            return {"signatures": [], "activeSignature": 0, "activeParameter": 0}
        signature = self._signature_from_binding(binding)
        if signature is None:
            return {"signatures": [], "activeSignature": 0, "activeParameter": 0}
        return {
            "signatures": [signature],
            "activeSignature": 0,
            "activeParameter": min(call.active_parameter, max(len(signature["parameters"]) - 1, 0)),
        }

    def _folding_ranges(self, params: dict[str, object]) -> list[dict[str, object]]:
        path = uri_to_path(params["textDocument"]["uri"])
        tokens = self._document_tokens(path)
        stack: list[LexerToken] = []
        ranges: list[dict[str, object]] = []
        for token in tokens:
            if token.type == TokenType.LEFT_BRACE:
                stack.append(token)
            elif token.type == TokenType.RIGHT_BRACE and stack:
                opened = stack.pop()
                if token.line > opened.line:
                    ranges.append(
                        {
                            "startLine": opened.line,
                            "startCharacter": opened.column,
                            "endLine": token.line,
                            "endCharacter": token.column + len(token.value),
                        }
                    )
        return ranges

    def _selection_ranges(self, params: dict[str, object]) -> list[dict[str, object]]:
        path = uri_to_path(params["textDocument"]["uri"])
        result: list[dict[str, object]] = []
        for position in params.get("positions", []):
            token = self._token_at(path, int(position["line"]), int(position["character"]))
            result.append({"range": self._token_range(token) if token is not None else make_range(0, 0, 0)})
        return result

    def _document_links(self, params: dict[str, object]) -> list[dict[str, object]]:
        path = uri_to_path(params["textDocument"]["uri"])
        try:
            target, manager = self._build_workspace(path)
            owner = manager._source_owner(target, path.resolve())
            ast = manager._inject_prelude_imports(owner, path.resolve(), manager._parse_file(path.resolve()))
        except Exception:
            return []
        links: list[dict[str, object]] = []
        for statement in ast:
            if not isinstance(statement, s.Statement_Import):
                continue
            line, column, span_length = statement_span(statement)
            if line is None or column is None:
                continue
            seen_targets: set[Path] = set()
            for request in manager._expand_import(statement):
                try:
                    edge = manager._resolve_import_edge(target, path.resolve(), request)
                except Exception:
                    continue
                resolved_target = edge.target.resolve()
                if resolved_target in seen_targets:
                    continue
                seen_targets.add(resolved_target)
                links.append(
                    {
                        "range": make_range(line, column, span_length),
                        "target": path_to_uri(resolved_target),
                        "tooltip": f"Encore import: {'::'.join(request.path)}",
                    }
                )
        return links

    def _semantic_tokens(self, params: dict[str, object]) -> dict[str, object]:
        path = uri_to_path(params["textDocument"]["uri"])
        try:
            target, _ = self._build_workspace(path)
        except Exception:
            try:
                target, _ = self._build_workspace(path, ignored_open_documents={path.resolve()})
            except Exception:
                target = None
        tokens = self._document_tokens(path)
        semantic_context = self._semantic_context(target, path) if target is not None else self._lexical_semantic_context(tokens)
        data: list[int] = []
        prev_line = 0
        prev_start = 0
        first = True
        for token in tokens:
            kind = self._semantic_token_kind(target, path, token, semantic_context)
            if kind is None:
                continue
            delta_line = token.line if first else token.line - prev_line
            delta_start = token.column if first or delta_line else token.column - prev_start
            data.extend([delta_line, delta_start, len(token.value), kind, 0])
            prev_line = token.line
            prev_start = token.column
            first = False
        return {"data": data}

    def _document_formatting(self, params: dict[str, object]) -> list[dict[str, object]]:
        path = uri_to_path(params["textDocument"]["uri"])
        text = self._document_text(path)
        formatted = self._format_document_text(text)
        if formatted == text:
            return []
        end = self._document_end_position(text)
        return [{"range": {"start": {"line": 0, "character": 0}, "end": end}, "newText": formatted}]

    def _document_diagnostic(self, params: dict[str, object]) -> dict[str, object]:
        path = uri_to_path(params["textDocument"]["uri"])
        diagnostics = self._cached_or_schedule_project_diagnostics(path)
        return {"kind": "full", "items": diagnostics.get(path.resolve(), [])}

    def _workspace_diagnostic(self) -> dict[str, object]:
        items: list[dict[str, object]] = []
        with self._state_lock:
            roots = sorted({find_project_root(path) for path in self._open_documents if find_project_root(path) is not None})
        for root in roots:
            entry = root / "src" / ("main.enq" if is_binary_project(root) else "lib.enq")
            diagnostics = self._cached_or_schedule_project_diagnostics(entry)
            for path, payload in diagnostics.items():
                items.append({"uri": path_to_uri(path), "version": None, "kind": "full", "items": payload})
        return {"items": items}

    def _prepare_call_hierarchy(self, params: dict[str, object]) -> list[dict[str, object]]:
        path, line, character = self._request_position(params)
        target, _ = self._build_workspace(path)
        binding = self._binding_at_position(target, path, line, character)
        if binding is None or not self._is_callable_binding(binding):
            return []
        location = self._binding_location(binding)
        if location is None:
            return []
        return [
            {
                "name": binding.name,
                "kind": symbol_kind(binding.statement),
                "uri": location["uri"],
                "range": location["range"],
                "selectionRange": location["range"],
                "data": {
                    "uri": location["uri"],
                    "name": binding.name,
                    "line": line,
                    "character": character,
                },
            }
        ]

    def _outgoing_calls(self, params: dict[str, object]) -> list[dict[str, object]]:
        item = params.get("item", {})
        path = uri_to_path(item["uri"])
        target, _ = self._build_workspace(path)
        source_binding = self._binding_at_position(
            target,
            path,
            int(item.get("data", {}).get("line", item["range"]["start"]["line"])),
            int(item.get("data", {}).get("character", item["range"]["start"]["character"])),
        )
        if source_binding is None or not self._is_callable_binding(source_binding):
            return []
        body_tokens = self._function_body_tokens(path, source_binding)
        if not body_tokens:
            return []
        result: list[dict[str, object]] = []
        seen: set[_BindingKey] = set()
        for token in body_tokens:
            if not self._token_can_reference(token) or not self._is_call_token(path, token):
                continue
            binding = self._binding_at_position(target, path, token.line, token.column)
            if binding is None or not self._is_callable_binding(binding):
                continue
            binding_key = self._binding_key(binding)
            if binding_key in seen:
                continue
            seen.add(binding_key)
            location = self._binding_location(binding)
            if location is None:
                continue
            result.append(
                {
                    "to": {
                        "name": binding.name,
                        "kind": symbol_kind(binding.statement),
                        "uri": location["uri"],
                        "range": location["range"],
                        "selectionRange": location["range"],
                        "data": {
                            "uri": location["uri"],
                            "name": binding.name,
                            "line": location["range"]["start"]["line"],
                            "character": location["range"]["start"]["character"],
                        },
                    },
                    "fromRanges": [self._token_range(token)],
                }
            )
        return result

    def _incoming_calls(self, params: dict[str, object]) -> list[dict[str, object]]:
        item = params.get("item", {})
        path = uri_to_path(item["uri"])
        target, _ = self._build_workspace(path)
        target_binding = self._binding_at_position(
            target,
            path,
            int(item.get("data", {}).get("line", item["range"]["start"]["line"])),
            int(item.get("data", {}).get("character", item["range"]["start"]["character"])),
        )
        if target_binding is None:
            return []
        target_key = self._binding_key(target_binding)
        result: list[dict[str, object]] = []
        for doc_path in self._project_paths(target):
            refs: list[dict[str, object]] = []
            for token in self._document_tokens(doc_path):
                if token.value != target_binding.name:
                    continue
                if not self._token_can_reference(token) or not self._is_call_token(doc_path, token):
                    continue
                binding = self._binding_at_position(target, doc_path, token.line, token.column)
                if binding is None or self._binding_key(binding) != target_key:
                    continue
                caller = self._enclosing_callable_binding(target, doc_path, token.line, token.column)
                if caller is None:
                    continue
                refs.append({"range": self._token_range(token), "caller": caller})
            if not refs:
                continue
            caller = refs[0]["caller"]
            location = self._binding_location(caller)
            if location is None:
                continue
            result.append(
                {
                    "from": {
                        "name": caller.name,
                        "kind": symbol_kind(caller.statement),
                        "uri": location["uri"],
                        "range": location["range"],
                        "selectionRange": location["range"],
                        "data": {
                            "uri": location["uri"],
                            "name": caller.name,
                            "line": location["range"]["start"]["line"],
                            "character": location["range"]["start"]["character"],
                        },
                    },
                    "fromRanges": [ref["range"] for ref in refs],
                }
            )
        return result

    def _publish_project_diagnostics(self, path: Path) -> None:
        self._schedule_project_diagnostics(path)

    def _build_workspace(
        self,
        path: Path,
        ignored_open_documents: set[Path] | None = None,
    ) -> tuple[RefrainData, RefrainManager]:
        root = find_project_root(path)
        if root is None:
            raise RuntimeError(f"Unable to find {ProjectManifest.default_filename()} for {path}")
        ignored_open_documents = {doc.resolve() for doc in ignored_open_documents or set()}
        use_cache = not ignored_open_documents
        fallback_key = (root, tuple(sorted(ignored_open_documents)))
        with self._state_lock:
            cached = self._workspace_cache.get(root)
            if use_cache and cached is not None:
                return cached.target, cached.manager
            fallback_cached = self._workspace_fallback_cache.get(fallback_key)
            if not use_cache and fallback_cached is not None:
                return fallback_cached.target, fallback_cached.manager
            overrides = {
                doc.resolve(): text
                for doc, text in self._open_documents.items()
                if doc.resolve() not in ignored_open_documents and find_project_root(doc) == root
            }
        manager = RefrainManager(source_overrides=overrides)
        target = manager.add_refrain_with_dependencies(root, is_binary_project(root))
        with self._state_lock:
            if use_cache:
                self._workspace_cache[root] = _CachedWorkspace(root=root, target=target, manager=manager)
            else:
                self._workspace_fallback_cache[fallback_key] = _CachedWorkspace(root=root, target=target, manager=manager)
        return target, manager

    def _invalidate_workspace(self, path: Path, invalidate_fallbacks: bool = False) -> None:
        root = find_project_root(path)
        if root is None:
            return
        with self._state_lock:
            self._workspace_cache.pop(root, None)
            changed_path = path.resolve()
            for key in list(self._workspace_fallback_cache):
                if key[0] != root:
                    continue
                ignored_paths = set(key[1])
                if invalidate_fallbacks or changed_path not in ignored_paths:
                    self._workspace_fallback_cache.pop(key, None)

    def _project_paths(self, target: RefrainData) -> list[Path]:
        paths: set[Path] = set()
        for refrain in self._collect_refrains(target):
            if refrain.import_graph is None:
                continue
            paths.update(module_id.resolve() for module_id in refrain.import_graph.modules)
        return sorted(paths)

    def _document_tokens(self, path: Path) -> list[LexerToken]:
        path = path.resolve()
        text = self._document_text(path)
        with self._state_lock:
            cached = self._token_cache.get(path)
            if cached is not None and cached[0] == text:
                return cached[1]
        tokens = self._lexer.parse(list(text))
        with self._state_lock:
            self._token_cache[path] = (text, tokens)
        return tokens

    def _token_at(self, path: Path, line: int, character: int) -> LexerToken | None:
        for token in self._document_tokens(path):
            if token.line != line:
                continue
            if token.column <= character < token.column + len(token.value):
                return token
        return None

    def _token_at_or_before(self, path: Path, line: int, character: int) -> LexerToken | None:
        token = self._token_at(path, line, character)
        if token is not None:
            return token
        if character <= 0:
            return None
        for token in self._document_tokens(path):
            if token.line != line:
                continue
            if token.column < character <= token.column + len(token.value):
                return token
        return None

    def _token_index_at(self, path: Path, line: int, character: int) -> int | None:
        tokens = self._document_tokens(path)
        for index, token in enumerate(tokens):
            if token.line != line:
                continue
            if token.column <= character < token.column + len(token.value):
                return index
        return None

    def _token_index(self, path: Path, token: LexerToken) -> int | None:
        for index, candidate in enumerate(self._document_tokens(path)):
            if (
                candidate.line == token.line
                and candidate.column == token.column
                and candidate.value == token.value
                and candidate.type == token.type
            ):
                return index
        return None

    def _token_range(self, token: LexerToken) -> dict[str, object]:
        return make_range(token.line, token.column, len(token.value))

    def _token_can_reference(self, token: LexerToken) -> bool:
        return token.type == TokenType.IDENTIFIER

    def _binding_key(self, binding: SymbolBinding) -> _BindingKey:
        line, column, span_length = statement_span(binding.statement)
        return _BindingKey(
            module_id=binding.module_id.resolve(),
            line=line,
            column=column,
            span_length=span_length,
            name=binding.name,
        )

    def _reference_locations(self, target: RefrainData, path: Path, line: int, character: int) -> list[dict[str, object]]:
        token = self._token_at(path, line, character)
        if token is None or not self._token_can_reference(token):
            return []
        binding = self._binding_at_position(target, path, line, character)
        if binding is None:
            return [{"uri": path_to_uri(path.resolve()), "range": self._token_range(other)} for other in self._same_document_token_occurrences(path, token.value)]
        binding_key = self._binding_key(binding)
        locations: list[dict[str, object]] = []
        for doc_path in self._project_paths(target):
            for other in self._document_tokens(doc_path):
                if other.value != token.value or not self._token_can_reference(other):
                    continue
                other_binding = self._binding_at_position(target, doc_path, other.line, other.column)
                if other_binding is None or self._binding_key(other_binding) != binding_key:
                    continue
                locations.append({"uri": path_to_uri(doc_path), "range": self._token_range(other)})
        return locations

    def _same_document_token_occurrences(self, path: Path, name: str) -> list[LexerToken]:
        return [token for token in self._document_tokens(path) if token.value == name and self._token_can_reference(token)]

    def _import_context_at_position(self, path: Path, line: int, character: int) -> _ImportTokenContext | None:
        token = self._token_at_or_before(path, line, character)
        if token is None or token.type != TokenType.IDENTIFIER:
            return None
        line_tokens = [item for item in self._document_tokens(path) if item.line == line]
        token_pos = None
        import_pos = None
        for index, item in enumerate(line_tokens):
            if item.type == TokenType.KW_IMPORT and item.column < token.column:
                import_pos = index
            if item.column == token.column and item.value == token.value and item.type == token.type:
                token_pos = index
        if import_pos is None or token_pos is None or token_pos <= import_pos:
            return None

        left = token_pos
        while left >= import_pos + 2 and line_tokens[left - 1].type == TokenType.SCOPE and line_tokens[left - 2].type == TokenType.IDENTIFIER:
            left -= 2
        right = token_pos
        while right + 2 < len(line_tokens) and line_tokens[right + 1].type == TokenType.SCOPE and line_tokens[right + 2].type == TokenType.IDENTIFIER:
            right += 2

        parts: list[str] = []
        part_index = 0
        for index in range(left, right + 1):
            item = line_tokens[index]
            if item.type != TokenType.IDENTIFIER:
                continue
            if index == token_pos:
                part_index = len(parts)
            parts.append(item.value)
        if not parts:
            return None
        return _ImportTokenContext(token=token, parts=tuple(parts), part_index=part_index)

    def _import_location_at_position(
        self,
        target: RefrainData,
        manager: RefrainManager,
        path: Path,
        line: int,
        character: int,
    ) -> dict[str, object] | None:
        context = self._import_context_at_position(path, line, character)
        if context is None:
            return None
        source = path.resolve()
        prefix = context.parts[: context.part_index + 1]
        if context.is_final_part:
            try:
                target_module, symbol_path = manager._resolve_import_target(target, source, context.parts)
            except Exception:
                return None
            if symbol_path:
                binding = self._lookup_exported_binding(target, target_module, symbol_path)
                return self._binding_location(binding) if binding is not None else None
            return self._module_location(target_module)

        try:
            target_module, _ = manager._resolve_import_target(target, source, prefix)
        except Exception:
            return None
        return self._module_location(target_module)

    def _lookup_exported_binding(
        self,
        target: RefrainData,
        module_id: Path,
        symbol_path: tuple[str, ...],
    ) -> SymbolBinding | None:
        exports = target.symbols.exports.get(module_id.resolve(), {})
        full_name = "::".join(symbol_path)
        binding = exports.get(full_name)
        if binding is None and len(symbol_path) == 1:
            binding = exports.get(symbol_path[0])
        return binding

    def _module_location(self, module_id: Path) -> dict[str, object]:
        return {
            "uri": path_to_uri(module_id),
            "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 0}},
        }

    def _validate_workspace(self, target: RefrainData, manager: RefrainManager) -> None:
        compiler = EncoreCompiler(refrain_manager=manager, targets=[target])
        compiler._infer_refrain_modules(target)
        alias_declarations = compiler._flattened_alias_declarations(target)
        entrypoint = target.import_graph.entrypoint if target.import_graph is not None else None
        source_text = None
        if entrypoint is not None:
            source_text = manager.source_overrides.get(entrypoint.resolve())
            if source_text is None and entrypoint.exists():
                source_text = entrypoint.read_text()
        try:
            ehir_raw_module = EncoreToEHIRTranslator().translate_ast(
                target.ast,
                module_id=entrypoint,
                imported_declarations=alias_declarations,
            )
            ehir_compiler = EHIR_ProjectCompiler()
            ehir_typed_module = ehir_compiler.resolve_module(ehir_raw_module)
            ehir_compiler.compile_module(ehir_typed_module)
        except Exception as exc:
            raise with_diagnostic_context(
                exc,
                stage="translation",
                module_id=entrypoint,
                source_text=source_text,
            ) from exc

    def _binding_at_position(
        self,
        target: RefrainData,
        path: Path,
        line: int,
        character: int,
    ) -> SymbolBinding | None:
        module_id = path.resolve()
        import_context = self._import_context_at_position(path, line, character)
        if import_context is not None:
            if not import_context.is_final_part:
                return None
            symbol_name = import_context.parts[-1]
            return self._binding_for_name(target, module_id, symbol_name)

        symbol_name = self._symbol_name_at_position(path, line, character)
        if symbol_name is None:
            module_ast = target.symbols.local_ast_without_imports.get(module_id, [])
            symbol_node = find_symbol_node(module_ast, line, character)
            symbol_name = symbol_name_from_node(symbol_node) if symbol_node is not None else None
        if symbol_name is None:
            return None
        method_binding = self._method_binding_for_symbol(target, symbol_name)
        if method_binding is not None:
            return method_binding
        return self._binding_for_name(target, module_id, symbol_name)

    def _symbol_name_at_position(self, path: Path, line: int, character: int) -> str | None:
        token = self._token_at_or_before(path, line, character)
        if token is None or token.type != TokenType.IDENTIFIER:
            return None
        tokens = self._document_tokens(path)
        index = self._token_index(path, token)
        if index is None:
            return token.value

        prev_index = index - 1
        if prev_index >= 0 and tokens[prev_index].type == TokenType.RIGHT_BRACKET:
            prev_index = self._skip_bracket_group(tokens, prev_index)
        if prev_index >= 0 and tokens[prev_index].type == TokenType.SCOPE:
            return self._scoped_name_ending_at(tokens, index)
        return token.value

    def _scoped_name_ending_at(self, tokens: list[LexerToken], index: int) -> str:
        names = [tokens[index].value]
        cursor = index - 1
        while cursor >= 0:
            if tokens[cursor].type == TokenType.RIGHT_BRACKET:
                cursor = self._skip_bracket_group(tokens, cursor)
                continue
            if tokens[cursor].type != TokenType.SCOPE:
                break
            prev = cursor - 1
            if prev >= 0 and tokens[prev].type == TokenType.RIGHT_BRACKET:
                prev = self._skip_bracket_group(tokens, prev)
            if prev < 0 or tokens[prev].type != TokenType.IDENTIFIER:
                break
            names.append(tokens[prev].value)
            cursor = prev - 1
        return "::".join(reversed(names))

    def _binding_for_name(self, target: RefrainData, module_id: Path, symbol_name: str) -> SymbolBinding | None:
        module_symbols = target.symbols.modules.get(module_id, {})
        candidates: list[SymbolBinding] = []
        lookup_names = [symbol_name]
        stripped_symbol_name = "::".join(strip_generic_suffix(part) for part in symbol_name.split("::"))
        if stripped_symbol_name != symbol_name:
            lookup_names.append(stripped_symbol_name)
        for lookup_name in lookup_names:
            direct = module_symbols.get(lookup_name)
            if direct is not None:
                candidates.append(direct)
        short_name = stripped_symbol_name.split("::")[-1]
        if short_name != symbol_name:
            direct_short = module_symbols.get(short_name)
            if direct_short is not None:
                candidates.append(direct_short)
        for binding_name, binding in module_symbols.items():
            if binding_name.split("::")[-1] == short_name:
                candidates.append(binding)
        for refrain in self._collect_refrains(target):
            for lookup_name in lookup_names:
                for binding in refrain.symbols.all.get(lookup_name, []):
                    candidates.append(binding)
            if short_name != symbol_name:
                for binding_name, bindings in refrain.symbols.all.items():
                    if binding_name.split("::")[-1] != short_name:
                        continue
                    candidates.extend(bindings)
        seen: set[tuple[Path, str, int]] = set()
        unique: list[SymbolBinding] = []
        for binding in candidates:
            key = (binding.module_id.resolve(), binding.name, id(binding.statement))
            if key in seen:
                continue
            seen.add(key)
            unique.append(binding)
        return unique[0] if len(unique) == 1 else (unique[0] if unique else None)

    def _symbol_text_at_position(self, path: Path, line: int, character: int) -> str | None:
        line_text = self._line_text(path, line)
        if line_text is None:
            return None
        allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_:.[]")
        if character > len(line_text):
            character = len(line_text)
        left = character
        while left > 0 and line_text[left - 1] in allowed:
            left -= 1
        right = character
        while right < len(line_text) and line_text[right] in allowed:
            right += 1
        token = line_text[left:right].strip(":.")
        return token or None

    def _completion_edit_range(self, path: Path, line: int, character: int) -> dict[str, object]:
        line_text = self._line_text(path, line) or ""
        if character > len(line_text):
            character = len(line_text)
        left = character
        while left > 0 and (line_text[left - 1].isalnum() or line_text[left - 1] == "_"):
            left -= 1
        return {
            "start": {"line": line, "character": left},
            "end": {"line": line, "character": character},
        }

    def _local_completion_items(
        self,
        target: RefrainData,
        path: Path,
        line: int,
        character: int,
    ) -> list[dict[str, object]]:
        binding = self._enclosing_callable_binding(target, path, line, character)
        if binding is None or not isinstance(binding.statement, s.Statement_FunctionDefinition):
            return []
        edit_range = self._completion_edit_range(path, line, character)
        items: list[dict[str, object]] = []
        seen: set[str] = set()
        for param in binding.statement.signature.params:
            if param.name in seen:
                continue
            seen.add(param.name)
            items.append(
                {
                    "label": param.name,
                    "kind": 6,
                    "detail": str(param),
                    "textEdit": {"range": edit_range, "newText": param.name},
                }
            )
        for node in walk_statement_nodes(binding.statement.body):
            node_line = getattr(node, "line", None)
            node_col = getattr(node, "column", None)
            if node_line is None:
                continue
            if node_line > line or (node_line == line and node_col is not None and node_col >= character):
                continue
            name = None
            detail = None
            if isinstance(node, s.Statement_Let):
                name = node.name
                detail = f"{node.name}: {node.type}" if node.type is not None else node.name
            elif isinstance(node, s.Statement_For):
                name = node.name
                detail = node.name
            elif isinstance(node, s.Statement_With):
                name = node.name
                detail = node.name
            elif isinstance(node, s.Statement_MatchArm) and node.binding is not None:
                name = node.binding
                detail = node.binding
            if name is None or name in seen:
                continue
            seen.add(name)
            items.append(
                {
                    "label": name,
                    "kind": 6,
                    "detail": detail,
                    "textEdit": {"range": edit_range, "newText": name},
                }
            )
        return items

    def _document_text(self, path: Path) -> str:
        path = path.resolve()
        with self._state_lock:
            text = self._open_documents.get(path)
        if text is not None:
            return text
        return path.read_text() if path.exists() else ""

    def _line_text(self, path: Path, line: int) -> str | None:
        rows = self._document_text(path).splitlines()
        if 0 <= line < len(rows):
            return rows[line]
        return None

    def _import_completion_items(
        self,
        target: RefrainData,
        manager: RefrainManager,
        path: Path,
        line: int,
        character: int,
    ) -> list[dict[str, object]] | None:
        line_text = self._line_text(path, line)
        if line_text is None:
            return None
        prefix = line_text[:character]
        import_match = re.search(r"(?:^|\s)import\s+([A-Za-z0-9_:]*)$", prefix)
        if import_match is None:
            return None
        fragment = import_match.group(1)
        ends_with_scope = fragment.endswith("::")
        raw_parts = [part for part in fragment.split("::") if part]
        partial = "" if ends_with_scope else (raw_parts.pop() if raw_parts else "")

        candidates = self._import_candidates(target, manager, path, tuple(raw_parts))
        items: list[dict[str, object]] = []
        seen: set[str] = set()
        for candidate in sorted(candidates):
            if partial and not candidate.startswith(partial):
                continue
            if candidate in seen:
                continue
            seen.add(candidate)
            start = character - len(partial)
            items.append(
                {
                    "label": candidate,
                    "kind": 9,
                    "textEdit": {"range": make_edit_range(line, start, len(partial)), "newText": candidate},
                }
            )
        return items

    def _is_import_completion_context(self, path: Path, line: int, character: int) -> bool:
        line_text = self._line_text(path, line)
        if line_text is None:
            return False
        return re.search(r"(?:^|\s)import\s+[A-Za-z0-9_:]*$", line_text[:character]) is not None

    def _scope_completion_items(
        self,
        target: RefrainData,
        manager: RefrainManager,
        path: Path,
        line: int,
        character: int,
    ) -> list[dict[str, object]] | None:
        line_text = self._line_text(path, line)
        if line_text is None:
            return None
        prefix = line_text[:character]
        match = re.search(r"([A-Za-z0-9_:\[\]]+)::([A-Za-z0-9_]*)$", prefix)
        if match is None:
            return None
        owner = match.group(1)
        partial = match.group(2)
        items: list[dict[str, object]] = []
        seen: set[str] = set()
        raw_parts = tuple(part for part in owner.split("::") if part)
        candidates = self._import_candidates(target, manager, path, raw_parts)
        for candidate in sorted(candidates):
            if partial and not candidate.startswith(partial):
                continue
            if candidate in seen:
                continue
            seen.add(candidate)
            start = character - len(partial)
            items.append(
                {
                    "label": candidate,
                    "kind": 9,
                    "textEdit": {"range": make_edit_range(line, start, len(partial)), "newText": candidate},
                }
            )
        owner_base = strip_generic_suffix(owner.split("::")[-1])
        for binding in self._methods_for_owner(target, owner_base):
            if partial and not binding.name.startswith(partial):
                continue
            if binding.name in seen:
                continue
            seen.add(binding.name)
            start = character - len(partial)
            items.append(
                {
                    "label": binding.name,
                    "kind": 2,
                    "detail": repr(binding.statement),
                    "textEdit": {"range": make_edit_range(line, start, len(partial)), "newText": binding.name},
                }
            )
        return items

    def _method_completion_items(
        self,
        target: RefrainData,
        path: Path,
        line: int,
        character: int,
    ) -> list[dict[str, object]] | None:
        line_text = self._line_text(path, line)
        if line_text is None:
            return None
        prefix = line_text[:character]
        match = re.search(r"\.([A-Za-z0-9_]*)$", prefix)
        if match is None:
            return None
        partial = match.group(1)
        items: list[dict[str, object]] = []
        seen: set[str] = set()
        start = character - len(partial)
        for binding in sorted(self._all_method_bindings(target), key=lambda item: item.name):
            if partial and not binding.name.startswith(partial):
                continue
            if binding.name in seen:
                continue
            seen.add(binding.name)
            items.append(
                {
                    "label": binding.name,
                    "kind": 2,
                    "detail": repr(binding.statement),
                    "textEdit": {"range": make_edit_range(line, start, len(partial)), "newText": binding.name},
                }
            )
        return items

    def _import_candidates(
        self,
        target: RefrainData,
        manager: RefrainManager,
        path: Path,
        path_parts: tuple[str, ...],
    ) -> set[str]:
        owner = manager._source_owner(target, path.resolve())
        if not path_parts:
            candidates = {"mod", "refrain", "repo", owner.name}
            candidates.update(dep.name for dep in owner.dependencies)
            candidates.update(dep.name for dep in target.dependencies)
            return candidates

        root_name = path_parts[0]
        suffix = path_parts[1:]
        if root_name in {"refrain", "repo", owner.name}:
            base_dir = owner.path / "src"
        elif root_name == "mod":
            base_dir = path.resolve().parent
        else:
            dependency = manager._dependency_by_name(owner, root_name) or manager._dependency_by_name(target, root_name)
            if dependency is None:
                return set()
            base_dir = dependency.path / "src"

        module_dir = base_dir.joinpath(*suffix) if suffix else base_dir
        candidates: set[str] = set()
        if module_dir.exists() and module_dir.is_dir():
            for child in module_dir.iterdir():
                if child.is_dir() and (child / "mod.enq").exists():
                    candidates.add(child.name)
                elif child.is_file() and child.suffix == ".enq" and child.stem not in {"main", "lib", "mod"}:
                    candidates.add(child.stem)

        resolved_module = manager._resolve_module_file(base_dir, suffix)
        if resolved_module is not None:
            exports = target.symbols.exports.get(resolved_module.resolve(), {})
            candidates.update(name.split("::")[-1] for name in exports)
        return candidates

    def _method_binding_for_symbol(self, target: RefrainData, symbol_name: str) -> SymbolBinding | None:
        if "::" not in symbol_name:
            return None
        owner_name, method_name = symbol_name.rsplit("::", 1)
        owner_base = strip_generic_suffix(owner_name.split("::")[-1])
        for refrain in self._collect_refrains(target):
            for module_id, statements in refrain.symbols.local_ast_without_imports.items():
                for statement in statements:
                    if not isinstance(statement, s.Statement_Impl):
                        continue
                    impl_owner = strip_generic_suffix(statement.struct.name.split("::")[-1])
                    trait_owner = strip_generic_suffix(statement.trait_name.split("::")[-1]) if statement.trait_name else None
                    if impl_owner != owner_base and trait_owner != owner_base:
                        continue
                    for method in statement.body:
                        if method.signature.name != method_name:
                            continue
                        if getattr(method, "line", None) is None:
                            method.line = getattr(statement, "line", None)
                            method.column = getattr(statement, "column", None)
                            method.span_length = getattr(statement, "span_length", None)
                        if getattr(method.signature, "line", None) is None:
                            method.signature.line = getattr(statement, "line", None)
                            method.signature.column = getattr(statement, "column", None)
                            method.signature.span_length = getattr(statement, "span_length", None)
                        return SymbolBinding(
                            name=method_name,
                            source_name=method_name,
                            module_id=module_id.resolve(),
                            statement=method,
                            is_public=method.is_public,
                        )
        return None

    def _method_bindings_by_name(self, target: RefrainData, method_name: str) -> list[SymbolBinding]:
        result: list[SymbolBinding] = []
        seen: set[_BindingKey] = set()
        for binding in self._all_method_bindings(target):
            if binding.name != method_name:
                continue
            key = self._binding_key(binding)
            if key in seen:
                continue
            seen.add(key)
            result.append(binding)
        return result

    def _all_method_bindings(self, target: RefrainData) -> list[SymbolBinding]:
        result: list[SymbolBinding] = []
        for refrain in self._collect_refrains(target):
            for module_id, statements in refrain.symbols.local_ast_without_imports.items():
                for statement in statements:
                    if not isinstance(statement, s.Statement_Impl):
                        continue
                    for method in statement.body:
                        result.append(
                            SymbolBinding(
                                name=method.signature.name,
                                source_name=method.signature.name,
                                module_id=module_id.resolve(),
                                statement=method,
                                is_public=method.is_public,
                            )
                        )
        return result

    def _methods_for_owner(self, target: RefrainData, owner_base: str) -> list[SymbolBinding]:
        result: list[SymbolBinding] = []
        for refrain in self._collect_refrains(target):
            for module_id, statements in refrain.symbols.local_ast_without_imports.items():
                for statement in statements:
                    if not isinstance(statement, s.Statement_Impl):
                        continue
                    impl_owner = strip_generic_suffix(statement.struct.name.split("::")[-1])
                    trait_owner = strip_generic_suffix(statement.trait_name.split("::")[-1]) if statement.trait_name else None
                    if impl_owner != owner_base and trait_owner != owner_base:
                        continue
                    for method in statement.body:
                        result.append(
                            SymbolBinding(
                                name=method.signature.name,
                                source_name=method.signature.name,
                                module_id=module_id.resolve(),
                                statement=method,
                                is_public=method.is_public,
                            )
                        )
        return result

    def _binding_for_call(self, target: RefrainData, module_id: Path, call: _CallInfo) -> SymbolBinding | None:
        if call.is_method:
            bindings = self._method_bindings_by_name(target, call.name)
            return bindings[0] if len(bindings) == 1 else None
        method_binding = self._method_binding_for_symbol(target, call.name)
        if method_binding is not None:
            return method_binding
        return self._binding_for_name(target, module_id, call.name)

    def _signature_from_binding(self, binding: SymbolBinding) -> dict[str, object] | None:
        statement = binding.statement
        if isinstance(statement, s.Statement_FunctionDefinition):
            signature = statement.signature
        elif isinstance(statement, s.FunctionSignature):
            signature = statement
        else:
            return None
        params = [
            {"label": str(param), "documentation": {"kind": "plaintext", "value": f"{param.name}: {param.type}"}}
            for param in signature.params
        ]
        return {
            "label": repr(signature),
            "documentation": {"kind": "plaintext", "value": repr(signature)},
            "parameters": params,
        }

    def _active_call(self, path: Path, line: int, character: int) -> _CallInfo | None:
        tokens = self._document_tokens(path)
        active_parameter = 0
        paren_depth = 0
        bracket_depth = 0
        brace_depth = 0
        filtered = [
            token
            for token in tokens
            if token.line < line or (token.line == line and token.column < character)
        ]
        for index in range(len(filtered) - 1, -1, -1):
            token = filtered[index]
            if token.type == TokenType.RIGHT_PAREN:
                paren_depth += 1
                continue
            if token.type == TokenType.LEFT_PAREN:
                if paren_depth == 0 and bracket_depth == 0 and brace_depth == 0:
                    return self._call_info_before_open_paren(filtered, index, active_parameter)
                paren_depth = max(paren_depth - 1, 0)
                continue
            if token.type == TokenType.RIGHT_BRACKET:
                bracket_depth += 1
                continue
            if token.type == TokenType.LEFT_BRACKET:
                bracket_depth = max(bracket_depth - 1, 0)
                continue
            if token.type == TokenType.RIGHT_BRACE:
                brace_depth += 1
                continue
            if token.type == TokenType.LEFT_BRACE:
                brace_depth = max(brace_depth - 1, 0)
                continue
            if token.type == TokenType.COMMA and paren_depth == 0 and bracket_depth == 0 and brace_depth == 0:
                active_parameter += 1
        return None

    def _call_info_before_open_paren(
        self,
        tokens: list[LexerToken],
        open_paren_index: int,
        active_parameter: int,
    ) -> _CallInfo | None:
        index = open_paren_index - 1
        while index >= 0 and tokens[index].type == TokenType.RIGHT_BRACKET:
            index = self._skip_bracket_group(tokens, index)
        if index < 0 or tokens[index].type != TokenType.IDENTIFIER:
            return None
        name_parts = [tokens[index].value]
        is_method = False
        left = index - 1
        while left >= 0 and tokens[left].type == TokenType.RIGHT_BRACKET:
            left = self._skip_bracket_group(tokens, left)
        if left >= 0 and tokens[left].type == TokenType.DOT:
            is_method = True
            return _CallInfo(name=tokens[index].value, is_method=True, active_parameter=active_parameter)
        while left >= 0:
            if tokens[left].type == TokenType.RIGHT_BRACKET:
                left = self._skip_bracket_group(tokens, left)
                continue
            if tokens[left].type == TokenType.SCOPE:
                prev = left - 1
                if prev >= 0 and tokens[prev].type == TokenType.RIGHT_BRACKET:
                    prev = self._skip_bracket_group(tokens, prev)
                if prev >= 0 and tokens[prev].type == TokenType.IDENTIFIER:
                    name_parts.append(tokens[prev].value)
                    left = prev - 1
                    continue
            break
        return _CallInfo(name="::".join(reversed(name_parts)), is_method=is_method, active_parameter=active_parameter)

    def _skip_bracket_group(self, tokens: list[LexerToken], index: int) -> int:
        depth = 1
        index -= 1
        while index >= 0 and depth > 0:
            if tokens[index].type == TokenType.RIGHT_BRACKET:
                depth += 1
            elif tokens[index].type == TokenType.LEFT_BRACKET:
                depth -= 1
            index -= 1
        return index

    def _semantic_context(self, target: RefrainData, path: Path) -> _SemanticContext:
        module_id = path.resolve()
        declaration_kinds: dict[tuple[int, int], int] = {}
        visible_kinds: dict[str, int] = {}
        for name, binding in target.symbols.modules.get(module_id, {}).items():
            if name.startswith("impl::"):
                continue
            kind = self._semantic_kind_for_statement(binding.statement)
            if kind is not None:
                visible_kinds[name.split("::")[-1]] = kind

        tokens = self._document_tokens(path)
        for statement in target.symbols.local_ast_without_imports.get(module_id, []):
            if isinstance(statement, s.Statement_Impl):
                line, _, _ = statement_span(statement)
                for method in statement.body:
                    self._record_declaration_kind(tokens, declaration_kinds, method.signature.name, SEM_FUNCTION, line, None)
                continue
            name = statement_name(statement) if isinstance(statement, s.Statement_TopLevel) else None
            if name is None:
                continue
            kind = self._semantic_kind_for_statement(statement)
            if kind is None:
                continue
            line, _, _ = statement_span(statement)
            self._record_declaration_kind(tokens, declaration_kinds, name, kind, line, line + 5 if line is not None else None)
        return _SemanticContext(
            declaration_kinds=declaration_kinds,
            visible_kinds=visible_kinds,
            import_token_kinds=self._semantic_import_token_kinds(tokens, visible_kinds),
            call_tokens=self._call_token_positions(tokens),
        )

    def _lexical_semantic_context(self, tokens: list[LexerToken]) -> _SemanticContext:
        return _SemanticContext(
            declaration_kinds={},
            visible_kinds={},
            import_token_kinds=self._semantic_import_token_kinds(tokens, {}),
            call_tokens=self._call_token_positions(tokens),
        )

    def _semantic_import_token_kinds(
        self,
        tokens: list[LexerToken],
        visible_kinds: dict[str, int],
    ) -> dict[tuple[int, int], int]:
        by_line: dict[int, list[LexerToken]] = {}
        for token in tokens:
            by_line.setdefault(token.line, []).append(token)

        import_kinds: dict[tuple[int, int], int] = {}
        for line_tokens in by_line.values():
            index = 0
            while index < len(line_tokens):
                token = line_tokens[index]
                if token.type != TokenType.KW_IMPORT:
                    index += 1
                    continue

                cursor = index + 1
                skip_alias_identifier = False
                while cursor < len(line_tokens):
                    current = line_tokens[cursor]
                    if current.type == TokenType.KW_IMPORT:
                        break
                    if current.type == TokenType.KW_AS:
                        skip_alias_identifier = True
                        cursor += 1
                        continue
                    if current.type == TokenType.IDENTIFIER:
                        if skip_alias_identifier:
                            skip_alias_identifier = False
                            cursor += 1
                            continue
                        next_index = cursor + 1
                        if next_index < len(line_tokens) and line_tokens[next_index].type == TokenType.SCOPE:
                            import_kinds[(current.line, current.column)] = SEM_NAMESPACE
                        else:
                            import_kinds[(current.line, current.column)] = visible_kinds.get(current.value, SEM_NAMESPACE)
                    cursor += 1
                index = cursor
        return import_kinds

    def _call_token_positions(self, tokens: list[LexerToken]) -> set[tuple[int, int]]:
        positions: set[tuple[int, int]] = set()
        for index, token in enumerate(tokens):
            if token.type != TokenType.IDENTIFIER:
                continue
            next_index = index + 1
            if next_index < len(tokens) and tokens[next_index].type == TokenType.LEFT_BRACKET:
                next_index = self._skip_bracket_group_forward(tokens, next_index)
            if next_index < len(tokens) and tokens[next_index].type == TokenType.LEFT_PAREN:
                positions.add((token.line, token.column))
        return positions

    def _skip_bracket_group_forward(self, tokens: list[LexerToken], index: int) -> int:
        depth = 1
        index += 1
        while index < len(tokens) and depth > 0:
            if tokens[index].type == TokenType.LEFT_BRACKET:
                depth += 1
            elif tokens[index].type == TokenType.RIGHT_BRACKET:
                depth -= 1
            index += 1
        return index

    def _record_declaration_kind(
        self,
        tokens: list[LexerToken],
        declaration_kinds: dict[tuple[int, int], int],
        name: str,
        kind: int,
        start_line: int | None,
        end_line: int | None,
    ) -> None:
        for token in tokens:
            if start_line is not None and token.line < start_line:
                continue
            if end_line is not None and token.line > end_line:
                continue
            if token.type == TokenType.IDENTIFIER and token.value == name:
                declaration_kinds[(token.line, token.column)] = kind
                return

    def _semantic_kind_for_statement(self, statement: s.Statement_TopLevel) -> int | None:
        if isinstance(statement, s.Statement_FunctionDefinition | s.FunctionSignature):
            return SEM_FUNCTION
        if isinstance(statement, s.Statement_StructureDefinition):
            return SEM_STRUCT
        if isinstance(statement, s.Statement_EnumDefinition):
            return SEM_ENUM
        if isinstance(statement, s.Statement_Trait):
            return SEM_INTERFACE
        if isinstance(statement, s.Statement_Global):
            return SEM_VARIABLE
        return None

    def _semantic_token_kind(
        self,
        target: RefrainData | None,
        path: Path,
        token: LexerToken,
        semantic_context: _SemanticContext | None = None,
    ) -> int | None:
        if token.type in {
            TokenType.KW_FN,
            TokenType.KW_STRUCT,
            TokenType.KW_TRAIT,
            TokenType.KW_DYN,
            TokenType.KW_ENUM,
            TokenType.KW_IMPL,
            TokenType.KW_FOR,
            TokenType.KW_IN,
            TokenType.KW_LET,
            TokenType.KW_MUT,
            TokenType.KW_RET,
            TokenType.KW_WHILE,
            TokenType.KW_LOOP,
            TokenType.KW_WITH,
            TokenType.KW_DO,
            TokenType.KW_CONTINUE,
            TokenType.KW_BREAK,
            TokenType.KW_IF,
            TokenType.KW_ELIF,
            TokenType.KW_ELSE,
            TokenType.KW_MATCH,
            TokenType.KW_PUB,
            TokenType.KW_IMPORT,
            TokenType.KW_AS,
            TokenType.KW_EXTERN,
            TokenType.KW_UNSAFE,
            TokenType.KW_EHIR,
            TokenType.KW_MACRO_RULES,
            TokenType.BOOLEAN,
        }:
            return SEM_KEYWORD
        if token.type in {TokenType.INTEGER, TokenType.FLOAT}:
            return SEM_NUMBER
        if token.type == TokenType.STRING:
            return SEM_STRING
        if token.type in {TokenType.ONE_LINE_COMMENT, TokenType.MULTI_LINE_COMMENT}:
            return SEM_COMMENT
        if token.type in {
            TokenType.PLUS,
            TokenType.MINUS,
            TokenType.ASTERISK,
            TokenType.POWER,
            TokenType.SLASH,
            TokenType.PERCENT,
            TokenType.EQUAL_EQUAL,
            TokenType.BANG_EQUAL,
            TokenType.LESS,
            TokenType.GREATER,
            TokenType.LESS_EQUAL,
            TokenType.GREATER_EQUAL,
            TokenType.AND_AND,
            TokenType.PIPE_PIPE,
            TokenType.BANG,
            TokenType.AMPERSAND,
            TokenType.PIPE,
            TokenType.CARET,
            TokenType.TILDE,
            TokenType.LEFT_SHIFT,
            TokenType.RIGHT_SHIFT,
            TokenType.ASSIGN,
            TokenType.PLUS_EQUAL,
            TokenType.MINUS_EQUAL,
            TokenType.ASTERISK_EQUAL,
            TokenType.POWER_EQUAL,
            TokenType.SLASH_EQUAL,
            TokenType.PERCENT_EQUAL,
            TokenType.AMPERSAND_EQUAL,
            TokenType.PIPE_EQUAL,
            TokenType.CARET_EQUAL,
            TokenType.LEFT_SHIFT_EQUAL,
            TokenType.RIGHT_SHIFT_EQUAL,
            TokenType.ARROW,
            TokenType.FAT_ARROW,
            TokenType.SCOPE,
        }:
            return SEM_OPERATOR
        if token.type != TokenType.IDENTIFIER:
            return None
        if semantic_context is None:
            semantic_context = self._semantic_context(target, path) if target is not None else self._lexical_semantic_context(self._document_tokens(path))
        import_kind = semantic_context.import_token_kinds.get((token.line, token.column))
        if import_kind is not None:
            return import_kind
        declared_kind = semantic_context.declaration_kinds.get((token.line, token.column))
        if declared_kind is not None:
            return declared_kind
        visible_kind = semantic_context.visible_kinds.get(token.value)
        if visible_kind is not None:
            return visible_kind
        if (token.line, token.column) in semantic_context.call_tokens:
            return SEM_FUNCTION
        return SEM_VARIABLE

    def _format_document_text(self, text: str) -> str:
        lines = [line.rstrip(" \t") for line in text.splitlines()]
        formatted = "\n".join(lines)
        if formatted and not formatted.endswith("\n"):
            formatted += "\n"
        return formatted

    def _document_end_position(self, text: str) -> dict[str, int]:
        lines = text.splitlines()
        if not lines:
            return {"line": 0, "character": 0}
        if text.endswith("\n"):
            return {"line": len(lines), "character": 0}
        return {"line": len(lines) - 1, "character": len(lines[-1])}

    def _cached_or_schedule_project_diagnostics(self, path: Path) -> dict[Path, list[dict[str, object]]]:
        root = find_project_root(path)
        if root is None:
            return {path.resolve(): [self._diagnostic_to_lsp(CompileDiagnostic(message=f"Unable to find {ProjectManifest.default_filename()} for {path}"))]}
        signature, overrides, project_docs = self._diagnostic_snapshot(root, path)
        with self._state_lock:
            cached = self._diagnostic_cache.get(root)
            if cached is not None and cached.signature == signature:
                return cached.diagnostics
            stale = cached.diagnostics if cached is not None else {doc: [] for doc in project_docs}
        self._schedule_project_diagnostics_from_snapshot(path, root, signature, overrides, project_docs)
        return stale

    def _schedule_project_diagnostics(self, path: Path) -> None:
        root = find_project_root(path)
        if root is None:
            self._notify(
                "textDocument/publishDiagnostics",
                {
                    "uri": path_to_uri(path),
                    "diagnostics": [self._diagnostic_to_lsp(CompileDiagnostic(message=f"Unable to find {ProjectManifest.default_filename()} for {path}"))],
                },
            )
            return
        signature, overrides, project_docs = self._diagnostic_snapshot(root, path)
        self._schedule_project_diagnostics_from_snapshot(path, root, signature, overrides, project_docs)

    def _schedule_project_diagnostics_from_snapshot(
        self,
        path: Path,
        root: Path,
        signature: tuple[tuple[Path, str], ...],
        overrides: dict[Path, str],
        project_docs: set[Path],
    ) -> None:
        job_key = (root, signature)
        with self._state_lock:
            cached = self._diagnostic_cache.get(root)
            if cached is not None and cached.signature == signature:
                return
            if job_key in self._diagnostic_jobs:
                return
            self._diagnostic_jobs.add(job_key)

        thread = threading.Thread(
            target=self._run_project_diagnostics,
            args=(path.resolve(), root, signature, overrides, project_docs, job_key),
            daemon=True,
        )
        thread.start()

    def _run_project_diagnostics(
        self,
        path: Path,
        root: Path,
        signature: tuple[tuple[Path, str], ...],
        overrides: dict[Path, str],
        project_docs: set[Path],
        job_key: tuple[Path, tuple[tuple[Path, str], ...]],
    ) -> None:
        diagnostics = self._collect_project_diagnostics_snapshot(path, overrides, project_docs)
        with self._state_lock:
            self._diagnostic_jobs.discard(job_key)
            if self._diagnostic_signature_unlocked(root) != signature:
                return
            self._diagnostic_cache[root] = _DiagnosticCacheEntry(signature=signature, diagnostics=diagnostics)
        for diag_path, payload in diagnostics.items():
            self._notify("textDocument/publishDiagnostics", {"uri": path_to_uri(diag_path), "diagnostics": payload})

    def _diagnostic_snapshot(
        self,
        root: Path,
        path: Path,
    ) -> tuple[tuple[tuple[Path, str], ...], dict[Path, str], set[Path]]:
        with self._state_lock:
            overrides = {
                doc.resolve(): text
                for doc, text in self._open_documents.items()
                if find_project_root(doc) == root
            }
            signature = self._diagnostic_signature_unlocked(root)
        project_docs = set(overrides)
        project_docs.add(path.resolve())
        return signature, overrides, project_docs

    def _diagnostic_signature_unlocked(self, root: Path) -> tuple[tuple[Path, str], ...]:
        return tuple(
            sorted(
                (
                    doc.resolve(),
                    hashlib.sha1(text.encode("utf-8")).hexdigest(),
                )
                for doc, text in self._open_documents.items()
                if find_project_root(doc) == root
            )
        )

    def _collect_project_diagnostics(self, path: Path) -> dict[Path, list[dict[str, object]]]:
        root = find_project_root(path)
        if root is None:
            return {path.resolve(): [self._diagnostic_to_lsp(CompileDiagnostic(message=f"Unable to find {ProjectManifest.default_filename()} for {path}"))]}
        _signature, overrides, project_docs = self._diagnostic_snapshot(root, path)
        return self._collect_project_diagnostics_snapshot(path, overrides, project_docs)

    def _collect_project_diagnostics_snapshot(
        self,
        path: Path,
        overrides: dict[Path, str],
        project_docs: set[Path],
    ) -> dict[Path, list[dict[str, object]]]:
        try:
            target, manager = self._build_workspace_from_overrides(path, overrides)
            self._validate_workspace(target, manager)
        except Exception as exc:
            diag = exc if isinstance(exc, CompileDiagnostic) else CompileDiagnostic(message=str(exc), cause=exc)
            diag_path = (diag.module_id or path).resolve() if diag.module_id is not None else path.resolve()
            project_docs = {*project_docs, diag_path}
            return {doc: ([self._diagnostic_to_lsp(diag)] if doc == diag_path else []) for doc in project_docs}
        return {doc: [] for doc in project_docs}

    def _build_workspace_from_overrides(
        self,
        path: Path,
        overrides: dict[Path, str],
    ) -> tuple[RefrainData, RefrainManager]:
        root = find_project_root(path)
        if root is None:
            raise RuntimeError(f"Unable to find {ProjectManifest.default_filename()} for {path}")
        manager = RefrainManager(source_overrides={doc.resolve(): text for doc, text in overrides.items()})
        return manager.add_refrain_with_dependencies(root, is_binary_project(root)), manager

    def _impl_matches_binding(self, statement: s.Statement_Impl, binding: SymbolBinding) -> bool:
        if isinstance(binding.statement, s.Statement_Trait):
            return statement.trait_name == binding.source_name
        if isinstance(binding.statement, s.Statement_StructureDefinition | s.Statement_EnumDefinition):
            return statement.struct.name == binding.source_name
        if isinstance(binding.statement, s.Statement_FunctionDefinition | s.FunctionSignature):
            owner = self._owner_name_for_method(binding)
            return owner is not None and strip_generic_suffix(statement.struct.name.split("::")[-1]) == owner
        return False

    def _owner_name_for_method(self, binding: SymbolBinding) -> str | None:
        for refrain in self._collect_refrains(self._build_workspace(binding.module_id)[0]):
            for statements in refrain.symbols.local_ast_without_imports.values():
                for statement in statements:
                    if not isinstance(statement, s.Statement_Impl):
                        continue
                    for method in statement.body:
                        if method is binding.statement:
                            return strip_generic_suffix(statement.struct.name.split("::")[-1])
        return None

    def _is_callable_binding(self, binding: SymbolBinding) -> bool:
        return isinstance(binding.statement, s.Statement_FunctionDefinition | s.FunctionSignature)

    def _function_body_tokens(self, path: Path, binding: SymbolBinding) -> list[LexerToken]:
        if not isinstance(binding.statement, s.Statement_FunctionDefinition):
            return []
        line, column, _ = statement_span(binding.statement)
        if line is None or column is None:
            return []
        start_index = self._token_index_at(binding.module_id, line, column)
        if start_index is None:
            return []
        tokens = self._document_tokens(path)
        brace_index = None
        for index in range(start_index, len(tokens)):
            if tokens[index].type == TokenType.LEFT_BRACE:
                brace_index = index
                break
        if brace_index is None:
            return []
        depth = 0
        body: list[LexerToken] = []
        for token in tokens[brace_index:]:
            if token.type == TokenType.LEFT_BRACE:
                depth += 1
                continue
            if token.type == TokenType.RIGHT_BRACE:
                depth -= 1
                if depth == 0:
                    break
            if depth >= 1:
                body.append(token)
        return body

    def _is_call_token(self, path: Path, token: LexerToken) -> bool:
        tokens = self._document_tokens(path)
        for index, candidate in enumerate(tokens):
            if candidate.line != token.line or candidate.column != token.column or candidate.value != token.value:
                continue
            next_index = index + 1
            while next_index < len(tokens) and tokens[next_index].type in {TokenType.RIGHT_BRACKET, TokenType.LEFT_BRACKET, TokenType.COMMA, TokenType.SCOPE, TokenType.IDENTIFIER}:
                if tokens[next_index].type == TokenType.LEFT_PAREN:
                    return True
                next_index += 1
            return next_index < len(tokens) and tokens[next_index].type == TokenType.LEFT_PAREN
        return False

    def _enclosing_callable_binding(self, target: RefrainData, path: Path, line: int, character: int) -> SymbolBinding | None:
        module_ast = target.symbols.local_ast_without_imports.get(path.resolve(), [])
        candidates: list[s.Statement_FunctionDefinition] = []
        for statement in module_ast:
            if not isinstance(statement, s.Statement_FunctionDefinition):
                continue
            stmt_line, stmt_col, _ = statement_span(statement)
            if stmt_line is None or stmt_col is None:
                continue
            if stmt_line > line:
                continue
            candidates.append(statement)
        candidates.sort(key=lambda stmt: (statement_span(stmt)[0] or 0, statement_span(stmt)[1] or 0), reverse=True)
        for statement in candidates:
            binding = SymbolBinding(
                name=statement.signature.name,
                source_name=statement.signature.name,
                module_id=path.resolve(),
                statement=statement,
                is_public=statement.is_public,
            )
            body_tokens = self._function_body_tokens(path, binding)
            if body_tokens:
                start_token = body_tokens[0]
                end_token = body_tokens[-1]
                if start_token.line <= line <= end_token.line:
                    return binding
            for token in body_tokens:
                if token.line == line and token.column <= character < token.column + len(token.value):
                    return binding
        return None

    def _binding_location(self, binding: SymbolBinding) -> dict[str, object] | None:
        binding_range = self._binding_name_range(binding)
        if binding_range is None:
            line, column, span_length = statement_span(binding.statement)
            if line is None or column is None:
                return None
            binding_range = make_range(line, column, span_length)
        return {"uri": path_to_uri(binding.module_id), "range": binding_range}

    def _binding_name_range(self, binding: SymbolBinding) -> dict[str, object] | None:
        line, _, _ = statement_span(binding.statement)
        tokens = self._document_tokens(binding.module_id)
        search_start = line if line is not None else 0
        search_end = search_start + 80
        for token in tokens:
            if token.line < search_start or token.line > search_end:
                continue
            if token.type == TokenType.IDENTIFIER and token.value == binding.source_name:
                return self._token_range(token)
        for token in tokens:
            if token.type == TokenType.IDENTIFIER and token.value == binding.source_name:
                return self._token_range(token)
        return None

    def _diagnostic_to_lsp(self, diag: CompileDiagnostic) -> dict[str, object]:
        return {
            "range": make_range(diag.line, diag.column, diag.span_length),
            "severity": 1,
            "source": "encore-py",
            "message": diag.message if diag.stage is None else f"[{diag.stage}] {diag.message}",
        }

    def _collect_refrains(self, root: RefrainData) -> list[RefrainData]:
        result: list[RefrainData] = []
        seen: set[Path] = set()

        def visit(current: RefrainData) -> None:
            key = current.path.resolve()
            if key in seen:
                return
            seen.add(key)
            result.append(current)
            for dependency in current.dependencies:
                visit(dependency)

        visit(root)
        return result

    def _guess_root_from_open_docs(self) -> Path | None:
        for path in self._open_documents:
            root = find_project_root(path)
            if root is not None:
                return root
        cwd_root = find_project_root(Path.cwd() / "dummy.enq")
        return cwd_root

    def _request_position(self, params: dict[str, object]) -> tuple[Path, int, int]:
        text_document = params["textDocument"]
        position = params["position"]
        path = uri_to_path(text_document["uri"])
        return path, int(position["line"]), int(position["character"])

    def _read_message(self) -> dict[str, object] | None:
        headers: dict[str, str] = {}
        while True:
            line = sys.stdin.buffer.readline()
            if not line:
                return None
            if line in {b"\r\n", b"\n"}:
                break
            key, value = line.decode("ascii").split(":", 1)
            headers[key.strip().lower()] = value.strip()
        content_length = int(headers["content-length"])
        payload = sys.stdin.buffer.read(content_length)
        return json.loads(payload.decode("utf-8"))

    def _write_message(self, payload: dict[str, object]) -> None:
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        with self._write_lock:
            sys.stdout.buffer.write(f"Content-Length: {len(raw)}\r\n\r\n".encode("ascii"))
            sys.stdout.buffer.write(raw)
            sys.stdout.buffer.flush()

    def _reply(self, req_id: object, result: object) -> None:
        if req_id is None:
            return
        self._write_message({"jsonrpc": "2.0", "id": req_id, "result": result})

    def _reply_error(self, req_id: object, *, code: int, message: str) -> None:
        self._write_message({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}})

    def _notify(self, method: str, params: object) -> None:
        self._write_message({"jsonrpc": "2.0", "method": method, "params": params})


def run_stdio_server() -> int:
    server = EncoreLanguageServer()
    return server.run()
