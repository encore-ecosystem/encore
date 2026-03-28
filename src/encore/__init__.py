import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


ENCORE_CACHE_DIR = Path(os.getenv("ENCORE_CACHE_DIR", "~/.cache/encore")).expanduser().resolve()
