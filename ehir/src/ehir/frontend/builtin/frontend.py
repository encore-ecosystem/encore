from pathlib import Path

from ehir.builder import EHIR_Module
from ehir.core.derectives import Derective_import
from ehir.frontend import EHIR_Frontend
from ehir.frontend.builtin.parser import Parser


class EHIR_DirectFrontend(EHIR_Frontend):
    """
    Module id is relative path to module
    """

    _cache: dict[Path, EHIR_Module]

    def __init__(self):
        self._cache = {}

    def get_module_by_id(self, id: Path) -> EHIR_Module:
        if id in self._cache:
            return self._cache[id]

        parser = Parser()
        module_path = Path(id).resolve()
        try:
            with module_path.open("r") as f:
                ast = parser.parse(f.read())
        except Exception as exc:
            raise RuntimeError(f"Parse error in {module_path}: {exc}") from exc

        mod = EHIR_Module(id, ast)
        self._cache[id] = mod
        return mod

    def get_parent_id_of(self, id: Path, derective: Derective_import) -> Path:
        child_path = Path(id).resolve()
        core_root = Path(__file__).resolve().parents[4] / "core"

        if derective.prefix and derective.prefix[0] == "core":
            rest = derective.prefix[1:]
            candidates: list[Path] = []
            if derective.symbol != "*":
                candidates.append((core_root / Path(*rest, derective.symbol)).with_suffix(self.get_file_extension()))
            candidates.append((core_root / Path(*rest)).with_suffix(self.get_file_extension()))
            if rest:
                candidates.append(core_root / Path(*rest) / f"mod{self.get_file_extension()}")
            candidates.append(core_root / f"mod{self.get_file_extension()}")
            for candidate in candidates:
                if candidate.exists():
                    return candidate.resolve()

        def suffix_variants(prefix_parts: list[str]) -> list[Path]:
            variants: list[Path] = []
            prefix_only = Path(*prefix_parts) if prefix_parts else Path()
            if derective.symbol != "*":
                with_symbol = Path(*prefix_parts, derective.symbol)
                variants.append(with_symbol)
            if not prefix_parts:
                variants.append(Path("lib"))
            variants.append(prefix_only)
            return variants

        def to_module_path(base: Path, suffix: Path) -> Path:
            target = base / suffix
            if target.is_dir():
                return target / f"mod{self.get_file_extension()}"
            return target.with_suffix(self.get_file_extension())

        def add_candidates(candidates: list[Path], base: Path, prefix_parts: list[str]):
            for suffix in suffix_variants(prefix_parts):
                candidates.append(to_module_path(base, suffix))

        # 1) Relative import from current module folder.
        candidates: list[Path] = []
        relative_prefix = derective.prefix[1:] if derective.prefix and derective.prefix[0] == "mod" else derective.prefix
        add_candidates(candidates, child_path.parent, relative_prefix)

        # 2) Refrain-aware lookup for staged layout:
        #    <stage_root>/refrains/<dep>/src/...
        #    <stage_root>/src/... (root refrain)
        parts = child_path.parts
        stage_root: Path | None = None
        current_refrain_src: Path | None = None
        root_refrain_src: Path | None = None

        if "refrains" in parts:
            idx = parts.index("refrains")
            stage_root = Path(*parts[:idx])
            if len(parts) > idx + 1:
                current_refrain_src = stage_root / "refrains" / parts[idx + 1] / "src"
            root_refrain_src = stage_root / "src"
        elif "src" in parts:
            idx = parts.index("src")
            stage_root = Path(*parts[:idx])
            current_refrain_src = stage_root / "src"
            root_refrain_src = stage_root / "src"

        if stage_root is not None and derective.prefix:
            first = derective.prefix[0]
            rest = derective.prefix[1:]

            if first == "mod":
                # `mod::...` stays relative by design, already covered by #1.
                pass
            else:
                if first == "refrain":
                    if current_refrain_src is not None:
                        add_candidates(candidates, current_refrain_src, rest)
                elif first == "repo":
                    if root_refrain_src is not None:
                        add_candidates(candidates, root_refrain_src, rest)
                else:
                    add_candidates(candidates, stage_root / "refrains" / first / "src", rest)
                    if root_refrain_src is not None:
                        add_candidates(candidates, root_refrain_src / first, rest)

        for candidate in candidates:
            if candidate.exists():
                return candidate

        candidates_repr = ", ".join(str(x) for x in candidates)
        raise RuntimeError(
            f"Unable to import: {id} :: prefix={derective.prefix}, symbol={derective.symbol}, "
            f"candidates=[{candidates_repr}]"
        )

    def get_file_extension(self) -> str:
        return ".ehir"

    def list_child_module_ids(self, id: Path) -> list[Path]:
        module_id = Path(id).resolve()

        if module_id.stem == "mod":
            base_dir = module_id.parent
            candidates = list(base_dir.glob("*.ehir")) + list(base_dir.glob("*/mod.ehir"))
        else:
            base_dir = module_id.parent / module_id.stem
            if not base_dir.exists():
                return []
            candidates = list(base_dir.glob("*.ehir")) + list(base_dir.glob("*/mod.ehir"))

        result: list[Path] = []
        seen: set[Path] = set()
        for candidate in sorted(candidates):
            candidate = candidate.resolve()
            if candidate == module_id or candidate in seen:
                continue
            seen.add(candidate)
            result.append(candidate)
        return result
