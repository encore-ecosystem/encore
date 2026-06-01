import platform
import re
import sys
from dataclasses import dataclass, field
from typing import Iterable


@dataclass(frozen=True)
class CfgEnvironment:
    flags: frozenset[str] = field(default_factory=frozenset)
    values: dict[str, str] = field(default_factory=dict)

    def has_flag(self, name: str) -> bool:
        return name in self.flags

    def get(self, name: str) -> str | None:
        return self.values.get(name)

    def with_overrides(self, overrides: Iterable[str]) -> "CfgEnvironment":
        flags = set(self.flags)
        values = dict(self.values)
        for raw in overrides:
            item = raw.strip()
            if not item:
                continue
            if "=" in item:
                key, value = item.split("=", 1)
                key = key.strip()
                value = _strip_quotes(value.strip())
                values[key] = value
                flags.add(f"{key}_{value}")
            else:
                flags.add(item)
        return CfgEnvironment(flags=frozenset(flags), values=values)


def default_cfg_environment(*, backend: str | None = None, extra: Iterable[str] = ()) -> CfgEnvironment:
    target_os = _detect_target_os()
    target_family = "windows" if target_os == "windows" else "unix"
    arch = platform.machine().lower() or "unknown"
    ptr_width = "64" if sys.maxsize > 2**32 else "32"

    values = {
        "target_os": target_os,
        "target_family": target_family,
        "target_arch": arch,
        "target_pointer_width": ptr_width,
    }
    if backend is not None:
        values["backend"] = backend

    flags = {
        target_os,
        target_family,
        arch,
        f"ptr{ptr_width}",
        f"target_os_{target_os}",
        f"target_family_{target_family}",
    }
    if target_family == "unix":
        flags.add("posix")
    if backend is not None:
        flags.add(backend)
        flags.add(f"backend_{backend}")

    return CfgEnvironment(flags=frozenset(flags), values=values).with_overrides(extra)


def cfg_matches(expr: str, env: CfgEnvironment) -> bool:
    tokens = _CfgLexer(expr).tokenize()
    parser = _CfgParser(tokens, env)
    value = parser.parse()
    if not parser.at_end:
        raise ValueError(f"Unexpected cfg token '{parser.peek().value}' in '{expr}'")
    return value


def filter_cfg_items[T](items: list[T], env: CfgEnvironment) -> list[T]:
    result: list[T] = []
    for item in items:
        if not item_matches_cfg(item, env):
            continue
        _filter_nested_cfg(item, env)
        result.append(item)
    return result


def item_matches_cfg(item: object, env: CfgEnvironment) -> bool:
    cfgs = getattr(item, "cfgs", ())
    return all(cfg_matches(expr, env) for expr in cfgs)


def set_item_cfgs(item: object, cfgs: Iterable[str]) -> None:
    values = tuple(dict.fromkeys(expr.strip() for expr in cfgs if expr.strip()))
    if values:
        setattr(item, "cfgs", values)


def _filter_nested_cfg(item: object, env: CfgEnvironment) -> None:
    if hasattr(item, "methods"):
        setattr(item, "methods", filter_cfg_items(list(getattr(item, "methods")), env))
    if hasattr(item, "body"):
        body = getattr(item, "body")
        if isinstance(body, list):
            setattr(item, "body", filter_cfg_items(list(body), env))


def _detect_target_os() -> str:
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith(("win32", "cygwin", "msys")):
        return "windows"
    if sys.platform.startswith("freebsd"):
        return "freebsd"
    if sys.platform.startswith("openbsd"):
        return "openbsd"
    if sys.platform.startswith("netbsd"):
        return "netbsd"
    return sys.platform.split("-", 1)[0].lower()


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


@dataclass(frozen=True)
class _CfgToken:
    kind: str
    value: str


class _CfgLexer:
    _token_re = re.compile(
        r"""
        (?P<space>\s+)
        |(?P<string>"(?:\\.|[^"])*"|'(?:\\.|[^'])*')
        |(?P<ident>[A-Za-z_][A-Za-z0-9_]*)
        |(?P<eq>=)
        |(?P<lpar>\()
        |(?P<rpar>\))
        |(?P<comma>,)
        """,
        re.VERBOSE,
    )

    def __init__(self, source: str):
        self.source = source

    def tokenize(self) -> list[_CfgToken]:
        tokens: list[_CfgToken] = []
        index = 0
        while index < len(self.source):
            match = self._token_re.match(self.source, index)
            if match is None:
                raise ValueError(f"Invalid cfg expression near '{self.source[index:]}'")
            index = match.end()
            kind = match.lastgroup
            if kind == "space":
                continue
            assert kind is not None
            tokens.append(_CfgToken(kind, match.group(kind)))
        return tokens


class _CfgParser:
    def __init__(self, tokens: list[_CfgToken], env: CfgEnvironment):
        self.tokens = tokens
        self.env = env
        self.index = 0

    @property
    def at_end(self) -> bool:
        return self.index >= len(self.tokens)

    def peek(self) -> _CfgToken:
        if self.at_end:
            return _CfgToken("eof", "")
        return self.tokens[self.index]

    def consume(self, kind: str | None = None) -> _CfgToken:
        token = self.peek()
        if kind is not None and token.kind != kind:
            raise ValueError(f"Expected cfg token '{kind}', got '{token.value}'")
        self.index += 1
        return token

    def parse(self) -> bool:
        if self.at_end:
            raise ValueError("Empty cfg expression")
        return self._parse_predicate()

    def _parse_predicate(self) -> bool:
        name = self.consume("ident").value
        if self.peek().kind == "eq":
            self.consume("eq")
            expected = self._parse_value()
            return self.env.get(name) == expected

        if self.peek().kind != "lpar":
            return self.env.has_flag(name)

        self.consume("lpar")
        if name == "not":
            result = not self._parse_predicate()
            self.consume("rpar")
            return result

        values: list[bool] = []
        if self.peek().kind != "rpar":
            values.append(self._parse_predicate())
            while self.peek().kind == "comma":
                self.consume("comma")
                values.append(self._parse_predicate())
        self.consume("rpar")

        if name == "all":
            return all(values)
        if name == "any":
            return any(values)
        raise ValueError(f"Unknown cfg predicate '{name}'")

    def _parse_value(self) -> str:
        token = self.peek()
        if token.kind == "string":
            return _strip_quotes(self.consume("string").value)
        if token.kind == "ident":
            return self.consume("ident").value
        raise ValueError(f"Expected cfg value, got '{token.value}'")
