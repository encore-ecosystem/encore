import os
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


ENCORE_CACHE_DIR = Path(os.getenv("ENCORE_CACHE_DIR", "~/.cache/encore")).expanduser().resolve()

try:
    __version__ = version(__package__ or "encore")
except PackageNotFoundError:
    __version__ = "0.0.0-dev"
