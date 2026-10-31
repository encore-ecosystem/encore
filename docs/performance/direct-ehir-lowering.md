# Direct EHIR construction

Encore constructs EHIR declarations, instructions, blocks and terminators as
typed values. Fresh package lowering and standalone test compilation pass this
graph to the backend without serializing it and parsing it again. Nominal type
collisions are resolved by a structural traversal.

The persistent cache formats remain unchanged. Restored module and function
records are decoded from their existing textual representation. Text export,
the EHIR CLI and explicit source-language `ehir` blocks remain supported.
Source type spellings are still converted with `parse_type_text`, interned in
the lowering scope; this change removes the full instruction/module round trip.

Construction buffers own graph-managed storage, snapshot appended fragments
and cannot be implicitly frozen or transferred to another thread. Type probes
fork their SSA context so temporary match and if expressions do not contaminate
the emitted graph.

Validation uses the established 0.1.12 bootstrap compiler: direct lowering and
text-cache round-trip regressions, the unsupported enum-payload regression,
function-cache replay with nested closures, and the nine EHIR-core tests.
The direct-lowering regression checks that no full bundle parser is invoked.

The unfinished binary snapshot/cache-format changes are excluded. A complete
self-host bootstrap has not been rerun for this isolated stage. No end-to-end
speedup is claimed; assembly and serialization timings are reported separately
from the removed fresh-bundle parse phase.
