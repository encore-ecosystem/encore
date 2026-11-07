#!/usr/bin/env python3
"""Focused native generator verification, executed only by GitHub Actions."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile

root = Path(__file__).resolve().parents[1]
output = root / 'target/generator-probe'
output.mkdir(parents=True, exist_ok=True)
environment = dict(os.environ, ENCORE_CORE_DIR=str(root / 'packages/core'),
                   ENCORE_INDEX_URL='http://127.0.0.1:9/index')
failed = []
group = os.environ.get('GENERATOR_PROBE_GROUP', 'all')


def run(name, command, cwd=root, timeout=1800, extra=None):
    try:
        result = subprocess.run(command, cwd=cwd, env=environment | (extra or {}),
                                text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, timeout=timeout)
        text = result.stdout
        code = result.returncode
    except subprocess.TimeoutExpired as error:
        text = str(error) + '\n' + str(error.stdout or '')
        code = 124
    (output / (name + '.log')).write_text(text)
    print(name, 'passed' if code == 0 else 'FAILED', flush=True)
    if code:
        failed.append(name)
        print(text, flush=True)
    return code


inputs = json.loads((root / 'scripts/generator-probe-inputs.json').read_text())
actual = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
pins = subprocess.check_output(['git', 'ls-tree', 'HEAD', 'packages/'], cwd=root, text=True)
(output / 'identity.json').write_text(json.dumps({'probe': actual, 'candidate': inputs['candidate'], 'pins': pins}, indent=2))
if group in ('all', 'build'):
    asset = 'encore-x86_64-unknown-linux-gnu.tar.gz'
    seed_dir = output / 'seed-download'
    seed_dir.mkdir()
    subprocess.run(['gh', 'release', 'download', 'v0.1.14-neumann', '--repo', 'encore-ecosystem/encore',
                    '--pattern', asset, '--pattern', asset + '.sha256', '--dir', str(seed_dir)], check=True)
    expected = (seed_dir / (asset + '.sha256')).read_text().split()[0].lower()
    assert hashlib.sha256((seed_dir / asset).read_bytes()).hexdigest() == expected
    with tarfile.open(seed_dir / asset) as archive:
        archive.extractall(output / 'seed', filter='data')
    seed = next((output / 'seed').glob('*/bin/encore'))
    seed.chmod(0o755)
    run('native-lifecycle', ['python3', 'scripts/test-node-runtime.py'])
    run('native-lifecycle-sanitized', ['python3', 'scripts/test-node-runtime.py', '--sanitize'])
    if run('compiler-build', [str(seed), 'build', '--profile', 'extreme']):
        (output / 'result.json').write_text(json.dumps({'failed': failed}, indent=2))
        raise SystemExit(1)
    if group == 'build':
        (output / 'result.json').write_text(json.dumps({'failed': failed}, indent=2))
        raise SystemExit(bool(failed))
compiler = root / 'target/extreme/encore'
compiler.chmod(0o755)
if group == 'storage':
    cases = {
        'generic-capture': {
            'main.enq': 'struct State { value: usize }\nfn values[T](state: T) -> usize { yield 1_usize yield 2_usize }\nfn main() -> u32 { let state = State<S>{3_usize} for value in values(state) {} ret 0_u32 }\n',
        },
        'foreign-capture': {
            'state.enq': 'pub struct State { value: usize }\npub struct Holder { state: State<S> }\n',
            'main.enq': 'import refrain::state::{State, Holder}\nfn values() -> usize { let state = Holder{State<S>{3_usize}} yield 1_usize yield state.state.value }\nfn main() -> u32 { for value in values() {} ret 0_u32 }\n',
        },
        'foreign-parameter': {
            'state.enq': 'pub struct State { value: usize }\npub struct Holder { state: State<S> }\n',
            'main.enq': 'import refrain::state::{State, Holder}\nfn values(state: Holder) -> usize { yield 1_usize yield state.state.value }\nfn main() -> u32 { let state = Holder{State<S>{3_usize}} for value in values(state) {} ret 0_u32 }\n',
        },
    }
    for label, files in cases.items():
        case = output / label
        (case / 'src').mkdir(parents=True)
        (case / 'encore.toml').write_text('[project]\nname="generator_storage"\nversion="0.0.0"\ndependencies=[]\n')
        for name, source in files.items():
            (case / 'src' / name).write_text(source)
        # A successful compile is the regression: these values must not
        # become owned by a heap frame after their stack placement expires.
        result = subprocess.run([str(compiler), 'build'], cwd=case, env=environment,
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                timeout=600)
        (output / ('storage-' + label + '.log')).write_text(result.stdout)
        print(label, 'exit', result.returncode, result.stdout, flush=True)
        if result.returncode == 0 or 'generator-stack-node-escape' not in result.stdout:
            failed.append('storage-' + label)
if group in ('all', 'language'):
    run('generator-language', [str(compiler), 'test', '--jobs', '2', '--filter', 'generator'])
    run('async-diagnostic', [str(compiler), 'test', '--jobs', '2', '--filter', 'negative_trait_method_async_mismatch'])
if group in ('all', 'ehir'):
    run('ehir-generators', [str(compiler), 'test', '--jobs', '2', '--filter', 'generators'], root / 'packages/ehir')
    run('preparation-cache', [str(compiler), 'test', '--jobs', '2', '--filter', 'preparation_cache'], root / 'packages/ehir')
if group in ('all', 'metadata'):
    run('package-metadata', ['bash', 'scripts/ci-test.sh', str(compiler), '--jobs', '2', '--filter', 'integration_generator_package_metadata'],
        extra={'CI_TEST_RUN_ID': 'generator-probe'})
if group in ('all', 'language'):
    if not run('iterator-build', [str(compiler), 'build'], root / 'examples/iterator'):
        run('iterator-run', [str(root / 'examples/iterator/target/dev/iterators')], root / 'examples/iterator')
formatted = []
if group in ('all', 'format'):
    for index, relative in enumerate(inputs['format_files']):
        path = root / relative
        if not path.is_file():
            continue
        before = path.read_bytes()
        run('format-' + str(index), [str(compiler), 'format', str(path)])
        if path.read_bytes() != before:
            formatted.append(relative)
with tarfile.open(output / 'formatted-sources.tar.gz', 'w:gz') as archive:
    for relative in formatted:
        archive.add(root / relative, arcname=relative)
(output / 'result.json').write_text(json.dumps({'failed': failed, 'formatted': formatted}, indent=2))
print('Formatter changes:', formatted, flush=True)
raise SystemExit(bool(failed))
