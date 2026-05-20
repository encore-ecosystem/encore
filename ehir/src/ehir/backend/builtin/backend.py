from pathlib import Path

from ehir.backend import EHIR_Backend
from ehir.refrain import CompiledRefrain, Refrain


class EHIR_DirectBackend(EHIR_Backend):
    def compile_refrain(
        self,
        refrain: CompiledRefrain,
    ) -> Path:
        target = self._build_target_path(refrain)
        with target.open("w") as f:
            f.write(refrain.module.__str__())
        return target

    def _build_target_path(self, refrain: CompiledRefrain) -> Path:
        if refrain.type == Refrain.TargetType.EXECUTABLE:
            return self.profile_path / refrain.name

        if refrain.type == Refrain.TargetType.STATIC_LIB:
            return self.profile_path / f"lib{refrain.name}.a"

        if refrain.type == Refrain.TargetType.OBJECT:
            return self.profile_path / f"{refrain.name}.o"

        raise ValueError(f"Unsupported refrain target type: {refrain.type}")
