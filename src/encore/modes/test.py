from __future__ import annotations

import subprocess
import sys
import time
from argparse import Namespace, SUPPRESS
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from rich.console import Console

from ehir import EHIR_ProjectCompiler
from ehir.compiler import CompileProfileRecord
from ehir_llvm_backend import EHIR_LLVM_Backend
from encore.compiler import EncoreCompiler
from encore.compiler.compiler import ImportedTopLevelDeclaration
from encore.compiler.inference import TypeInferer
from encore.compiler.parser import statements as s
from encore.compiler.translator import EncoreToEHIRTranslator
from encore.modes.build import (
    add_build_options,
    print_profile_report,
    profile_timings_enabled,
    resolve_build_profile,
)
from encore.utils.diagnostics import CompileDiagnostic, render_diagnostic


@dataclass(frozen=True)
class UnitTestCase:
    refrain_name: str
    refrain_path: Path
    module_id: Path
    function_name: str

    @property
    def source_file(self) -> Path:
        return self.module_id

    @property
    def module_display_name(self) -> str:
        try:
            return self.module_id.relative_to(self.refrain_path).as_posix()
        except ValueError:
            return self.module_id.name

    @property
    def display_name(self) -> str:
        return f"{self.refrain_name}:{self.module_display_name}::{self.function_name}"

    @property
    def synthetic_module_id(self) -> Path:
        safe = _sanitize_path_fragment(self.display_name)
        return self.refrain_path / "target" / "tests" / safe / "src" / "main.enq"


@dataclass(frozen=True)
class StandaloneTestCase:
    refrain_name: str
    refrain_path: Path
    module_id: Path
    expected_compile_error: str | None = None

    @property
    def source_file(self) -> Path:
        return self.module_id

    @property
    def module_display_name(self) -> str:
        try:
            return self.module_id.relative_to(self.refrain_path).as_posix()
        except ValueError:
            return self.module_id.name

    @property
    def display_name(self) -> str:
        return f"{self.refrain_name}:{self.module_display_name}"


TestCase = UnitTestCase | StandaloneTestCase


def add_test_parser(subparsers) -> tuple[str, Callable]:
    section = "test"
    test_parser = subparsers.add_parser(section, help="Run unit tests marked with #attr(test)")
    add_build_options(test_parser)
    test_parser.add_argument(
        "--filter",
        type=str,
        default=None,
        help="Only run tests whose display name contains this text",
    )
    test_parser.add_argument("-j", "--jobs", type=int, default=1, help="Number of test worker processes to run")
    test_parser.add_argument("--test-timeout", type=float, default=30.0, help="Seconds to wait for each test binary")
    test_parser.add_argument("--_worker-refrain", dest="_worker_refrain", type=str, default=None, help=SUPPRESS)
    test_parser.add_argument("--_worker-module", dest="_worker_module", type=str, default=None, help=SUPPRESS)
    test_parser.add_argument("--_worker-function", dest="_worker_function", type=str, default=None, help=SUPPRESS)
    test_parser.add_argument("--_worker-kind", dest="_worker_kind", type=str, default=None, help=SUPPRESS)
    return (section, handle_test)


def handle_test(args: Namespace):
    cwd = Path().resolve()
    console = Console(highlight=False)
    args.resolved_profile = resolve_build_profile(args)
    args.profile_timings = profile_timings_enabled(args)

    if args._worker_refrain is not None:
        _handle_test_worker(args, cwd)
        return

    compiler = EncoreCompiler()
    _add_test_target(compiler, cwd)
    refrains = list(compiler.refrain_manager.get_building_queue())
    refrains_by_name = {refrain.name: refrain for refrain in refrains}

    for refrain in refrains:
        compiler._infer_refrain_modules(refrain)

    native_inputs_by_refrain = {
        refrain.name: compiler._native_link_inputs_for_refrain(refrain) for refrain in refrains
    }
    tests = _collect_tests(refrains, args.filter)
    if not tests:
        console.print("No tests found.")
        return

    console.print(f"running {len(tests)} tests")
    start = time.perf_counter()

    if args.jobs > 1 and not args.profile_timings:
        passed, failed = _run_tests_in_parallel(args, cwd, tests, console)
    else:
        passed, failed = _run_tests_sequential(
            args,
            compiler,
            refrains_by_name,
            native_inputs_by_refrain,
            tests,
            console,
        )

    elapsed = time.perf_counter() - start
    if args.profile_timings:
        print_profile_report(compiler)

    if failed == 0:
        console.print(f"test result: [green]ok[/green]. {passed} passed; 0 failed; finished in {elapsed:.2f}s")
        return

    console.print(f"test result: [red]FAILED[/red]. {passed} passed; {failed} failed; finished in {elapsed:.2f}s")
    raise SystemExit(1)


def _handle_test_worker(args: Namespace, cwd: Path) -> None:
    compiler = EncoreCompiler()
    _add_test_target(compiler, cwd)
    refrains = list(compiler.refrain_manager.get_building_queue())
    refrains_by_name = {refrain.name: refrain for refrain in refrains}

    for refrain in refrains:
        compiler._infer_refrain_modules(refrain)

    native_inputs_by_refrain = {
        refrain.name: compiler._native_link_inputs_for_refrain(refrain) for refrain in refrains
    }
    tests = _collect_tests(refrains, None)
    for test in tests:
        if args._worker_kind and _test_kind(test) != args._worker_kind:
            continue
        if (
            test.refrain_name == args._worker_refrain
            and str(test.module_id.resolve()) == str(Path(args._worker_module).resolve())
            and (not isinstance(test, UnitTestCase) or test.function_name == args._worker_function)
        ):
            passed = _run_single_test_case(
                args,
                compiler,
                refrains_by_name[test.refrain_name],
                native_inputs_by_refrain,
                test,
                console=Console(highlight=False),
                print_summary=True,
            )
            raise SystemExit(0 if passed else 1)

    raise RuntimeError(
        f"Unknown test: refrain={args._worker_refrain}, module={args._worker_module}, function={args._worker_function}"
    )


def _run_tests_in_parallel(
    args: Namespace, cwd: Path, tests: list[TestCase], console: Console
) -> tuple[int, int]:
    passed = 0
    failed = 0
    with ThreadPoolExecutor(max_workers=_normalize_jobs(args.jobs)) as executor:
        futures = {executor.submit(_run_test_worker, args, cwd, test): test for test in tests}
        for future in as_completed(futures):
            test = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                failed += 1
                console.print(f"test {test.display_name} ... [red]FAILED[/red]")
                console.print(_exception_text(exc))
                continue

            worker_output = "\n".join(part.rstrip() for part in (result.stdout, result.stderr) if part.strip()).strip()
            if worker_output:
                console.print(worker_output)
            if result.returncode == 0:
                passed += 1
            else:
                failed += 1

    if failed == 0:
        return passed, failed
    return passed, failed


def _run_tests_sequential(
    args: Namespace,
    compiler: EncoreCompiler,
    refrains_by_name: dict[str, object],
    native_inputs_by_refrain: dict[str, object],
    tests: list[TestCase],
    console: Console,
) -> tuple[int, int]:
    passed = 0
    failed = 0
    for test in tests:
        refrain = refrains_by_name[test.refrain_name]
        result = _run_single_test_case(
            args,
            compiler,
            refrain,
            native_inputs_by_refrain,
            test,
            console=console,
            print_summary=True,
        )
        if result:
            passed += 1
        else:
            failed += 1

    return passed, failed


def _run_test_worker(args: Namespace, cwd: Path, test: TestCase) -> subprocess.CompletedProcess[str]:
    cmd = [
        sys.executable,
        "-c",
        "from encore.cli import main; main()",
        "test",
        "--backend",
        args.backend,
        "--opt-profile",
        args.resolved_profile.value,
        "--_worker-refrain",
        test.refrain_name,
        "--_worker-module",
        str(test.module_id),
        "--_worker-kind",
        _test_kind(test),
    ]
    if isinstance(test, UnitTestCase):
        cmd.extend(["--_worker-function", test.function_name])
    if args.profile_timings:
        cmd.extend(["--profile", "timings"])
    if args.no_cache:
        cmd.append("--no-cache")
    for cfg in args.cfg:
        cmd.extend(["--cfg", cfg])
    cmd.extend(["--test-timeout", str(args.test_timeout)])

    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)


def _run_single_test_case(
    args: Namespace,
    compiler: EncoreCompiler,
    refrain,
    native_inputs_by_refrain: dict[str, object],
    test: TestCase,
    *,
    console: Console,
    print_summary: bool,
) -> bool:
    start = time.perf_counter()
    try:
        if isinstance(test, UnitTestCase):
            binary_path, profile_records = _compile_unit_test_binary(
                args, compiler, refrain, native_inputs_by_refrain, test
            )
        else:
            binary_path, profile_records = _compile_standalone_test_binary(
                args, compiler, refrain, native_inputs_by_refrain, test
            )
        if isinstance(test, StandaloneTestCase) and test.expected_compile_error is not None:
            duration = time.perf_counter() - start
            console.print(f"test {test.display_name} ... [red]FAILED[/red] ({duration:.2f}s)")
            console.print(f"expected compile error containing: {test.expected_compile_error}")
            return False

        result = _run_binary(binary_path, [], timeout=args.test_timeout)
        duration = time.perf_counter() - start
        if result.returncode == 0:
            if print_summary:
                console.print(f"test {test.display_name} ... [green]ok[/green] ({duration:.2f}s)")
            else:
                console.print(f"test {test.display_name} ... [green]ok[/green]")
            if args.profile_timings:
                _append_profile_records(compiler, test.display_name, profile_records)
            return True

        if print_summary:
            console.print(f"test {test.display_name} ... [red]FAILED[/red] ({duration:.2f}s)")
        else:
            console.print(f"test {test.display_name} ... [red]FAILED[/red]")
        output = _format_worker_error(result)
        if output:
            console.print(output)
        if args.profile_timings:
            _append_profile_records(compiler, test.display_name, profile_records)
        return False
    except Exception as exc:
        duration = time.perf_counter() - start
        if isinstance(test, StandaloneTestCase) and test.expected_compile_error is not None:
            failure_text = _render_failure(exc)
            if test.expected_compile_error in failure_text or test.expected_compile_error in _exception_text(exc):
                if print_summary:
                    console.print(f"test {test.display_name} ... [green]ok[/green] ({duration:.2f}s)")
                else:
                    console.print(f"test {test.display_name} ... [green]ok[/green]")
                return True
        if print_summary:
            console.print(f"test {test.display_name} ... [red]FAILED[/red] ({duration:.2f}s)")
        else:
            console.print(f"test {test.display_name} ... [red]FAILED[/red]")
        console.print(_render_failure(exc))
        return False


def _compile_unit_test_binary(
    args: Namespace,
    compiler: EncoreCompiler,
    refrain,
    native_inputs_by_refrain: dict[str, object],
    test: UnitTestCase,
) -> tuple[Path, list]:
    module_id = test.synthetic_module_id
    imported_declarations = _test_imported_declarations(compiler, refrain, test.module_id)

    module_ast = _build_test_module_ast(compiler, refrain, test)
    TypeInferer().infer(module_ast, imported_declarations=imported_declarations)
    _validate_test_function(module_ast, test)

    ehr = EncoreToEHIRTranslator().translate_ast(
        module_ast,
        module_id=module_id,
        imported_declarations=imported_declarations,
    )
    ehir_compiler = EHIR_ProjectCompiler()
    typed = ehir_compiler.resolve_module(ehr)
    processed = ehir_compiler.compile_module(typed)

    link_inputs = compiler._native_link_inputs_for_closure(refrain, native_inputs_by_refrain)
    backend = EHIR_LLVM_Backend()
    binary_path = backend.compile(
        processed,
        opt_profile=args.resolved_profile,
        native_objects=list(link_inputs.objects),
        native_link_args=list(link_inputs.link_args),
    )
    return binary_path, ehir_compiler.pass_timings


def _compile_standalone_test_binary(
    args: Namespace,
    compiler: EncoreCompiler,
    refrain,
    native_inputs_by_refrain: dict[str, object],
    test: StandaloneTestCase,
) -> tuple[Path, list]:
    graph = compiler.refrain_manager.build_import_graph_from_entrypoint(refrain, test.module_id)
    compiler.refrain_manager._resolve_imports(refrain, graph)
    module_ast = compiler.refrain_manager._flatten_import_graph_ast(graph)
    imported_declarations = _graph_alias_declarations(refrain, graph)
    TypeInferer().infer(module_ast, imported_declarations=imported_declarations)
    _validate_standalone_main(module_ast, test)

    ehr = EncoreToEHIRTranslator().translate_ast(
        module_ast,
        module_id=test.module_id,
        imported_declarations=imported_declarations,
    )
    ehir_compiler = EHIR_ProjectCompiler()
    typed = ehir_compiler.resolve_module(ehr)
    processed = ehir_compiler.compile_module(typed)

    link_inputs = compiler._native_link_inputs_for_closure(refrain, native_inputs_by_refrain)
    backend = EHIR_LLVM_Backend()
    binary_path = backend.compile(
        processed,
        opt_profile=args.resolved_profile,
        native_objects=list(link_inputs.objects),
        native_link_args=list(link_inputs.link_args),
    )
    return binary_path, ehir_compiler.pass_timings


def _graph_alias_declarations(refrain, graph) -> list[ImportedTopLevelDeclaration]:
    aliases: list[ImportedTopLevelDeclaration] = []
    seen: set[tuple[Path, Path, str, str, int]] = set()
    for alias_module_id in graph.modules:
        for binding in refrain.symbols.modules.get(alias_module_id.resolve(), {}).values():
            if binding.name == binding.source_name and binding.module_id.resolve() == alias_module_id.resolve():
                continue
            key = (
                alias_module_id.resolve(),
                binding.module_id.resolve(),
                binding.name,
                binding.source_name,
                id(binding.statement),
            )
            if key in seen:
                continue
            seen.add(key)
            aliases.append(
                ImportedTopLevelDeclaration(
                    module_id=binding.module_id,
                    statement=binding.statement,
                    local_name=binding.name,
                    source_name=binding.source_name,
                    alias_module_id=alias_module_id,
                )
            )
    return aliases


def _build_test_module_ast(compiler: EncoreCompiler, refrain, test: UnitTestCase) -> list[s.Statement]:
    module_ast = deepcopy(compiler.refrain_manager._parse_file(test.module_id))
    filtered_ast: list[s.Statement] = []
    for statement in module_ast:
        if isinstance(statement, s.Statement_FunctionDefinition) and statement.name == "main":
            continue
        filtered_ast.append(statement)
    filtered_ast.append(_build_test_harness(test.function_name))
    return filtered_ast


def _test_imported_declarations(compiler: EncoreCompiler, refrain, module_id: Path) -> list[ImportedTopLevelDeclaration]:
    local_statements = refrain.symbols.local_ast_without_imports.get(module_id, [])
    local_keys = {
        (module_id.resolve(), type(statement).__name__, _top_level_name(statement))
        for statement in local_statements
        if isinstance(statement, s.Statement_TopLevel)
    }
    imported: list[ImportedTopLevelDeclaration] = []
    seen: set[tuple[Path, str, str | None]] = set()
    for statement in refrain.ast:
        if not isinstance(statement, s.Statement_TopLevel):
            continue
        if isinstance(statement, s.Statement_FunctionDefinition) and statement.signature.name == "main":
            continue
        source_module_id = getattr(statement, "module_id", module_id)
        if not isinstance(source_module_id, Path):
            source_module_id = module_id
        source_module_id = source_module_id.resolve()
        key = (source_module_id, type(statement).__name__, _top_level_name(statement))
        if key in local_keys or key in seen:
            continue
        seen.add(key)
        imported.append(
            ImportedTopLevelDeclaration(
                module_id=source_module_id,
                statement=statement,
            )
        )
    return imported


def _top_level_name(statement: s.Statement_TopLevel) -> str | None:
    if isinstance(statement, s.Statement_FunctionDefinition):
        return statement.signature.name
    if isinstance(statement, s.FunctionSignature):
        return statement.name
    if isinstance(statement, s.Statement_StructureDefinition):
        return statement.signature.name
    if isinstance(statement, s.Statement_EnumDefinition):
        return statement.name
    if isinstance(statement, s.Statement_Trait):
        return statement.name
    if isinstance(statement, s.Statement_Global):
        return statement.name
    if isinstance(statement, s.Statement_Impl):
        trait_name = statement.trait_name or ""
        methods = ",".join(method.signature.name for method in statement.body)
        return f"impl::{trait_name}::{statement.struct}::{methods}"
    return None


def _build_test_harness(test_function_name: str) -> s.Statement_FunctionDefinition:
    test_call = s.Expression_Call(
        callee=s.Expression_Path([s.Type(test_function_name)]),
        generics=[],
        args=[],
    )
    body = s.Block(
        [
            s.Statement_If(
                branches=[
                    s.Statement_IfBranch(
                        expr=s.Expression_UnaryOperation(operator="!", expr=test_call),
                        body=s.Block([s.Statement_Ret(s.Expression_IntegerLiteral("1", s.Type("u32")))]),
                    )
                ]
            ),
            s.Statement_Ret(s.Expression_IntegerLiteral("0", s.Type("u32"))),
        ]
    )
    return s.Statement_FunctionDefinition(
        is_public=False,
        signature=s.FunctionSignature(
            is_public=False,
            attrs=[],
            is_extern=False,
            name="main",
            generics=[],
            params=[],
            type=s.Type("u32"),
        ),
        body=body,
    )


def _validate_test_function(module_ast: list[s.Statement], test: UnitTestCase) -> None:
    if test.function_name == "main":
        raise RuntimeError(f"Test function '{test.display_name}' can not be named 'main'")
    test_fn = _find_function(module_ast, test.function_name)
    if test_fn is None:
        raise RuntimeError(f"Unable to locate test function '{test.function_name}' in {test.display_name}")
    if test_fn.signature.is_extern:
        raise RuntimeError(f"Test function '{test.display_name}' can not be extern")
    if test_fn.params:
        raise RuntimeError(f"Test function '{test.display_name}' must not accept parameters")
    if test_fn.generics:
        raise RuntimeError(f"Test function '{test.display_name}' must not be generic")
    if test_fn.type is None or not _is_bool_like_type(test_fn.type):
        raise RuntimeError(
            f"Test function '{test.display_name}' must return bool, got {test_fn.type if test_fn.type is not None else 'void'}"
        )


def _validate_standalone_main(module_ast: list[s.Statement], test: StandaloneTestCase) -> None:
    main_fn = _find_function(module_ast, "main")
    if main_fn is None:
        raise RuntimeError(f"Standalone test '{test.display_name}' must define main")
    if main_fn.signature.is_extern:
        raise RuntimeError(f"Standalone test '{test.display_name}' main can not be extern")
    if main_fn.params:
        raise RuntimeError(f"Standalone test '{test.display_name}' main must not accept parameters")
    if main_fn.generics:
        raise RuntimeError(f"Standalone test '{test.display_name}' main must not be generic")
    if main_fn.type is None or getattr(main_fn.type, "name", None) != "u32":
        raise RuntimeError(
            f"Standalone test '{test.display_name}' main must return u32, "
            f"got {main_fn.type if main_fn.type is not None else 'void'}"
        )


def _find_function(module_ast: list[s.Statement], function_name: str) -> s.Statement_FunctionDefinition | None:
    for statement in module_ast:
        if isinstance(statement, s.Statement_FunctionDefinition) and statement.name == function_name:
            return statement
    return None


def _collect_tests(refrains: Iterable, filter_text: str | None) -> list[TestCase]:
    tests: list[TestCase] = []
    tests.extend(_collect_unit_tests(refrains, filter_text))
    tests.extend(_collect_standalone_tests(refrains, filter_text))
    tests.sort(key=lambda test: test.display_name)
    return tests


def _collect_unit_tests(refrains: Iterable, filter_text: str | None) -> list[UnitTestCase]:
    tests: list[UnitTestCase] = []
    for refrain in refrains:
        for module_id, statements in sorted(refrain.symbols.local_ast_without_imports.items(), key=lambda item: str(item[0])):
            for statement in statements:
                if not isinstance(statement, s.Statement_FunctionDefinition):
                    continue
                if "test" not in statement.signature.attrs:
                    continue
                case = UnitTestCase(
                    refrain_name=refrain.name,
                    refrain_path=refrain.path,
                    module_id=module_id,
                    function_name=statement.name,
                )
                if filter_text and filter_text not in case.display_name:
                    continue
                tests.append(case)
    return tests


def _collect_standalone_tests(refrains: Iterable, filter_text: str | None) -> list[StandaloneTestCase]:
    tests: list[StandaloneTestCase] = []
    for refrain in refrains:
        tests_dir = refrain.path / "tests"
        if not tests_dir.exists():
            continue
        for module_id in sorted(tests_dir.glob("*.enq")):
            case = StandaloneTestCase(
                refrain_name=refrain.name,
                refrain_path=refrain.path,
                module_id=module_id.resolve(),
                expected_compile_error=_expected_compile_error(module_id),
            )
            if filter_text and filter_text not in case.display_name:
                continue
            tests.append(case)
    return tests


def _test_kind(test: TestCase) -> str:
    if isinstance(test, UnitTestCase):
        return "unit"
    return "standalone"


def _expected_compile_error(module_id: Path) -> str | None:
    try:
        for line in module_id.read_text().splitlines()[:8]:
            stripped = line.strip()
            for prefix in ("//@expect.compile_error=", "// @expect.compile_error="):
                if stripped.startswith(prefix):
                    return stripped.removeprefix(prefix).strip()
            if stripped and not stripped.startswith("//"):
                return None
    except OSError:
        return None
    return None


def _append_profile_records(compiler: EncoreCompiler, test_name: str, records: list) -> None:
    compiler.profile_records.extend(
        CompileProfileRecord(module=test_name, stage=record.stage, seconds=record.seconds) for record in records
    )


def _normalize_jobs(jobs: int) -> int:
    if jobs < 1:
        raise RuntimeError("--jobs must be greater than zero")
    return jobs


def _run_binary(executable_path: Path, program_args: list[str], *, timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(executable_path), *program_args], capture_output=True, text=True, check=False, timeout=timeout)


def _sanitize_path_fragment(value: str) -> str:
    parts: list[str] = []
    for ch in value:
        if ch.isalnum():
            parts.append(ch)
        else:
            parts.append("_")
    return "".join(parts)


def _is_bool_like_type(typ) -> bool:
    return getattr(typ, "name", None) in {"bool", "u1"}


def _format_worker_error(result: subprocess.CompletedProcess[str]) -> str:
    output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
    if output:
        return output
    if result.returncode < 0:
        return f"worker terminated by signal {-result.returncode}"
    return f"worker exited with code {result.returncode}"


def _render_failure(exc: Exception) -> str:
    if isinstance(exc, CompileDiagnostic):
        return render_diagnostic(exc)
    return _exception_text(exc)


def _add_test_target(compiler: EncoreCompiler, cwd: Path) -> None:
    src_dir = cwd / "src"
    main_entry = src_dir / "main.enq"
    lib_entry = src_dir / "lib.enq"
    if main_entry.exists():
        compiler.refrain_manager.add_binary_target(cwd)
        return
    if lib_entry.exists():
        compiler.refrain_manager.add_refrain_with_dependencies(cwd, False)
        return
    raise RuntimeError(f"Unable to find test entrypoint: expected {main_entry} or {lib_entry}")


def _exception_text(exc: Exception) -> str:
    parts: list[str] = []
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        text = str(current).strip()
        parts.append(text if text else current.__class__.__name__)
        current = current.__cause__ or current.__context__
    return " | caused by: ".join(parts)
