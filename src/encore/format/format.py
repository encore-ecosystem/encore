from ehir.format.theme import ThemePalette
from rich.console import Console

RICH_TEXT = True

_console = Console(highlight=False)


def printfmt(text: str, style: ThemePalette = ThemePalette.COMMON_TEXT) -> None:
    if RICH_TEXT:
        _console.print(text, style=style.value, markup=False, end="")
    else:
        print(text, end="")
