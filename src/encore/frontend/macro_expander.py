from dataclasses import dataclass

from encore.frontend.lexer.lexer import Lexer
from encore.frontend.lexer.tokens import LexerToken, TokenType
from encore.utils.diagnostics import CompileDiagnostic

OPEN_TO_CLOSE = {
    TokenType.LEFT_PAREN: TokenType.RIGHT_PAREN,
    TokenType.LEFT_BRACKET: TokenType.RIGHT_BRACKET,
    TokenType.LEFT_BRACE: TokenType.RIGHT_BRACE,
}
CLOSE_TO_OPEN = {v: k for k, v in OPEN_TO_CLOSE.items()}
REPEAT_OPS = {TokenType.ASTERISK, TokenType.PLUS, TokenType.QUESTION}


@dataclass(frozen=True)
class PatternLiteral:
    token: LexerToken


@dataclass(frozen=True)
class PatternCapture:
    name: str
    kind: str


@dataclass(frozen=True)
class PatternRepeat:
    body: list["PatternNode"]
    separator: LexerToken | None
    op: TokenType


PatternNode = PatternLiteral | PatternCapture | PatternRepeat


@dataclass(frozen=True)
class TemplateLiteral:
    token: LexerToken


@dataclass(frozen=True)
class TemplateVar:
    name: str


@dataclass(frozen=True)
class TemplateRepeat:
    body: list["TemplateNode"]
    separator: LexerToken | None
    op: TokenType


TemplateNode = TemplateLiteral | TemplateVar | TemplateRepeat


@dataclass(frozen=True)
class MacroRule:
    pattern: list[PatternNode]
    template: list[TemplateNode]


@dataclass(frozen=True)
class MacroDef:
    name: str
    rules: list[MacroRule]


class MacroExpander:
    def __init__(self, *, max_rounds: int = 64):
        self._max_rounds = max_rounds
        self._gensym = 0
        self._inline_lexer = Lexer()

    def expand(self, tokens: list[LexerToken]) -> list[LexerToken]:
        tokens = self._lower_fstrings(tokens)
        macros: dict[str, MacroDef] = {}
        stripped = self._strip_macro_defs(tokens, macros)
        return self._expand_calls_recursively(stripped, macros)

    def _lower_fstrings(self, tokens: list[LexerToken]) -> list[LexerToken]:
        out: list[LexerToken] = []
        i = 0
        while i < len(tokens):
            if (
                i + 1 < len(tokens)
                and tokens[i].type == TokenType.IDENTIFIER
                and tokens[i].value == "f"
                and tokens[i + 1].type == TokenType.STRING
            ):
                fmt_literal, args = self._build_format_call_from_fstring(tokens[i + 1])
                out.append(
                    LexerToken(type=TokenType.IDENTIFIER, value="format", line=tokens[i].line, column=tokens[i].column)
                )
                out.append(LexerToken(type=TokenType.BANG, value="!", line=tokens[i].line, column=tokens[i].column))
                out.append(LexerToken(type=TokenType.LEFT_PAREN, value="(", line=tokens[i].line, column=tokens[i].column))
                out.append(LexerToken(type=TokenType.STRING, value=fmt_literal, line=tokens[i].line, column=tokens[i].column))
                for arg in args:
                    out.append(LexerToken(type=TokenType.COMMA, value=",", line=tokens[i].line, column=tokens[i].column))
                    out.extend(
                        LexerToken(type=t.type, value=t.value, line=tokens[i].line, column=tokens[i].column) for t in arg
                    )
                out.append(LexerToken(type=TokenType.RIGHT_PAREN, value=")", line=tokens[i].line, column=tokens[i].column))
                i += 2
                continue
            out.append(tokens[i])
            i += 1
        return out

    def _strip_macro_defs(self, tokens: list[LexerToken], macros: dict[str, MacroDef]) -> list[LexerToken]:
        out: list[LexerToken] = []
        i = 0
        while i < len(tokens):
            if tokens[i].type != TokenType.KW_MACRO_RULES:
                out.append(tokens[i])
                i += 1
                continue
            i += 1
            i = self._expect(tokens, i, TokenType.BANG)
            name_tok = tokens[i]
            i = self._expect(tokens, i, TokenType.IDENTIFIER)
            i = self._expect(tokens, i, TokenType.LEFT_BRACE)
            body_all, i = self._collect_balanced(tokens, i - 1)
            macros[name_tok.value] = MacroDef(name=name_tok.value, rules=self._parse_rules(body_all[1:-1]))
        return out

    def _parse_rules(self, body: list[LexerToken]) -> list[MacroRule]:
        rules: list[MacroRule] = []
        i = 0
        while i < len(body):
            if body[i].type == TokenType.SEMICOLON:
                i += 1
                continue
            if body[i].type not in OPEN_TO_CLOSE:
                break
            pattern_all, i = self._collect_balanced(body, i)
            i = self._expect(body, i, TokenType.FAT_ARROW)
            if i >= len(body) or body[i].type not in OPEN_TO_CLOSE:
                raise CompileDiagnostic(message="macro_rules arm must have delimited template")
            template_all, i = self._collect_balanced(body, i)
            if i < len(body) and body[i].type == TokenType.SEMICOLON:
                i += 1
            p = pattern_all[1:-1]
            t = template_all[1:-1]
            pattern = self._parse_pattern_sequence(p, 0, len(p))[0]
            template = self._parse_template_sequence(t, 0, len(t))[0]
            rules.append(MacroRule(pattern=pattern, template=template))
        return rules

    def _expand_calls_recursively(self, tokens: list[LexerToken], macros: dict[str, MacroDef]) -> list[LexerToken]:
        current = tokens
        for _ in range(self._max_rounds):
            next_tokens, changed = self._expand_calls_one_round(current, macros)
            if not changed:
                return current
            current = next_tokens
        raise CompileDiagnostic(message="Macro expansion exceeded recursion limit")

    def _expand_calls_one_round(self, tokens: list[LexerToken], macros: dict[str, MacroDef]) -> tuple[list[LexerToken], bool]:
        out: list[LexerToken] = []
        changed = False
        i = 0
        while i < len(tokens):
            if i + 2 < len(tokens) and tokens[i].type == TokenType.IDENTIFIER and tokens[i + 1].type == TokenType.BANG:
                if tokens[i + 2].type not in OPEN_TO_CLOSE:
                    out.append(tokens[i])
                    i += 1
                    continue
                name = tokens[i].value
                args_all, next_i = self._collect_balanced(tokens, i + 2)
                if name == "vec":
                    out.extend(self._expand_builtin_vec(args_all[1:-1], args_all[0]))
                    i = next_i
                    changed = True
                    continue
                if name == "format":
                    out.extend(self._expand_builtin_format(args_all[1:-1], args_all[0]))
                    i = next_i
                    changed = True
                    continue
                if name in macros:
                    out.extend(self._expand_one(macros[name], args_all[1:-1], args_all[0]))
                    i = next_i
                    changed = True
                    continue
            out.append(tokens[i])
            i += 1
        return out, changed

    def _expand_one(self, macro: MacroDef, args: list[LexerToken], callsite: LexerToken) -> list[LexerToken]:
        for rule in macro.rules:
            captures = self._match_pattern(rule.pattern, args)
            if captures is None:
                continue
            rendered = self._render_template(rule.template, captures, {})
            return [LexerToken(type=x.type, value=x.value, line=callsite.line, column=callsite.column) for x in rendered]
        raise CompileDiagnostic(
            message=f"No macro_rules arm matched for {macro.name}!(...)",
            line=callsite.line,
            column=callsite.column,
        )

    def _expand_builtin_format(self, args: list[LexerToken], callsite: LexerToken) -> list[LexerToken]:
        parts = self._split_top_level_args(args)
        if not parts:
            raise CompileDiagnostic(message="format! expects at least a format string", line=callsite.line, column=callsite.column)
        fmt = parts[0]
        if len(fmt) != 1 or fmt[0].type != TokenType.STRING:
            raise CompileDiagnostic(message="format! first argument must be a string literal", line=callsite.line, column=callsite.column)
        raw = fmt[0].value
        chunks, placeholders = self._parse_format_template(raw, callsite)
        positional = parts[1:]
        pos_idx = 0
        expr_parts: list[list[LexerToken]] = []
        for idx, chunk in enumerate(chunks):
            if chunk:
                expr_parts.append([LexerToken(type=TokenType.STRING, value=self._quote_string(chunk), line=callsite.line, column=callsite.column)])
            if idx >= len(placeholders):
                continue
            hole = placeholders[idx]
            expr: list[LexerToken]
            if hole == "" or hole == "#":
                if pos_idx >= len(positional):
                    raise CompileDiagnostic(
                        message="format! missing positional argument for '{}' placeholder",
                        line=callsite.line,
                        column=callsite.column,
                    )
                expr = positional[pos_idx]
                pos_idx += 1
            else:
                name = hole[1:] if hole.startswith("#") else hole
                expr = [LexerToken(type=TokenType.IDENTIFIER, value=name, line=callsite.line, column=callsite.column)]
            expr_parts.append(
                [
                    LexerToken(type=TokenType.IDENTIFIER, value="Debug", line=callsite.line, column=callsite.column),
                    LexerToken(type=TokenType.SCOPE, value="::", line=callsite.line, column=callsite.column),
                    LexerToken(type=TokenType.IDENTIFIER, value="fmt", line=callsite.line, column=callsite.column),
                    LexerToken(type=TokenType.LEFT_PAREN, value="(", line=callsite.line, column=callsite.column),
                    *[LexerToken(type=t.type, value=t.value, line=callsite.line, column=callsite.column) for t in expr],
                    LexerToken(type=TokenType.RIGHT_PAREN, value=")", line=callsite.line, column=callsite.column),
                ]
            )
        if pos_idx != len(positional):
            raise CompileDiagnostic(
                message="format! has unused positional arguments",
                line=callsite.line,
                column=callsite.column,
            )
        if not expr_parts:
            return [LexerToken(type=TokenType.STRING, value='""', line=callsite.line, column=callsite.column)]
        out: list[LexerToken] = []
        for idx, part in enumerate(expr_parts):
            if idx > 0:
                out.append(LexerToken(type=TokenType.PLUS, value="+", line=callsite.line, column=callsite.column))
            out.extend(part)
        return out

    def _expand_builtin_vec(self, args: list[LexerToken], callsite: LexerToken) -> list[LexerToken]:
        items = self._split_top_level_args(args)
        if not items:
            return [
                LexerToken(type=TokenType.IDENTIFIER, value="Vec", line=callsite.line, column=callsite.column),
                LexerToken(type=TokenType.SCOPE, value="::", line=callsite.line, column=callsite.column),
                LexerToken(type=TokenType.IDENTIFIER, value="new", line=callsite.line, column=callsite.column),
                LexerToken(type=TokenType.LEFT_PAREN, value="(", line=callsite.line, column=callsite.column),
                LexerToken(type=TokenType.RIGHT_PAREN, value=")", line=callsite.line, column=callsite.column),
            ]
        self._gensym += 1
        var = f"__macro_vec_tmp_{self._gensym}"
        inferred_type = self._infer_type_tokens_from_expr(items[0], callsite)
        def tok(tt: TokenType, v: str) -> LexerToken:
            return LexerToken(type=tt, value=v, line=callsite.line, column=callsite.column)

        out: list[LexerToken] = [tok(TokenType.LEFT_BRACE, "{"), tok(TokenType.KW_LET, "let"), tok(TokenType.KW_MUT, "mut"), tok(TokenType.IDENTIFIER, var)]
        if inferred_type is not None:
            out.extend([tok(TokenType.COLON, ":"), tok(TokenType.IDENTIFIER, "Vec"), tok(TokenType.LEFT_BRACKET, "["), *inferred_type, tok(TokenType.RIGHT_BRACKET, "]")])
        out.extend([tok(TokenType.ASSIGN, "="), tok(TokenType.IDENTIFIER, "Vec")])
        if inferred_type is not None:
            out.extend([tok(TokenType.LEFT_BRACKET, "["), *inferred_type, tok(TokenType.RIGHT_BRACKET, "]")])
        out.extend([tok(TokenType.SCOPE, "::"), tok(TokenType.IDENTIFIER, "new"), tok(TokenType.LEFT_PAREN, "("), tok(TokenType.RIGHT_PAREN, ")")])
        for item in items:
            out.extend(
                [
                    tok(TokenType.IDENTIFIER, var),
                    tok(TokenType.ASSIGN, "="),
                    tok(TokenType.IDENTIFIER, "Vec"),
                    tok(TokenType.SCOPE, "::"),
                    tok(TokenType.IDENTIFIER, "push"),
                    tok(TokenType.LEFT_PAREN, "("),
                    tok(TokenType.IDENTIFIER, var),
                    tok(TokenType.COMMA, ","),
                    *[LexerToken(type=x.type, value=x.value, line=callsite.line, column=callsite.column) for x in item],
                    tok(TokenType.RIGHT_PAREN, ")"),
                ]
            )
        out.extend([tok(TokenType.IDENTIFIER, var), tok(TokenType.RIGHT_BRACE, "}")])
        return out

    def _build_format_call_from_fstring(self, string_tok: LexerToken) -> tuple[str, list[list[LexerToken]]]:
        chunks, placeholders = self._parse_format_template(string_tok.value, string_tok)
        rendered = ""
        args: list[list[LexerToken]] = []
        for idx, chunk in enumerate(chunks):
            rendered += chunk
            if idx >= len(placeholders):
                continue
            hole = placeholders[idx]
            rendered += "{}"
            expr_src = hole[1:].strip() if hole.startswith("#") else hole
            if not expr_src:
                raise CompileDiagnostic(
                    message="f-string placeholder can not be empty",
                    line=string_tok.line,
                    column=string_tok.column,
                )
            args.append(self._lex_inline_expr(expr_src, string_tok))
        return self._quote_string(rendered), args

    def _parse_format_template(self, raw_string_token_value: str, callsite: LexerToken) -> tuple[list[str], list[str]]:
        if len(raw_string_token_value) < 2 or raw_string_token_value[0] != '"' or raw_string_token_value[-1] != '"':
            raise CompileDiagnostic(message="Invalid string literal in format template", line=callsite.line, column=callsite.column)
        s = raw_string_token_value[1:-1]
        chunks: list[str] = []
        placeholders: list[str] = []
        curr = ""
        i = 0
        while i < len(s):
            ch = s[i]
            if ch == "{":
                if i + 1 < len(s) and s[i + 1] == "{":
                    curr += "{"
                    i += 2
                    continue
                end = s.find("}", i + 1)
                if end == -1:
                    raise CompileDiagnostic(message="Unclosed '{' in format string", line=callsite.line, column=callsite.column)
                hole = s[i + 1 : end].strip()
                chunks.append(curr)
                curr = ""
                placeholders.append(hole)
                i = end + 1
                continue
            if ch == "}" and i + 1 < len(s) and s[i + 1] == "}":
                curr += "}"
                i += 2
                continue
            if ch == "}":
                raise CompileDiagnostic(message="Unmatched '}' in format string", line=callsite.line, column=callsite.column)
            curr += ch
            i += 1
        chunks.append(curr)
        return chunks, placeholders

    def _quote_string(self, s: str) -> str:
        escaped = s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")
        return f'"{escaped}"'

    def _lex_inline_expr(self, expr_src: str, callsite: LexerToken) -> list[LexerToken]:
        try:
            return self._inline_lexer.parse(list(expr_src))
        except Exception as exc:  # pragma: no cover - defensive diagnostic wrapper
            raise CompileDiagnostic(
                message=f"Invalid expression in f-string placeholder: {expr_src}",
                line=callsite.line,
                column=callsite.column,
            ) from exc

    def _match_pattern(self, nodes: list[PatternNode], args: list[LexerToken]) -> dict[str, object] | None:
        cap, cur = self._match_nodes(nodes, args, 0, {}, None)
        if cap is None or cur != len(args):
            return None
        return cap

    def _match_nodes(
        self,
        nodes: list[PatternNode],
        args: list[LexerToken],
        cursor: int,
        captures: dict[str, object],
        stop_token: LexerToken | None,
    ) -> tuple[dict[str, object] | None, int]:
        for idx, node in enumerate(nodes):
            if isinstance(node, PatternLiteral):
                if cursor >= len(args):
                    return None, cursor
                t = args[cursor]
                if t.type != node.token.type or t.value != node.token.value:
                    return None, cursor
                cursor += 1
                continue

            if isinstance(node, PatternCapture):
                next_fixed = self._next_pattern_literal(nodes, idx + 1) or stop_token
                val, next_cursor = self._capture_fragment(args, cursor, node.kind, next_fixed)
                if val is None:
                    return None, cursor
                captures[node.name] = val
                cursor = next_cursor
                continue

            if isinstance(node, PatternRepeat):
                repeat_values: dict[str, list[list[LexerToken]]] = {}
                count = 0
                while True:
                    local, next_cursor = self._match_nodes(node.body, args, cursor, {}, node.separator)
                    if local is None:
                        break
                    for k, v in local.items():
                        if isinstance(v, list) and v and isinstance(v[0], LexerToken):
                            repeat_values.setdefault(k, []).append(v)
                    cursor = next_cursor
                    count += 1
                    if node.separator is not None and cursor < len(args):
                        s = args[cursor]
                        if s.type == node.separator.type and s.value == node.separator.value:
                            cursor += 1
                            continue
                    if node.separator is None:
                        continue
                    break

                if node.op == TokenType.PLUS and count == 0:
                    return None, cursor
                if node.op == TokenType.QUESTION and count > 1:
                    return None, cursor
                for k, values in repeat_values.items():
                    captures[k] = values
                continue
        return captures, cursor

    def _next_pattern_literal(self, nodes: list[PatternNode], start: int) -> LexerToken | None:
        for i in range(start, len(nodes)):
            n = nodes[i]
            if isinstance(n, PatternLiteral):
                return n.token
        return None

    def _capture_fragment(
        self, args: list[LexerToken], start: int, kind: str, next_fixed: LexerToken | None
    ) -> tuple[list[LexerToken] | None, int]:
        if kind == "ident":
            if start >= len(args) or args[start].type != TokenType.IDENTIFIER:
                return None, start
            return [args[start]], start + 1
        depth = 0
        i = start
        while i < len(args):
            t = args[i]
            if t.type in OPEN_TO_CLOSE:
                depth += 1
            elif t.type in CLOSE_TO_OPEN:
                depth -= 1
            if depth == 0 and next_fixed is not None and t.type == next_fixed.type and t.value == next_fixed.value:
                break
            i += 1
        if kind in {"expr", "tt"}:
            if i == start:
                return None, start
            return args[start:i], i
        return None, start

    def _render_template(self, nodes: list[TemplateNode], captures: dict[str, object], rep_index: dict[str, int]) -> list[LexerToken]:
        out: list[LexerToken] = []
        for node in nodes:
            if isinstance(node, TemplateLiteral):
                out.append(node.token)
                continue
            if isinstance(node, TemplateVar):
                value = captures.get(node.name)
                if value is None:
                    raise CompileDiagnostic(message=f"Unknown macro template variable '${node.name}'")
                if isinstance(value, list) and value and isinstance(value[0], LexerToken):
                    out.extend(value)
                    continue
                if isinstance(value, list) and (not value or isinstance(value[0], list)):
                    if node.name not in rep_index:
                        raise CompileDiagnostic(message=f"Template variable '${node.name}' used outside repetition")
                    idx = rep_index[node.name]
                    if idx >= len(value):
                        raise CompileDiagnostic(message=f"Template repetition index out of range for '${node.name}'")
                    out.extend(value[idx])
                    continue
                raise CompileDiagnostic(message=f"Unsupported capture shape for '${node.name}'")
            if isinstance(node, TemplateRepeat):
                vars_in = self._collect_template_vars(node.body)
                repeated = [v for v in vars_in if isinstance(captures.get(v), list) and captures.get(v)]
                count = 0
                if repeated:
                    first = captures[repeated[0]]
                    if isinstance(first, list) and (not first or isinstance(first[0], list)):
                        count = len(first)
                if node.op == TokenType.QUESTION:
                    count = min(count, 1) if count > 0 else 0
                if node.op == TokenType.PLUS and count == 0:
                    raise CompileDiagnostic(message="Template repetition '+' has zero captures")
                for i in range(count):
                    scoped = dict(rep_index)
                    for v in repeated:
                        scoped[v] = i
                    out.extend(self._render_template(node.body, captures, scoped))
                    if node.separator is not None and i + 1 < count:
                        out.append(node.separator)
        return out

    def _collect_template_vars(self, nodes: list[TemplateNode]) -> set[str]:
        names: set[str] = set()
        for n in nodes:
            if isinstance(n, TemplateVar):
                names.add(n.name)
            elif isinstance(n, TemplateRepeat):
                names |= self._collect_template_vars(n.body)
        return names

    def _parse_pattern_sequence(self, tokens: list[LexerToken], start: int, end: int) -> tuple[list[PatternNode], int]:
        out: list[PatternNode] = []
        i = start
        while i < end:
            t = tokens[i]
            if t.type == TokenType.DOLLAR:
                if i + 1 >= end:
                    raise CompileDiagnostic(message="Incomplete '$' in macro pattern")
                nxt = tokens[i + 1]
                if nxt.type in OPEN_TO_CLOSE:
                    group_all, ni = self._collect_balanced(tokens, i + 1)
                    body_tokens = group_all[1:-1]
                    body = self._parse_pattern_sequence(body_tokens, 0, len(body_tokens))[0]
                    sep = None
                    op_idx = ni
                    if op_idx + 1 < end and tokens[op_idx].type in REPEAT_OPS and tokens[op_idx + 1].type in REPEAT_OPS:
                        sep = tokens[op_idx]
                        op_idx += 1
                    if op_idx < end and tokens[op_idx].type not in REPEAT_OPS:
                        sep = tokens[op_idx]
                        op_idx += 1
                    if op_idx >= end or tokens[op_idx].type not in REPEAT_OPS:
                        raise CompileDiagnostic(message="Expected repetition operator after $() in macro pattern")
                    out.append(PatternRepeat(body=body, separator=sep, op=tokens[op_idx].type))
                    i = op_idx + 1
                    continue
                if i + 3 >= end:
                    raise CompileDiagnostic(message="Invalid capture in macro pattern")
                name = tokens[i + 1]
                colon = tokens[i + 2]
                kind = tokens[i + 3]
                if name.type != TokenType.IDENTIFIER or colon.type != TokenType.COLON or kind.type != TokenType.IDENTIFIER:
                    raise CompileDiagnostic(message="Invalid capture syntax in macro pattern")
                out.append(PatternCapture(name=name.value, kind=kind.value))
                i += 4
                continue
            out.append(PatternLiteral(t))
            i += 1
        return out, i

    def _parse_template_sequence(self, tokens: list[LexerToken], start: int, end: int) -> tuple[list[TemplateNode], int]:
        out: list[TemplateNode] = []
        i = start
        while i < end:
            t = tokens[i]
            if t.type == TokenType.DOLLAR:
                if i + 1 >= end:
                    raise CompileDiagnostic(message="Incomplete '$' in macro template")
                nxt = tokens[i + 1]
                if nxt.type in OPEN_TO_CLOSE:
                    group_all, ni = self._collect_balanced(tokens, i + 1)
                    body_tokens = group_all[1:-1]
                    body = self._parse_template_sequence(body_tokens, 0, len(body_tokens))[0]
                    sep = None
                    op_idx = ni
                    if op_idx + 1 < end and tokens[op_idx].type in REPEAT_OPS and tokens[op_idx + 1].type in REPEAT_OPS:
                        sep = tokens[op_idx]
                        op_idx += 1
                    if op_idx < end and tokens[op_idx].type not in REPEAT_OPS:
                        sep = tokens[op_idx]
                        op_idx += 1
                    if op_idx >= end or tokens[op_idx].type not in REPEAT_OPS:
                        raise CompileDiagnostic(message="Expected repetition operator after $() in macro template")
                    out.append(TemplateRepeat(body=body, separator=sep, op=tokens[op_idx].type))
                    i = op_idx + 1
                    continue
                if nxt.type != TokenType.IDENTIFIER:
                    raise CompileDiagnostic(message="Expected identifier after '$' in macro template")
                out.append(TemplateVar(name=nxt.value))
                i += 2
                continue
            out.append(TemplateLiteral(t))
            i += 1
        return out, i

    def _collect_balanced(self, tokens: list[LexerToken], start: int) -> tuple[list[LexerToken], int]:
        open_tok = tokens[start]
        if open_tok.type not in OPEN_TO_CLOSE:
            raise CompileDiagnostic(message="Expected opening delimiter")
        close_type = OPEN_TO_CLOSE[open_tok.type]
        depth = 0
        out: list[LexerToken] = []
        i = start
        while i < len(tokens):
            tok = tokens[i]
            out.append(tok)
            if tok.type == open_tok.type:
                depth += 1
            elif tok.type == close_type:
                depth -= 1
                if depth == 0:
                    return out, i + 1
            i += 1
        raise CompileDiagnostic(message="Unclosed delimiter in macro")

    def _expect(self, tokens: list[LexerToken], index: int, token_type: TokenType) -> int:
        if index >= len(tokens) or tokens[index].type != token_type:
            raise CompileDiagnostic(message=f"Expected {token_type.name} in macro definition")
        return index + 1

    def _split_top_level_args(self, tokens: list[LexerToken]) -> list[list[LexerToken]]:
        if not tokens:
            return []
        out: list[list[LexerToken]] = []
        curr: list[LexerToken] = []
        depth = 0
        for tok in tokens:
            if tok.type in OPEN_TO_CLOSE:
                depth += 1
            elif tok.type in CLOSE_TO_OPEN:
                depth -= 1
            if tok.type == TokenType.COMMA and depth == 0:
                if curr:
                    out.append(curr)
                    curr = []
                continue
            curr.append(tok)
        if curr:
            out.append(curr)
        return out

    def _infer_type_tokens_from_expr(self, item: list[LexerToken], callsite: LexerToken) -> list[LexerToken] | None:
        if not item:
            return None
        first = item[0]
        if first.type == TokenType.STRING:
            return [LexerToken(type=TokenType.IDENTIFIER, value="str", line=callsite.line, column=callsite.column)]
        if first.type == TokenType.BOOLEAN:
            return [LexerToken(type=TokenType.IDENTIFIER, value="bool", line=callsite.line, column=callsite.column)]
        if len(item) >= 2 and first.type in {TokenType.INTEGER, TokenType.FLOAT} and item[1].type == TokenType.IDENTIFIER:
            suffix = item[1].value
            if suffix.startswith("_") and len(suffix) > 1:
                return [LexerToken(type=TokenType.IDENTIFIER, value=suffix[1:], line=callsite.line, column=callsite.column)]
        return None
