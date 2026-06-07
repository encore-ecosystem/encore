from pathlib import Path

import llvmlite.binding as llvm


class Assembler:
    def run(self, ir_module: llvm.ModuleRef, object_path: Path) -> Path:
        llvm.initialize_native_target()
        llvm.initialize_native_asmprinter()

        target = llvm.Target.from_default_triple()
        target_machine = target.create_target_machine(
            opt=2,
            reloc="pic",
        )

        with open(object_path, "wb") as f:
            f.write(target_machine.emit_object(ir_module))

        return object_path
