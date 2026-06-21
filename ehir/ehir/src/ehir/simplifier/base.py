from abc import ABC, abstractmethod

from ehir.resolver import EHIR_TypedModule


class SimplifierPass(ABC):
    @abstractmethod
    def run(self, module: EHIR_TypedModule) -> EHIR_TypedModule:
        raise NotImplementedError
