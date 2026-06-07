from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from ehir.builder import EHIR_Module
from ehir.core.derectives import Derective_import


@dataclass
class EHIR_Frontend(ABC):
    @abstractmethod
    def get_module_by_id(self, id: Path) -> EHIR_Module:
        raise NotImplementedError

    @abstractmethod
    def get_parent_id_of(self, id: Path, derective: Derective_import) -> Path:
        raise NotImplementedError

    @abstractmethod
    def get_file_extension(self) -> str:
        raise NotImplementedError

    def list_child_module_ids(self, id: Path) -> list[Path]:
        return []
