import concurrent.futures
import json
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from teflow.teaid_isolation import IsolatedSubprocess


_worker_proxy = None


def forked_teaid(args):
    return _worker_proxy.run(args, check=True, capture_output=True, text=True, timeout=12)


@unittest.skipUnless(sys.platform == "linux", "Linux subprocess execution contract")
class IsolationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="teaid-isolation-test-")
        self.root = Path(self.temp.name)
        self.binary = self.root / "TE-Aid"
        self.binary.write_text("#!" + sys.executable + "\n" + '''import json, pathlib, sys, time
a=sys.argv
q=pathlib.Path(a[a.index('-q')+1]); out=pathlib.Path(a[a.index('-o')+1])
if '--fail' in a:
    print('real BLAST failure', file=sys.stderr); sys.exit(7)
header=pathlib.Path('header'); header.write_text(q.name)
barrier=q.parent
(barrier/(q.name+'.ready')).touch()
deadline=time.monotonic()+8
while len(list(barrier.glob('*.ready'))) < 2:
    if time.monotonic()>deadline: raise RuntimeError('barrier timeout')
    time.sleep(.01)
assert header.read_text()==q.name, 'shared cwd corrupted header'
(out/'result.json').write_text(json.dumps({'cwd':str(pathlib.Path.cwd()),'query':q.name}))
header.unlink()
print('unchanged stdout')
''')
        self.binary.chmod(0o755)
        self.proxy = IsolatedSubprocess(self.binary)
        self.genome = self.root / "genome.fa"; self.genome.write_text(">x\nACGT\n")

    def tearDown(self):
        self.temp.cleanup()

    def args(self, name):
        q = self.root / (name + ".fa"); q.write_text(">x\nACGT\n")
        out = self.root / name
        return [str(self.binary), "-q", str(q), "-g", str(self.genome), "-o", str(out)]

    def test_concurrent_private_workdirs_and_parent_cwd_unchanged(self):
        cwd = Path.cwd()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.proxy.run, self.args(n), check=True, capture_output=True, text=True, timeout=12)
                       for n in ("a", "b")]
            results = [f.result() for f in futures]
        records = [json.loads((self.root / n / "result.json").read_text()) for n in ("a", "b")]
        self.assertNotEqual(records[0]["cwd"], records[1]["cwd"])
        self.assertEqual(Path.cwd(), cwd)
        self.assertTrue(all(r.stdout.strip() == "unchanged stdout" and not r.stderr for r in results))
        self.assertTrue(all(not Path(r["cwd"]).exists() for r in records))

    def test_real_errors_and_return_codes_are_not_suppressed(self):
        with self.assertRaises(subprocess.CalledProcessError) as got:
            self.proxy.run(self.args("bad") + ["--fail"], check=True, capture_output=True, text=True)
        self.assertEqual(got.exception.returncode, 7)
        self.assertIn("real BLAST failure", got.exception.stderr)

    def test_fork_workers_inherit_module_local_proxy(self):
        global _worker_proxy
        _worker_proxy = self.proxy
        try:
            with concurrent.futures.ProcessPoolExecutor(max_workers=2,
                    mp_context=multiprocessing.get_context("fork")) as pool:
                results = list(pool.map(forked_teaid, [self.args(n) for n in ("fork-a", "fork-b")]))
            records = [json.loads((self.root / n / "result.json").read_text()) for n in ("fork-a", "fork-b")]
            self.assertNotEqual(records[0]["cwd"], records[1]["cwd"])
            self.assertTrue(all(r.stdout.strip() == "unchanged stdout" and not r.stderr for r in results))
        finally:
            _worker_proxy = None

    def test_relative_paths_are_refused_and_other_commands_unchanged(self):
        args = self.args("relative"); args[2] = "relative.fa"
        with self.assertRaisesRegex(ValueError, "absolute"):
            self.proxy.run(args)
        r = self.proxy.run([sys.executable, "-c", "print('ordinary')"], check=True, capture_output=True, text=True)
        self.assertEqual(r.stdout.strip(), "ordinary")
