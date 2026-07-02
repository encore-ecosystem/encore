# from .add import add_add_parser
from .build import add_build_parser
from .init import add_init_parser
from .install import add_install_parser
from .lsp import add_lsp_parser

from .memcheck import add_memcheck_parser
from .run import add_run_parser
from .test import add_test_parser

# from .sync import add_sync_parser
# from .update import add_update_parser

__all__ = [
    "add_add_parser",
    "add_build_parser",
    "add_init_parser",
    "add_install_parser",
    "add_lsp_parser",
    "add_memcheck_parser",
    "add_run_parser",
    "add_sync_parser",
    "add_test_parser",
    "add_update_parser",
]
