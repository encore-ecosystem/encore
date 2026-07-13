import os
from importlib.metadata import version
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CORE_PATH = PROJECT_ROOT / "core"

ENCORE_CACHE_DIR = Path(os.getenv("ENCORE_CACHE_DIR", "~/.cache/encore")).expanduser().resolve()
ENCORE_INDEX_URL = "git@https://github.com/encore-language-index"

__version__ = version(__package__ or "encore")
