from dataclasses import dataclass
from pathlib import Path

from ehir.postprocessor import ProcessedModule

from ehir_llvm_backend.archiver import Archiver
from ehir_llvm_backend.assembler import Assembler
from ehir_llvm_backend.codegen import Codegen
from ehir_llvm_backend.linker import Linker
from ehir_llvm_backend.optimizer import OptimizationProfile, Optimizer


@dataclass
class EHIR_LLVM_Backend:
    def __post_init__(self):
        self._codegen = Codegen()
        self._optimizer = Optimizer()
        self._archiver = Archiver()
        self._assembler = Assembler()
        self._linker = Linker()

    def compile(self, module: ProcessedModule) -> Path:
        llvm_mod = Codegen().run(module)
        llvm_optimized_mod = Optimizer().run(llvm_mod, opt_profile=OptimizationProfile.debug)

        print(llvm_optimized_mod)
