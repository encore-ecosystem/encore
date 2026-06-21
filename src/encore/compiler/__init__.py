from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .compiler import EncoreCompiler


def __getattr__(name: str):
    if name == "EncoreCompiler":
        from .compiler import EncoreCompiler

        return EncoreCompiler
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "EncoreCompiler",
]
