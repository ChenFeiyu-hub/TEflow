"""Real scheduler: scoped cancellation, child cleanup, unchanged resume and reports.

Only a 160-bp fixture and fake tools are used; no system settings are changed.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from teflow.cli import VERSIONS
from teflow.common import read_json, write_json
from teflow.resource_pool import inspect_pool
from teflow.runtime import group_alive

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--output')
p.add_argument('--installed',action='store_true')
args = p.parse_args()
if sys.platform != 'linux' or len(os.sched_getaffinity(0)) < 4:
    raise SystemExit('Linux with 4 available CPUs required')
repo = Path(__file__).resolve().parents[1]
root = Path(args.output).resolve() if args.output else Path(tempfile.mkdtemp(prefix='teflow-control-'))
root.mkdir(parents=True,exist_ok=True)
if any(root.iterdir()): raise SystemExit('Output must be empty')
env = dict(os.environ,PYTHONPATH=str(repo/'src'),TEFLOW_REPOSITORY=str(repo),PYTHONUNBUFFERED='1')
if args.installed:
    import teflow
    assert not Path(teflow.__file__).resolve().is_relative_to(repo)
    env.pop('PYTHONPATH',None); env.pop('TEFLOW_REPOSITORY',None)
genome = root/'genome.fa'; genome.write_text('>OriginalChr\n'+'ACGT'*40+'\n')
cfg = root/'run.json'
config = dict(schema_version=2,run_id='control',fixture_only=True,work_root=str(root/'work'),results_root=str(root/'results'),
    samples=[dict(id='plant',genome=str(genome),taxon_group='plant')],
    execution=dict(mode='server',threads=4,mem_mb=4096),
    branches=dict(edta=dict(enabled=True)),parameters=dict(max_divergence=40),
    qc={},evaluation=dict(promoter_analysis=False),
    tools={k:dict(command=[sys.executable,str(repo/'tests/mock_tool.py'),k],expected_version=VERSIONS[k])
           for k in ('edta','repeatmasker','trf','dustmasker')},databases=dict(files=[]))
write_json(cfg,config)

def cli(*items, code=0):
    r = subprocess.run([sys.executable,'-m','teflow',*map(str,items),'--config',str(cfg)],
        env=env,capture_output=True,text=True,timeout=120)
    with (root/'commands.log').open('a') as f: f.write(str(items)+'\n'+r.stdout+r.stderr+'\n')
    assert r.returncode == code,(items,r.returncode,r.stderr[-3000:],str(root))
    return json.loads(r.stdout) if r.stdout.lstrip().startswith('{') else r.stdout

first = cli('run-preview')
assert first['counts']['new_work'] > 0 and not (root/'work').exists()
cli('run','--target-stage','tracks')
base = root/'work/control/plant'
preserved = {name:(base/name).read_bytes() for name in ('prepared/manifest.json','tracks/complete.json')}
assert cli('run-preview')['counts']['existing_completion'] >= 1
foreign = subprocess.Popen([sys.executable,'-c','import time;time.sleep(180)'])
runner = None
try:
    with (root/'cancel-run.log').open('w') as log:
        runner = subprocess.Popen([sys.executable,'-m','teflow','run','--config',str(cfg)],
            env=dict(env,TEFLOW_FIXTURE_EVENTS=str(root/'events.jsonl'),TEFLOW_FIXTURE_DELAY='40',
                     TEFLOW_FIXTURE_SPAWN_CHILD='1'),stdout=log,stderr=subprocess.STDOUT)
        deadline = time.monotonic()+60
        command = base/'edta/run.log.command.json'
        while time.monotonic() < deadline:
            if runner.poll() is not None: raise AssertionError(('launcher exited early',str(root)))
            if command.exists() and (root/'events.jsonl').exists():
                if any(json.loads(line)['event']=='child_started' for line in (root/'events.jsonl').read_text().splitlines()):
                    break
            time.sleep(0.1)
        else: raise AssertionError(('command did not start',str(root)))
        request = cli('cancel')
        assert request['status']=='CANCEL_REQUESTED'
        assert runner.wait(timeout=40) == 130, str(root)
    state = cli('status')
    assert state['launcher']['status']=='cancelled', state
    assert foreign.poll() is None, 'unrelated process was affected'
    assert not inspect_pool(root/'work/.teflow-runtime')['leases']
    assert not group_alive(read_json(command)), 'command group survived cancellation'
    assert not (base/'edta/complete.json').exists()
    cli('cancel',code=2)
    cli('run','--resume')
    assert cli('status')['launcher']['status']=='succeeded'
    assert all((base/name).read_bytes()==data for name,data in preserved.items())
    source_files = {str(path):path.stat() for path in (root/'results').rglob('*') if path.is_file()}
    cli('report','--output',root/'report')
    result = read_json(root/'report/report.json')
    assert result['stage_status']['status']=='complete' and result['selected_branch'] is None
    assert result['accuracy_claim'] is False
    assert all(Path(path).stat().st_mtime_ns==stat.st_mtime_ns for path,stat in source_files.items())
    cli('report','--output',root/'report',code=2)
    assert cli('logs','--stage','edta')['logs']
    assert cli('logs')['logs']
    assert cli('runtime-summary')['attempts']
    cli('pack-feedback','--output',root/'feedback.tar.gz')
    import tarfile
    with tarfile.open(root/'feedback.tar.gz') as t:
        assert any(n.startswith('work/launches/') and n.endswith('/cancel.json') for n in t.getnames())
    write_json(root/'validation.json',dict(status='pass',installed=args.installed,
        checks=['preview_read_only','scoped_cancellation','owned_child_cleanup','foreign_process_preserved',
                'no_false_success','explicit_resume','completed_receipts_preserved','report_preserves_outputs',
                'bounded_logs','feedback_includes_launches'],real_genome_analysis=False))
    print(json.dumps(dict(status='pass',output=str(root))))
finally:
    if runner and runner.poll() is None:
        # Use its cooperative interface first even if the test failed.
        subprocess.run([sys.executable,'-m','teflow','cancel','--config',str(cfg)],env=env,capture_output=True)
        runner.wait(timeout=45)
    foreign.terminate(); foreign.wait(timeout=5)
