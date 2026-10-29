#!/usr/bin/env python3
"""Verify edit-session isolation and reject fast but stale compilation results."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

SCRIPTS = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("incremental", SCRIPTS/"compiler_incremental_benchmark.py")
incremental = importlib.util.module_from_spec(spec)
spec.loader.exec_module(incremental)


def workload(root):
    (root/"src").mkdir(parents=True)
    (root/"styles").mkdir()
    (root/"encore.toml").write_text('[project]\nname="graphene"\nversion="1.0.0"\ndependencies=[]\n')
    (root/"encore.lock").write_text('version=2\n[[packages]]\nname="std"\nregistry="http://127.0.0.1:9/index"\n')
    (root/"src/main.enq").write_text('''fn main() -> u32 {
    match argv(1) {
        Option::Some(command) => {
            if command == "import-character" { ret 1 }
            if command == "cook" { println("Usage: graphene cook <project directory>") ret 1 }
            camera.look(1, 0, false)
        }
    }
    ret 0
}
''')
    (root/"src/editor_camera.enq").write_text('''impl for EditorCameraState {
    pub fn look(self: mut Self, delta_x: f32, delta_y: f32, orbit: bool) ->() {
        self.yaw = self.yaw - delta_x * 0.006_f32
    }
}
''')
    (root/"styles/theme.css").write_text('.camera { opacity: 1; }\n')


class IncrementalContracts(unittest.TestCase):
    @unittest.skipIf(os.name=='nt','fixture executable uses a POSIX shebang')
    def test_nan_camera_output_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);binary=root/'target/dev/graphene'
            binary.parent.mkdir(parents=True)
            binary.write_text('#!/usr/bin/env python3\nprint("NaN")\n')
            binary.chmod(0o755)
            with self.assertRaisesRegex(ValueError,'stale or incorrect camera code'):
                incremental.verify_binary(root,'dev',.006,'unused')

    def test_plain_package_under_another_git_repository_preserves_sources_only(self):
        with tempfile.TemporaryDirectory() as directory:
            outer=Path(directory)
            subprocess.run(['git','init','-q',str(outer)],check=True)
            source=outer/'Physics';(source/'src').mkdir(parents=True)
            (source/'src/lib.enq').write_text('pub fn value() -> u32 { ret 1 }\n')
            (source/'target').mkdir();(source/'target/cache').write_text('not input')
            (source/'.env').write_text('not input')
            destination=outer/'snapshot'
            digest=incremental.snapshot(source,destination)
            self.assertEqual(incremental.source_files(destination),[Path('src/lib.enq')])
            self.assertEqual(incremental.tree_digest(destination),digest)

    def test_edit_sequence_preserves_interface_until_explicit_interface_edit(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);workload(root);incremental.ensure_probe(root)
            initial=incremental.tree_digest(root)
            incremental.edit(root,'unchanged',1)
            self.assertEqual(incremental.tree_digest(root),initial)
            incremental.edit(root,'method-body',1)
            self.assertIn('0.00601_f32',(root/'src/editor_camera.enq').read_text())
            self.assertIn('pub fn look(',(root/'src/editor_camera.enq').read_text())
            before=(root/'src/main.enq').read_text()
            incremental.edit(root,'relocate',1)
            self.assertEqual((root/'src/main.enq').read_text(),'\n\n\n'+before)
            incremental.edit(root,'interface',1)
            self.assertNotIn('camera.look(', (root/'src/main.enq').read_text())
            self.assertEqual((root/'src/main.enq').read_text().count('camera.look_bench_1('),2)
            previous=incremental.tree_digest(root)
            incremental.edit(root,'method-body',2)
            self.assertNotEqual(incremental.tree_digest(root),previous)

    def test_summary_excludes_warmup_and_diagnostics_and_pairs_by_repetition(self):
        samples=[]
        for repetition,before,after in ((1,100,70),(2,10,8)):
            for variant,seconds in (('baseline',before),('candidate',after)):
                samples.append(dict(variant=variant,case='main-body',repetition=repetition,
                                    role='measurement',result=dict(exit_code=0,wall_seconds=seconds)))
        for role in ('warmup','diagnostic'):
            samples.append(dict(variant='candidate',case='main-body',repetition=0,role=role,
                                result=dict(exit_code=0,wall_seconds=0.0001)))
        row=next(r for r in incremental.summarize(samples) if r['variant']=='candidate')
        self.assertEqual(row['repetitions'],2)
        self.assertEqual(row['paired_time_reduction_percent'],25)
        self.assertEqual(row['faster_pairs'],2)

    @unittest.skipIf(os.name=='nt','fixture executables use a POSIX shebang')
    def test_complete_cli_keeps_warm_caches_and_rejects_stale_executables(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);project=root/'Graphene';workload(project)
            source=root/'compiler';(source/'packages/core').mkdir(parents=True)
            (source/'packages/core/fixture').write_text('SDK')
            subprocess.run(['git','init','-q',str(source)],check=True)
            compiler=source/'fake-encore'
            compiler.write_text(textwrap.dedent('''\
                #!/usr/bin/env python3
                import hashlib,json,os,pathlib,re,sys
                if sys.argv[1:]==['--version']:
                    print('encore fixture');sys.exit(0)
                assert sys.argv[1]=='build'
                assert '--jobs' not in sys.argv
                project=pathlib.Path.cwd();cache=pathlib.Path(os.environ['ENCORE_BUILD_CACHE'])
                cache.mkdir(parents=True,exist_ok=True)
                count=cache/'counter';n=int(count.read_text()) if count.exists() else 0;count.write_text(str(n+1))
                with open(os.environ['INCREMENTAL_TRACE'],'a') as stream:
                    stream.write(json.dumps({'variant':cache.parent.name,'count':n,'timings':'--timings' in sys.argv})+'\\n')
                camera=(project/'src/editor_camera.enq').read_text();main=(project/'src/main.enq').read_text()
                coef=float(re.search(r'delta_x \\* ([0-9.]+)_f32',camera)[1])
                message=re.search(r'Usage: graphene cook <project directory>[^"\\n]*',main)[0]
                out=project/'target/dev';out.mkdir(parents=True,exist_ok=True);binary=out/'graphene'
                if not os.environ.get('INCREMENTAL_STALE') or not binary.exists():
                    binary.write_text('#!/usr/bin/env python3\\nimport sys\\nif sys.argv[1]=="__encore_bench_camera":\\n print('+repr(1.5707963-100*coef)+')\\nelse:\\n print('+repr(message)+')\\n sys.exit(1)\\n')
                    binary.chmod(0o755)
                if '--timings' in sys.argv:
                    (out/'encore-timings.json').write_text(json.dumps({'total_ms':1,'units':[]}))
                '''))
            compiler.chmod(0o755)
            registry=root/'registry';registry.mkdir()
            output=root/'results.json';trace=root/'trace'
            command=[sys.executable,str(SCRIPTS/'benchmark-compiler-tests.py'),str(compiler),
                     '--source',str(source),'--baseline-compiler',str(compiler),'--scenario','incremental',
                     '--project-root',str(project),'--registry-seed',str(registry),
                     '--repetitions','2','--output',str(output)]
            environment={**os.environ,'INCREMENTAL_TRACE':str(trace)}
            before=incremental.tree_digest(project)
            result=subprocess.run(command,env=environment,text=True,capture_output=True,timeout=60)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            report=json.loads(output.read_text())
            self.assertTrue(report['completed']);self.assertFalse(report['failed'])
            self.assertEqual(report['profile'],'dev')
            self.assertEqual(incremental.tree_digest(project),before)
            measurements=[s for s in report['samples'] if s['role']=='measurement']
            self.assertEqual(len(measurements),24)
            self.assertEqual(measurements[0]['variant'],'baseline')
            self.assertEqual(measurements[12]['variant'],'candidate')
            for variant in ('baseline','candidate'):
                rows=[json.loads(line) for line in trace.read_text().splitlines() if json.loads(line)['variant']==variant]
                self.assertEqual([r['count'] for r in rows],list(range(19)))
                self.assertEqual(sum(r['timings'] for r in rows),7)
            seed=root/'baseline-cache';seed.mkdir();(seed/'counter').write_text('9')
            seeded=root/'seeded.json'
            seeded_command=command.copy();seeded_command[seeded_command.index('--output')+1]=str(seeded)
            seeded_command[seeded_command.index('--repetitions')+1]='1'
            seeded_command += ['--baseline-cache-seed',str(seed),'--first-repetition','10']
            result=subprocess.run(seeded_command,env=environment,text=True,capture_output=True,timeout=60)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            seeded_report=json.loads(seeded.read_text())
            self.assertTrue(seeded_report['completed'])
            self.assertIn('cache_seed_sha256',seeded_report['variants']['baseline'])
            self.assertEqual((seed/'counter').read_text(),'9')
            self.assertEqual((seeded.with_suffix('.logs')/'baseline/cache/counter').read_text(),'22')
            broken=root/'stale.json';command[command.index('--output')+1]=str(broken)
            result=subprocess.run(command,env={**environment,'INCREMENTAL_STALE':'1'},
                                  text=True,capture_output=True,timeout=60)
            self.assertNotEqual(result.returncode,0)
            failed=json.loads(broken.read_text());self.assertFalse(failed['completed'])
            self.assertTrue(any('stale or incorrect' in e for e in failed['failed']))


if __name__=='__main__':
    unittest.main()
