#!/usr/bin/env python3
"""Bounded server acceptance for 0.6; no installed TE tools or real genome analysis."""
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
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',required=True,help='Project root; creates a fresh acceptance directory')
    p.add_argument('--threads',type=int,default=8,help='Fixture pool only, minimum 4; default 8')
    args=p.parse_args()
    if sys.platform!='linux' or args.threads<4 or len(os.sched_getaffinity(0))<args.threads:
        p.error('Linux with at least the requested 4+ available CPUs is required')
    repo=Path(__file__).resolve().parents[1]
    test=repo/'tests/integration_parallel.py'
    if not test.is_file(): p.error('Use this script from the extracted source package (tests/ must be present)')
    out=Path(args.root).resolve()/'acceptance'/('single-species-v06.'+time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+'.'+uuid.uuid4().hex[:8])
    out.mkdir(parents=True,exist_ok=False)
    env=dict(os.environ,PYTHONPATH=str(repo/'src'),TEFLOW_REPOSITORY=str(repo),PYTHONUNBUFFERED='1')
    env.pop('TEFLOW_FIXTURE_FAIL_STAGE',None)
    cmd=[sys.executable,str(test),'--output',str(out/'fixture'),'--pool-threads',str(args.threads)]
    record=dict(command=cmd,scope='160 bp synthetic genome, three fake TE tools, serial/parallel/failure tests',threads=args.threads,
                memory_reservation_mb=4096,enforcement='observe_only',real_genome_analysis=False,checksums_required=False)
    (out/'request.json').write_text(json.dumps(record,indent=2)+'\n')
    with (out/'acceptance.log').open('w') as log:
        result=subprocess.run(cmd,env=env,stdout=log,stderr=subprocess.STDOUT)
    status='SINGLE_SPECIES_ACCEPTANCE_PASSED' if result.returncode==0 else 'ACCEPTANCE_FAILED'
    archive=out.with_name(out.name+'.feedback.tar.gz')
    with tarfile.open(archive,'x:gz') as t:
        for path in sorted(out.rglob('*')):
            if path.is_symlink() or not path.is_file() or path.suffix not in ('.json','.jsonl','.log','.tsv'): continue
            with path.open('rb') as f:
                size=path.stat().st_size
                if size>2*1024*1024: f.seek(-2*1024*1024,2)
                data=f.read()
            name=path.relative_to(out).as_posix()+('.tail' if size>len(data) else '')
            entry=tarfile.TarInfo(name);entry.size=len(data);entry.mode=0o600
            t.addfile(entry,io.BytesIO(data))
    print(json.dumps(dict(status=status,output=str(out),feedback=str(archive),returncode=result.returncode),indent=2))
    return result.returncode


if __name__=='__main__': raise SystemExit(main())
