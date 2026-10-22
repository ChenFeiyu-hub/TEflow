"""Optional real-micromamba regression using tiny, offline package metadata.

No package is downloaded or installed. This tests solver request semantics,
not compatibility of the complete server's EDTA dependency graph.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


@unittest.skipUnless(os.environ.get('TEFLOW_TEST_MICROMAMBA'), 'Optional real micromamba executable')
class RepairSolverTests(unittest.TestCase):
    def test_freeze_blocks_target_downgrade_but_other_package_specs_allow_it(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            channel = root / 'channel'
            meta = root / 'environment/conda-meta'
            meta.mkdir(parents=True)
            records = []
            for name, version in [('pandas', '3.0.6'), ('pandas', '2.3.3'), ('anchor', '1.0')]:
                filename = f'{name}-{version}-0.tar.bz2'
                records.append(dict(name=name, version=version, build='0', build_number=0,
                                    depends=[], subdir='linux-64', fn=filename,
                                    url=channel.as_uri() + '/linux-64/' + filename,
                                    channel=channel.as_uri(), size=1, md5='0' * 32))
            for subdir in ('linux-64', 'noarch'):
                folder = channel / subdir
                folder.mkdir(parents=True)
                packages = {r['fn']: r for r in records} if subdir == 'linux-64' else {}
                (folder / 'repodata.json').write_text(json.dumps(dict(
                    info=dict(subdir=subdir), packages=packages, repodata_version=1)))
            for record in (records[0], records[2]):
                installed = dict(record, files=[])
                (meta / (record['fn'].removesuffix('.tar.bz2') + '.json')).write_text(json.dumps(installed))
            (meta / 'history').write_text('# synthetic solver-only environment\n')
            before = {p.name: p.read_bytes() for p in meta.iterdir()}
            specs = root / 'keep-installed-except-pandas.txt'
            specs.write_text('anchor=1.0=0\n')
            common = [os.environ['TEFLOW_TEST_MICROMAMBA'], 'install', '--no-rc',
                      '--root-prefix', str(root / 'mamba'), '-p', str(meta.parent),
                      '--offline', '--override-channels', '-c', channel.as_uri(),
                      '--strict-channel-priority', '--dry-run', '--json']
            old = subprocess.run(common + ['--freeze-installed', 'pandas=2.3.3'],
                                 capture_output=True, text=True, timeout=30)
            self.assertNotEqual(old.returncode, 0, old.stdout)
            new = subprocess.run(common + ['--file', str(specs), 'pandas=2.3.3'],
                                 capture_output=True, text=True, timeout=30)
            self.assertEqual(new.returncode, 0, new.stdout + new.stderr)
            result = json.loads(new.stdout)
            self.assertTrue(result['success'])
            linked = result['actions'].get('LINK', [])
            self.assertEqual([(r['name'], r['version']) for r in linked], [('pandas', '2.3.3')])
            self.assertEqual({p.name: p.read_bytes() for p in meta.iterdir()}, before)


if __name__ == '__main__':
    unittest.main()
