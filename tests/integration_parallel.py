"""Bounded single-species branch acceptance with actual Snakemake and fake TE tools.

Run on Linux with >=8 available CPUs; no upstream tools or downloaded data used.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from teflow.common import write_json,read_json
from teflow.cli import VERSIONS,OPTIONAL_VERSIONS
from teflow.resource_pool import inspect_pool

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--output',required=False)
p.add_argument('--pool-threads',type=int,default=8)
p.add_argument('--installed',action='store_true',help='Use installed runtime/recipes outside the checkout')
args=p.parse_args()
if sys.platform!='linux' or args.pool_threads<4 or len(os.sched_getaffinity(0))<args.pool_threads:
    raise SystemExit('Acceptance requires Linux and available CPUs >= --pool-threads >= 4')
repo=Path(__file__).resolve().parents[1]
root=Path(args.output).resolve() if args.output else Path(tempfile.mkdtemp(prefix='teflow-v06-parallel-'))
root.mkdir(parents=True,exist_ok=True)
if any(root.iterdir()): raise SystemExit('Use an empty acceptance output directory')
env=dict(os.environ,PYTHONPATH=str(repo/'src'),TEFLOW_REPOSITORY=str(repo),TEFLOW_FIXTURE_DELAY='0.6')
if args.installed:
    import teflow
    from teflow.assets import asset_root
    assert not Path(teflow.__file__).resolve().is_relative_to(repo),teflow.__file__
    assert asset_root().name=='_assets'
    env.pop('PYTHONPATH',None);env.pop('TEFLOW_REPOSITORY',None)
genome=root/'genome.fa'; genome.write_text('>OriginalChr\n'+'ACGT'*40+'\n')
names=['edta','edta_tetrimmer','hite']
config=dict(schema_version=2,run_id='serial',fixture_only=True,work_root=str(root/'work'),results_root=str(root/'results'),
    samples=[dict(id='fixture',genome=str(genome),taxon_group='plant')],
    execution=dict(mode='server',threads=args.pool_threads,mem_mb=4096),parameters=dict(max_divergence=40),
    branches={name:dict(enabled=True) for name in names},
    qc={},evaluation=dict(promoter_analysis=False),exports=dict(softmask_policies=['te_primary','all_interspersed']),
    tools={k:dict(command=[sys.executable,str(repo/'tests/mock_tool.py'),k],expected_version=v)
           for k,v in {**VERSIONS,'hite':OPTIONAL_VERSIONS['hite']}.items()},databases=dict(files=[],pfam_dir=str(root/'fake_pfam')))

def cli(cfg,*items,expected=0,extra=None):
    proc=subprocess.run([sys.executable,'-m','teflow',*map(str,items),'--config',str(cfg)],env={**env,**(extra or {})},
                        stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=180)
    with (root/'commands.log').open('a') as f: f.write(str(items)+'\n'+proc.stdout+'\n')
    if (proc.returncode==0)!=(expected==0): raise AssertionError((items,proc.returncode,proc.stdout[-5000:],str(root)))
    return proc.stdout

configs={}
for mode in ('serial','parallel','failure'):
    c=copy.deepcopy(config); c['run_id']=mode
    if mode!='serial':
        c['execution']['scheduling']=dict(mode='branches',max_jobs=2,io_slots=2,memory_headroom_mb=0,poll_seconds=1,
             stages={name:dict(threads=args.pool_threads//2 if name in ('edta','hite') else 4,mem_mb=512) for name in ('edta','tetrimmer','hite','repeatmasker')}
                    | {name:dict(threads=1,mem_mb=128) for name in ('tracks','qc','export','prepared')})
    cfg=root/(mode+'.json'); write_json(cfg,c); configs[mode]=cfg
    extra=dict(TEFLOW_FIXTURE_EVENTS=str(root/(mode+'.events.jsonl')))
    if mode=='failure': extra['TEFLOW_FIXTURE_FAIL_STAGE']='hite'
    cli(cfg,'run',expected=1 if mode=='failure' else 0,extra=extra)
    assert not inspect_pool(root/'work/.teflow-runtime')['leases']

intervals={}
for mode in ('serial','parallel'):
    rows=[json.loads(x) for x in (root/(mode+'.events.jsonl')).read_text().splitlines()]
    starts={r['pid']:r for r in rows if r['event']=='start'}
    intervals[mode]=[(starts[r['pid']],r) for r in rows if r['event']=='end']
    overlaps=[]
    for i,(a,b) in enumerate(intervals[mode]):
        for x,y in intervals[mode][i+1:]:
            if max(a['at'],x['at']) < min(b['at'],y['at']):
                overlaps.append((a['tool'],x['tool']))
                assert set(a['cpu_ids']).isdisjoint(x['cpu_ids']), (a,x)
                assert a['tmpdir']!=x['tmpdir']
    if mode=='serial': assert not overlaps
    else: assert overlaps, 'No actual branch overlap observed'

for branch in names:
    for name in ('library.fa','te.mask.bed','repeat.mask.bed','mask_sources.tsv','classification_inventory.tsv',
                 'genome.softmasked.fa','genome.softmasked.all_interspersed.fa','te_fragments.gff3'):
        assert (root/'results/serial/fixture'/branch/name).read_bytes()==(root/'results/parallel/fixture'/branch/name).read_bytes(),(branch,name)
failed=root/'results/failure/fixture'
assert (failed/'edta/manifest.json').exists() and (failed/'edta_tetrimmer/manifest.json').exists()
assert not (failed/'manifest.json').exists() and not (failed/'hite/manifest.json').exists()
status=json.loads(cli(configs['failure'],'status'))
states={r['stage']:r['status'] for r in status['stages']}
assert states['hite']=='failed' and states['export']=='blocked_dependency',states
assert states['export_edta']=='complete',states
# Offline re-evaluation never changes source files or requires executing their wrappers.
oldroot=root/'results/parallel'
before={str(p):p.read_bytes() for p in oldroot.rglob('*') if p.is_file()}
cli(configs['parallel'],'reevaluate','--output',root/'reevaluated')
assert all(Path(k).read_bytes()==v for k,v in before.items())
assert (root/'reevaluated/fixture/coverage_layers.tsv').exists()
cli(configs['parallel'],'reevaluate','--output',root/'reevaluated',expected=1)
cli(configs['parallel'],'audit-results','--output',root/'audit.json')
assert all(r['status']=='consistent' for r in read_json(root/'audit.json')['branches'])
cli(configs['parallel'],'report','--output',root/'report')
assert read_json(root/'report/report.json')['edta_tetrimmer_retention'][0]['status']=='computed'
cli(configs['parallel'],'select','--branch','edta','--policy','te_primary','--mode','copy','--output',root/'delivery')
assert (root/'delivery/genome.softmasked.fa').read_bytes()==(root/'results/parallel/fixture/edta/genome.softmasked.fa').read_bytes()
cli(configs['parallel'],'select','--branch','edta','--policy','te_primary','--mode','copy','--output',root/'delivery',expected=1)
assert all(Path(k).read_bytes()==v for k,v in before.items())
report=dict(status='pass',scope='Synthetic three-branch actual Snakemake acceptance; not a genome performance benchmark',
    checks=['actual_parallel_overlap','serial_no_overlap','nonoverlapping_cpu_affinity','private_tmpdir',
            'serial_parallel_scientific_equivalence','independent_branches_finish_after_failure',
            'blocked_dependents_reported','no_final_success_after_failure','leases_released',
            'offline_reevaluation_preserves_sources','audit_consensus_coordinates','lineage_report','explicit_delivery_choice_preserves_sources'],output=str(root))
write_json(root/'validation.json',report)
print(json.dumps(report,indent=2))
