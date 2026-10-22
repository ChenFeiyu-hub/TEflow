#!/usr/bin/env python3
"""Bounded release server acceptance: fake tools, synthetic 160-bp input, no installs."""
import argparse
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import time
import uuid


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',required=True)
    p.add_argument('--threads',type=int,default=8)
    args = p.parse_args()
    if sys.platform!='linux' or args.threads<4 or len(os.sched_getaffinity(0))<args.threads:
        p.error('Linux with at least the requested 4+ available CPUs is required')
    repo = Path(__file__).resolve().parents[1]
    out = Path(args.root).resolve()/'acceptance'/('release-v1.'+time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+'.'+uuid.uuid4().hex[:8])
    if not (repo/'tests/integration_control.py').is_file(): p.error('Use the extracted source package, including tests/')
    out.mkdir(parents=True,exist_ok=False)
    env = dict(os.environ,PYTHONPATH=str(repo/'src'),TEFLOW_REPOSITORY=str(repo),PYTHONUNBUFFERED='1')
    for key in ('TEFLOW_FIXTURE_FAIL_STAGE','TEFLOW_FIXTURE_EVENTS','TEFLOW_FIXTURE_DELAY',
                'TEFLOW_FIXTURE_SPAWN_CHILD','TEFLOW_CANCEL_FILE','TEFLOW_LAUNCH_ID'):
        env.pop(key,None)
    tasks = [
        ('delivery-unit',[sys.executable,'-m','unittest','discover','-s',str(repo/'tests'),'-p','test_delivery_v1.py','-v']),
        ('control',[sys.executable,str(repo/'tests/integration_control.py'),'--output',str(out/'control')]),
        ('parallel',[sys.executable,str(repo/'tests/integration_parallel.py'),'--output',str(out/'parallel'),
                     '--pool-threads',str(args.threads)])]
    outcomes = []
    for name, command in tasks:
        with (out/(name+'.log')).open('w') as log:
            r = subprocess.run(command,env=env,stdout=log,stderr=subprocess.STDOUT)
        outcomes.append(dict(case=name,returncode=r.returncode))
        print(json.dumps(outcomes[-1]),flush=True)
        if r.returncode: break
    result = dict(status='RELEASE_ACCEPTANCE_PASSED' if len(outcomes)==3 and all(r['returncode']==0 for r in outcomes) else 'RELEASE_ACCEPTANCE_FAILED',
                  cases=outcomes,output=str(out),real_genome_analysis=False,checksum_steps=False,
                  scope='Synthetic scheduler/cancellation/resume/parallelism; not TE biology or hard-memory enforcement')
    (out/'validation.json').write_text(json.dumps(result,indent=2)+'\n')
    archive = out.with_name(out.name+'.feedback.tar.gz')
    with tarfile.open(archive,'x:gz') as tar:
        for path in sorted(out.rglob('*')):
            if path.is_symlink() or not path.is_file() or path.suffix not in ('.json','.jsonl','.log','.tsv'): continue
            with path.open('rb') as f:
                size=path.stat().st_size
                if size>2*1024*1024: f.seek(-2*1024*1024,2)
                data=f.read()
            name=path.relative_to(out).as_posix()+('.tail' if size>len(data) else '')
            item=tarfile.TarInfo(name); item.size=len(data); item.mode=0o600
            tar.addfile(item,io.BytesIO(data))
    result['feedback']=str(archive)
    print(json.dumps(result,indent=2))
    return 0 if result['status']=='RELEASE_ACCEPTANCE_PASSED' else 1


if __name__=='__main__': raise SystemExit(main())
