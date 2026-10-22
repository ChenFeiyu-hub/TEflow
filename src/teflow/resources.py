"""Single-specimen scheduling policy. Biology stays outside the generic lease pool."""
from .common import WorkflowError
from .registry import stage_kind

KINDS = {'prepared','tracks','export','qc','repeatmasker','edta','tetrimmer','heliano','hite','assembly'}


def policy(c):
    supplied = c['execution'].get('scheduling', {})
    return {**dict(mode='serial', max_jobs=1, io_slots=1, keep_going=True,
                   memory_headroom_mb=1024, poll_seconds=10, admission_timeout_seconds=600, stages={}),
            **supplied}


def stage_resources(c, stage):
    p, e, kind = policy(c), c['execution'], stage_kind(stage)
    light = kind in {'prepared','tracks','export'}
    if p['mode'] == 'serial':
        return dict(threads=1 if light else e['threads'],
                    mem_mb=min(e['mem_mb'], 4096) if light else e['mem_mb'], io=1)
    if light or kind == 'assembly':
        defaults = dict(threads=1, mem_mb=min(4096, e['mem_mb']), io=1)
    elif kind in {'repeatmasker','qc'}:
        defaults = dict(threads=4 if kind == 'repeatmasker' else min(4,e['threads']),
                        mem_mb=max(1, e['mem_mb']//p['max_jobs']), io=1)
    else:
        # Long discovery stages remain conservative until the operator supplies measurements.
        defaults = dict(threads=e['threads'], mem_mb=e['mem_mb'], io=1)
    return {**defaults, **p['stages'].get(kind, {}), **p['stages'].get(stage, {})}


def validate(c):
    from .branches import graph
    raw = c['execution'].get('scheduling', {})
    if not isinstance(raw, dict):
        raise WorkflowError('execution.scheduling must be an object')
    p = policy(c)
    if set(raw) - set(p) or set(raw) - {'mode','max_jobs','io_slots','keep_going','memory_headroom_mb','poll_seconds','admission_timeout_seconds','stages'}:
        raise WorkflowError('Unknown scheduling option')
    if p['mode'] not in ('serial','branches') or type(p['keep_going']) is not bool:
        raise WorkflowError('Scheduling mode must be serial or branches; keep_going must be boolean')
    for k in ('max_jobs','io_slots','poll_seconds','admission_timeout_seconds','memory_headroom_mb'):
        if type(p[k]) is not int or p[k] < (0 if k == 'memory_headroom_mb' else 1):
            raise WorkflowError('Invalid scheduling.' + k)
    if p['mode'] == 'serial' and (p['max_jobs'] != 1 or p['io_slots'] != 1 or p['stages']):
        raise WorkflowError('Stage overrides/concurrency require scheduling.mode=branches')
    if p['mode'] == 'branches' and len(c['samples']) != 1:
        raise WorkflowError('0.6 branch concurrency requires exactly one sample; multi-species scheduling is deferred')
    if not isinstance(p['stages'], dict) or set(p['stages']) - (KINDS | set(graph(c))):
        raise WorkflowError('Unknown stage resource override')
    for name, r in p['stages'].items():
        if not isinstance(r, dict) or set(r) - {'threads','mem_mb','io'} or any(type(v) is not int or v < 1 for v in r.values()):
            raise WorkflowError('Invalid resource override: ' + name)
    for name in ['prepared', *graph(c)]:
        r = stage_resources(c, name)
        if r['threads'] > c['execution']['threads'] or r['mem_mb'] > c['execution']['mem_mb'] or r['io'] > p['io_slots']:
            raise WorkflowError('Stage resource request exceeds pool: ' + name)
        if stage_kind(name) in ('repeatmasker','tetrimmer','heliano') and r['threads'] < 4 and c['execution']['mode'] == 'server':
            raise WorkflowError('Stage requires at least 4 threads for RepeatMasker: ' + name)


def pool_root(c):
    from pathlib import Path
    return Path(c['work_root']) / '.teflow-runtime'


def resource_plan(c):
    from .branches import graph
    return dict(scope='single_species_branches' if policy(c)['mode']=='branches' else 'legacy_serial',
                policy=policy(c), pool=dict(threads=c['execution']['threads'], mem_mb=c['execution']['mem_mb']),
                stages={s:stage_resources(c,s) for s in ['prepared', *graph(c)]},
                cpu_affinity=cpu_affinity_plan(c), enforcement='observe_only', memory_guarantee=False,
                note='Memory requests govern admission, not allocation limits; sampled RSS can miss short peaks and double-count shared pages')


def cpu_affinity_plan(c):
    import os
    available = sorted(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else None
    requested = c['execution']['threads']
    return dict(available_cpu_ids=available,
                planned_pool_cpu_ids=available[:requested] if available is not None and len(available) >= requested else None,
                requested_threads=requested,
                budget_fits_inherited_affinity=len(available) >= requested if available is not None else None,
                cross_project_exclusivity=False,
                note='Inherits taskset/Slurm affinity; selects the lowest available IDs. Separate work roots do not coordinate CPU reservations. Use disjoint inherited CPU sets for simultaneous projects.')


def stage_context(c, sid, stage, cores=None):
    from pathlib import Path
    from .resource_pool import Lease
    p, r = policy(c), stage_resources(c,stage)
    if cores is not None and cores != r['threads']:
        raise WorkflowError('Stage threads must match the frozen resource plan (scheduler scaling is not allowed)')
    return Lease(pool_root(c), Path(c['work_root'])/c['run_id']/sid/'.runtime'/stage,
                 dict(threads=c['execution']['threads'], mem_mb=c['execution']['mem_mb'],
                      jobs=p['max_jobs'], io=p['io_slots']), r, p,
                 dict(run_id=c['run_id'], sample=sid, stage=stage))
