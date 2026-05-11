from dataclasses import dataclass
from pathlib import Path

from ehir.backend import EHIR_Backend
from ehir.refrain import CompiledRefrain, Refrain

from ehir_llvm_backend.archiver import Archiver
from ehir_llvm_backend.assembler import Assembler
from ehir_llvm_backend.codegen import Codegen
from ehir_llvm_backend.linker import Linker
from ehir_llvm_backend.optimizer import Optimizer


@dataclass
class EHIR_LLVM_Backend(EHIR_Backend):
    def __post_init__(self):
        self._codegen = Codegen()
        self._optimizer = Optimizer()
        self._archiver = Archiver()
        self._assembler = Assembler()
        self._linker = Linker()

        self._profile_path = self.target_dir / self.opt_profile
        self._llvm_ir_path = self._profile_path / "llvm"
        self._object_path = self._profile_path / "object"

        self._llvm_ir_path.mkdir(exist_ok=True, parents=True)
        self._object_path.mkdir(exist_ok=True, parents=True)

    def compile_refrain(self, refrain: CompiledRefrain) -> Path:
        output_stem = self._build_output_stem(refrain)

        llvm_ir_raw_module = self._codegen.run(refrain.module)
        llvm_ir_opt_module = self._optimizer.run(llvm_ir_raw_module, self.opt_profile)

        with (self._llvm_ir_path / f"{output_stem}.ir").open("w") as f:
            f.write(str(llvm_ir_opt_module))

        object_path = self._assembler.run(llvm_ir_opt_module, self._object_path / f"{output_stem}.o")

        if refrain.type == Refrain.TargetType.OBJECT:
            return object_path

        if refrain.type == Refrain.TargetType.STATIC_LIB:
            return self._archiver.run(object_path, self._profile_path / f"{output_stem}.a")

        if refrain.type == Refrain.TargetType.EXECUTABLE:
            return self._linker.run(object_path, self._profile_path / output_stem)

        raise ValueError(f"Unsupported refrain target type: {refrain.type}")

    @staticmethod
    def _build_output_stem(refrain: CompiledRefrain) -> str:
        if refrain.type == Refrain.TargetType.STATIC_LIB:
            return f"lib{refrain.name}"
        return refrain.name
