"""The solver-only repair must never install, rewrite v01, or start a genome run."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == "posix" and shutil.which("bash"), "Linux shell contract")
class RepairScriptTests(unittest.TestCase):
    def exercise(self, extra_package=None, solver_plan=None):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for part in ('engine/conda-meta', 'edta/conda-meta', 'locks'):
                (root / 'envs' / part).mkdir(parents=True)
            original = '{"run_id":"at_pilot_v01"}\n'
            (root / 'at_pilot.local.json').write_text(original)
            (root / 'envs/locks/edta.linux-64.explicit.txt').write_text('original-lock\n')
            for name, version in [('edta', '2.3.0'), ('tir-learner', '3.0.7'), ('pandas', '3.0.6')]:
                (root / 'envs/edta/conda-meta' / (name + '.json')).write_text(
                    json.dumps(dict(name=name, version=version, build='test_build_0')))
            capture = root / 'calls.jsonl'
            mock = root / 'mock-mamba'
            mock.write_text('''#!/usr/bin/env python3
import json, os, subprocess, sys
a = sys.argv[1:]
with open(os.environ['CAPTURE'], 'a') as out:
    out.write(json.dumps(a) + '\\n')
if a[0] == 'list':
    print('@EXPLICIT\\nhttps://example.invalid/pandas-3.0.6.conda')
elif a[0] == 'install':
    assert '--dry-run' in a, 'Solver-only command attempted installation'
    assert '--freeze-installed' not in a, 'The target pandas package must remain replaceable'
    specs = open(a[a.index('--file') + 1]).read().splitlines()
    assert not any(s.startswith('pandas=') for s in specs), specs
    assert 'edta=2.3.0=test_build_0' in specs, specs
    assert 'tir-learner=3.0.7=test_build_0' in specs, specs
    assert 'pandas=2.3.3' in a, a
    if os.environ.get('SOLVER_PLAN'):
        print(os.environ['SOLVER_PLAN'])
    else:
        names = ['pandas'] + ([os.environ['EXTRA_PACKAGE']] if os.environ.get('EXTRA_PACKAGE') else [])
        print(json.dumps(dict(success=True, actions={'LINK': [dict(name=n) for n in names]})))
elif a[0] == 'run' and a[3:7] == ['python', '-m', 'pip', 'freeze']:
    print('te-annotation-workflow==0.1.2')
elif a[0] == 'run' and a[3:5] == ['python', '-']:
    raise SystemExit(subprocess.call([sys.executable] + a[4:]))
else:
    raise SystemExit('Unexpected command: ' + repr(a))
''')
            mock.chmod(0o755)
            env = dict(os.environ, MICROMAMBA=str(mock), CAPTURE=str(capture),
                       EXTRA_PACKAGE=extra_package or '',
                       SOLVER_PLAN=json.dumps(solver_plan) if solver_plan else '')
            p = subprocess.run(['bash', str(REPO / 'scripts/repair_edta_pandas.sh'), str(root), '--solve-only'],
                               env=env, capture_output=True, text=True)
            self.assertEqual((root / 'at_pilot.local.json').read_text(), original)
            self.assertEqual((root / 'envs/locks/edta.linux-64.explicit.txt').read_text(), 'original-lock\n')
            self.assertFalse((root / 'at_pilot_v02.local.json').exists())
            self.assertFalse((root / 'work').exists())
            calls = [json.loads(line) for line in capture.read_text().splitlines()]
            self.assertTrue(all('--dry-run' in a for a in calls if a[0] == 'install'))
            return p

    def test_solver_only_preserves_original_run_and_environment(self):
        p = self.exercise()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn('No environment/config/workflow change was applied', p.stdout)

    def test_unexpected_solver_changes_stop_before_installation(self):
        p = self.exercise('numpy')
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('Unexpected package changes', p.stdout + p.stderr)

    def test_recorded_pandas_downgrade_and_both_timezone_dependencies_are_allowed(self):
        plan = json.loads((REPO / 'tests/fixtures/pandas233_solver_plan.json').read_text())
        p = self.exercise(solver_plan=plan)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn('Planned changes: pandas, python-tzdata, pytz', p.stdout)


if __name__ == '__main__':
    unittest.main()
