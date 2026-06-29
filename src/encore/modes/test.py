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
    test_parser.add_argument("--_worker-refrain", dest="_worker_refrain", type=str, default=None, help=SUPPRESS)
    test_parser.add_argument("--_worker-module", dest="_worker_module", type=str, default=None, help=SUPPRESS)
    test_parser.add_argument("--_worker-function", dest="_worker_function", type=str, default=None, help=SUPPRESS)
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
    tests = _collect_unit_tests(refrains, args.filter)
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
    tests = _collect_unit_tests(refrains, None)
    for test in tests:
        if (
            test.refrain_name == args._worker_refrain
            and str(test.module_id.resolve()) == str(Path(args._worker_module).resolve())
            and test.function_name == args._worker_function
        ):
            passed = _run_single_test(
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
    args: Namespace, cwd: Path, tests: list[UnitTestCase], console: Console
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
    tests: list[UnitTestCase],
    console: Console,
) -> tuple[int, int]:
    passed = 0
    failed = 0
    for test in tests:
        refrain = refrains_by_name[test.refrain_name]
        result = _run_single_test(
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


def _run_test_worker(args: Namespace, cwd: Path, test: UnitTestCase) -> subprocess.CompletedProcess[str]:
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
        "--_worker-function",
        test.function_name,
    ]
    if args.profile_timings:
        cmd.extend(["--profile", "timings"])
    if args.no_cache:
        cmd.append("--no-cache")
    for cfg in args.cfg:
        cmd.extend(["--cfg", cfg])

    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)


def _run_single_test(
    args: Namespace,
    compiler: EncoreCompiler,
    refrain,
    native_inputs_by_refrain: dict[str, object],
    test: UnitTestCase,
    *,
    console: Console,
    print_summary: bool,
) -> bool:
    start = time.perf_counter()
    try:
        binary_path, profile_records = _compile_test_binary(args, compiler, refrain, native_inputs_by_refrain, test)
        result = _run_binary(binary_path, [])
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
        if print_summary:
            console.print(f"test {test.display_name} ... [red]FAILED[/red] ({duration:.2f}s)")
        else:
            console.print(f"test {test.display_name} ... [red]FAILED[/red]")
        console.print(_render_failure(exc))
        return False


def _compile_test_binary(
    args: Namespace,
    compiler: EncoreCompiler,
    refrain,
    native_inputs_by_refrain: dict[str, object],
    test: UnitTestCase,
) -> tuple[Path, list]:
    module_id = test.synthetic_module_id
    imported_declarations = compiler._imported_declarations_for_module(refrain, test.module_id)
    alias_declarations = compiler._flattened_alias_declarations(refrain)

    module_ast = _build_test_module_ast(refrain, test)
    TypeInferer().infer(module_ast, imported_declarations=imported_declarations)
    _validate_test_function(module_ast, test)

    ehr = EncoreToEHIRTranslator().translate_ast(
        module_ast,
        module_id=module_id,
        imported_declarations=alias_declarations,
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


def _build_test_module_ast(refrain, test: UnitTestCase) -> list[s.Statement]:
    local_ast = deepcopy(refrain.symbols.local_ast_without_imports.get(test.module_id, []))
    filtered_ast: list[s.Statement] = []
    for statement in local_ast:
        if isinstance(statement, s.Statement_FunctionDefinition) and statement.name == "main":
            continue
        filtered_ast.append(statement)
    filtered_ast.append(_build_test_harness(test.function_name))
    return filtered_ast


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


def _find_function(module_ast: list[s.Statement], function_name: str) -> s.Statement_FunctionDefinition | None:
    for statement in module_ast:
        if isinstance(statement, s.Statement_FunctionDefinition) and statement.name == function_name:
            return statement
    return None


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
    tests.sort(key=lambda test: test.display_name)
    return tests


def _append_profile_records(compiler: EncoreCompiler, test_name: str, records: list) -> None:
    compiler.profile_records.extend(
        CompileProfileRecord(module=test_name, stage=record.stage, seconds=record.seconds) for record in records
    )


def _normalize_jobs(jobs: int) -> int:
    if jobs < 1:
        raise RuntimeError("--jobs must be greater than zero")
    return jobs


def _run_binary(executable_path: Path, program_args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(executable_path), *program_args], capture_output=True, text=True, check=False)


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
