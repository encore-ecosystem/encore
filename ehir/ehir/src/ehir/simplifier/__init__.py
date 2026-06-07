from .autoretain import AutoRetainPass
from .deallocator import Deallocator
from .drop_lowering import DropLoweringPass
from .downgrader import Downgrader
from .instance_call_lowering import InstanceCallLoweringPass
from .match_validator import MatchValidatorPass
from .monomorphize import MonomorphizationPass
from .normalizer import Normalizer
from .reference_lowering import ReferenceLoweringPass
from .retainer import RetainInsertionPass
from .resolver import Resolver
from .autodrop import AutoDropPass

__all__ = [
    "AutoDropPass",
    "AutoRetainPass",
    "Deallocator",
    "Downgrader",
    "DropLoweringPass",
    "InstanceCallLoweringPass",
    "MatchValidatorPass",
    "Normalizer",
    "MonomorphizationPass",
    "ReferenceLoweringPass",
    "Resolver",
    "RetainInsertionPass",
]
