from enum import StrEnum, auto

import llvmlite.binding as llvm
from llvmlite import ir


class OptimizationProfile(StrEnum):
    debug = auto()
    release = auto()
    extreme = auto()


class Optimizer:
    def __init__(self):
        llvm.initialize_native_target()
        llvm.initialize_native_asmprinter()

    def run(self, module: ir.Module, opt_profile: OptimizationProfile) -> llvm.ModuleRef:
        target = llvm.Target.from_default_triple()
        target_machine = target.create_target_machine()

        module_llvm = llvm.parse_assembly(str(module))

        # Keep debug builds as transparent as possible: no LLVM optimization
        # pipeline, only structural verification.
        if opt_profile == OptimizationProfile.debug:
            module_llvm.verify()
            return module_llvm

        speed_level = 0
        size_level = 0
        if opt_profile == OptimizationProfile.release:
            speed_level = 1
        elif opt_profile == OptimizationProfile.extreme:
            speed_level = 2
            size_level = 2

        pto = llvm.create_pipeline_tuning_options(speed_level=speed_level, size_level=size_level)
        pto.loop_vectorization = True
        pto.slp_vectorization = True
        pto.loop_unrolling = True
        pass_builder = llvm.create_pass_builder(target_machine, pto)
        mpm = pass_builder.getModulePassManager()
        mpm.run(module_llvm, pass_builder)

        # Function
        fpm = pass_builder.getFunctionPassManager()
        for function in module_llvm.functions:
            fpm.run(function, pass_builder)

        module_llvm.verify()
        return module_llvm
