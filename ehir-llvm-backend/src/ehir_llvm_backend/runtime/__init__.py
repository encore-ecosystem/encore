from pathlib import Path


def runtime_c_path() -> Path:
    return Path(__file__).with_name("runtime.c")


__all__ = ["runtime_c_path"]
