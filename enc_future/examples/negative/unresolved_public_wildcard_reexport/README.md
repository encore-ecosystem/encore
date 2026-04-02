# unresolved_public_wildcard_reexport

Negative case: module uses `pub import util::*` but `util` cannot be resolved; importer must fail on missing exported symbol.
