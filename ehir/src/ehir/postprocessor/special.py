from dataclasses import dataclass

from ehir.core.block import TerminatedBlock

from .instructions import ProcessedControlFlow, ProcessedInstruction


@dataclass
class ProcessedBlock(TerminatedBlock):
    term: ProcessedControlFlow
    body: list[ProcessedInstruction]
