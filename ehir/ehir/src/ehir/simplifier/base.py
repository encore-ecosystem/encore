from abc import ABC, abstractmethod

from ehir.builder import EHIR_Module


class SimplifierPass(ABC):
    @abstractmethod
    def run(self, module: EHIR_Module) -> EHIR_Module:
        raise NotImplementedError
