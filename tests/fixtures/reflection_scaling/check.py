#!/usr/bin/env python3
"""Small reflected records must not rescan every unrelated declaration per field."""
from pathlib import Path
import argparse, json, os, subprocess, tempfile, time

parser = argparse.ArgumentParser()
parser.add_argument('--compiler', required=True)
parser.add_argument('--types', type=int, default=500)
parser.add_argument('--timeout', type=float, default=120)
args = parser.parse_args()
repo = Path(__file__).resolve().parents[3]
compiler = Path(args.compiler).resolve()
env = os.environ.copy()
env['ENCORE_CORE_DIR'] = str(repo / 'packages/core')
with tempfile.TemporaryDirectory(prefix='encore-reflection-scaling-') as directory:
    root = Path(directory)
    (root / 'model/src').mkdir(parents=True)
    (root / 'app/src').mkdir(parents=True)
    (root / 'model/encore.toml').write_text('[project]\nname="scaling_model"\nversion="0.0.0"\ndependencies=[]\n')
    model = 'import core::vec::Vec\npub struct Asset { name:str values:Vec[f32] }\n'
    model += ''.join(f'pub struct Unused{i} {{ x:f32 y:f32 z:f32 w:f32 }}\n' for i in range(args.types))
    (root / 'model/src/lib.enq').write_text(model)
    binary = repo / 'packages/binary'
    (root / 'app/encore.toml').write_text('[project]\nname="reflection_scaling"\nversion="0.0.0"\ndependencies=["path@../model", "path@' + binary.as_posix() + '"]\n')
    (root / 'app/src/main.enq').write_text('''import core::result::Result
import binary::{encode, decode}
import scaling_model::Asset
fn main() -> u32 {
    let encoded = match encode(Asset { "fish", vec![1.0_f32, 2.0, 3.0] }) { Ok(value) => value Err(_) => { ret 1 } }
    let asset = match decode[Asset](encoded) { Ok(value) => value Err(_) => { ret 2 } }
    ret if asset.name == "fish" && asset.values.len() == 3 { 0_u32 } else { 3_u32 }
}
''')
    started = time.monotonic()
    try:
        result = subprocess.run([str(compiler), 'check'], cwd=root / 'app', env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=args.timeout)
    except subprocess.TimeoutExpired:
        print(json.dumps({'types': args.types, 'timeout_seconds': args.timeout, 'completed': False}))
        raise SystemExit(124)
    elapsed = time.monotonic() - started
    print(json.dumps({'types': args.types, 'seconds': round(elapsed, 3), 'completed': True, 'exit_code': result.returncode}))
    if result.returncode:
        print(result.stdout)
    raise SystemExit(result.returncode)
