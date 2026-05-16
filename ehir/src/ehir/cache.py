import json
from dataclasses import dataclass
from enum import Enum
from importlib import import_module
from pathlib import Path
from typing import Any

from ehir.refrain import CompiledRefrain

CACHE_FORMAT_VERSION = 2


def _load_symbol(module_name: str, qualname: str) -> type[Any]:
    symbol = import_module(module_name)
    for part in qualname.split("."):
        symbol = getattr(symbol, part)
    return symbol


def _encode(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value

    if isinstance(value, Path):
        return {
            "__kind__": "path",
            "value": value.as_posix(),
        }

    if isinstance(value, Enum):
        return {
            "__kind__": "enum",
            "module": value.__class__.__module__,
            "qualname": value.__class__.__qualname__,
            "name": value.name,
        }

    if isinstance(value, list):
        return [_encode(item) for item in value]

    if isinstance(value, tuple):
        return {
            "__kind__": "tuple",
            "items": [_encode(item) for item in value],
        }

    if isinstance(value, set):
        return {
            "__kind__": "set",
            "items": [_encode(item) for item in value],
        }

    if isinstance(value, dict):
        return {
            "__kind__": "dict",
            "items": [[_encode(key), _encode(item)] for key, item in value.items()],
        }

    if hasattr(value, "__dict__"):
        return {
            "__kind__": "object",
            "module": value.__class__.__module__,
            "qualname": value.__class__.__qualname__,
            "attrs": {key: _encode(item) for key, item in vars(value).items()},
        }

    raise TypeError(f"Unable to serialize {type(value)!r}")


def _decode(payload: Any) -> Any:
    if isinstance(payload, list):
        return [_decode(item) for item in payload]

    if not isinstance(payload, dict):
        return payload

    kind = payload.get("__kind__")
    if kind is None:
        return {key: _decode(value) for key, value in payload.items()}

    if kind == "path":
        return Path(payload["value"])

    if kind == "enum":
        enum_cls = _load_symbol(payload["module"], payload["qualname"])
        return enum_cls[payload["name"]]

    if kind == "tuple":
        return tuple(_decode(item) for item in payload["items"])

    if kind == "set":
        return {_decode(item) for item in payload["items"]}

    if kind == "dict":
        return {_decode(key): _decode(value) for key, value in payload["items"]}

    if kind == "object":
        object_cls = _load_symbol(payload["module"], payload["qualname"])
        obj = object_cls.__new__(object_cls)
        for key, value in payload["attrs"].items():
            setattr(obj, key, _decode(value))
        return obj

    raise TypeError(f"Unknown cache payload kind: {kind}")


@dataclass
class CompiledRefrainCache:
    cache_dir: Path

    def __post_init__(self):
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def load(self, refrain_name: str, semantic_hash: str) -> CompiledRefrain | None:
        cache_path = self._get_cache_path(refrain_name, semantic_hash)
        if not cache_path.exists():
            return None

        try:
            with cache_path.open("r") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError):
            return None

        if payload.get("format_version") != CACHE_FORMAT_VERSION:
            return None

        try:
            compiled_refrain = _decode(payload["compiled_refrain"])
        except (KeyError, TypeError, ValueError, AttributeError, ImportError):
            return None
        if compiled_refrain.semantic_hash != semantic_hash:
            return None

        return compiled_refrain

    def store(self, compiled_refrain: CompiledRefrain):
        cache_path = self._get_cache_path(compiled_refrain.name, compiled_refrain.semantic_hash)
        cache_path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "format_version": CACHE_FORMAT_VERSION,
            "compiled_refrain": _encode(compiled_refrain),
        }
        tmp_path = cache_path.with_suffix(f"{cache_path.suffix}.tmp")
        with tmp_path.open("w") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
        tmp_path.replace(cache_path)

    def _get_cache_path(self, refrain_name: str, semantic_hash: str) -> Path:
        return self.cache_dir / refrain_name / f"{semantic_hash}.json"
