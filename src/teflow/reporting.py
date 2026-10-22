"""Read-only run views. Reports never freeze, dispatch, select or merge libraries."""
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import sys
from . import __version__
from .branches import graph, enabled, BRANCHES
from .common import WorkflowError, now, read_json, write_json, table, work, results


def latest_launch(c):
    paths = list((Path(c['work_root'])/c['run_id']/'launches').glob('*.json'))
    if not paths:
        return None
    path = max(paths, key=lambda p:p.stat().st_mtime_ns)
    rec = read_json(path)
    rec['receipt'] = str(path)
    if rec.get('status') in ('preflight','running','cancelling'):
        from .resource_pool import identity_alive
        alive = identity_alive(rec.get('owner', {})) if sys.platform == 'linux' else None
        rec['owner_alive'] = alive
        rec['observed_state'] = rec['status'] if alive else 'interrupted_review' if alive is False else 'owner_unverified'
    else:
        rec['observed_state'] = rec.get('status', 'legacy_dispatch_only')
    return rec


def preview(c, target=None):
    from .cli import run_status
    from .resources import resource_plan
    dag = graph(c)
    if target and target not in dag:
        raise WorkflowError('Target stage is not enabled: '+target)
    selected = set()
    def visit(name):
        if name in selected: return
        selected.add(name)
        for parent in dag[name]: visit(parent)
    visit(target or 'export')
    status = run_status(c)
    rows = [dict(sample=r['sample'], stage=r['stage'], state=r['status'],
                 action='existing_completion' if r['status'].startswith('complete') else
                        'new_work' if r['status']=='pending' else 'review_before_resume')
            for r in status['stages'] if r['stage'] in selected]
    return dict(run_id=c['run_id'], target_stage=target, stages=rows,
                counts=dict(Counter(r['action'] for r in rows)),
                preparation=[dict(sample=s['id'], manifest_exists=(work(c,s['id'])/'prepared/manifest.json').exists())
                             for s in c['samples']],
                read_only=True, output_imported=False, resources=resource_plan(c),
                note='Metadata view, not a cache promise. run freezes/verifies inputs and artifacts before reuse. A fork imports no outputs.')


def runtime_summary(c):
    rows, events = [], []
    for sample in c['samples']:
        for path in sorted((work(c,sample['id'])/'.runtime').glob('*/*/status.json')):
            rec = read_json(path)
            count = descendants = max_processes = 0
            first = last = None
            gap = 0.0
            metrics = path.with_name('metrics.jsonl')
            incomplete = False
            if metrics.exists():
                with metrics.open(encoding='utf-8') as f:
                    for line in f:
                        try:
                            obs = json.loads(line)
                            stamp = datetime.fromisoformat(obs['at']).timestamp()
                        except (ValueError, KeyError):
                            incomplete = True
                            continue
                        if last is not None: gap = max(gap, stamp-last)
                        first = stamp if first is None else first
                        last = stamp
                        count += 1
                        n = obs.get('processes', 0)
                        descendants += int(n > 1)
                        max_processes = max(max_processes, n)
            quality = 'no_samples' if not count else 'initial_only' if count == 1 else 'parent_only' if not descendants else 'descendants_observed'
            row = dict(sample=sample['id'], stage=path.parent.parent.name, attempt=path.parent.name,
                       phase=rec['phase'], elapsed_seconds=rec.get('elapsed_seconds'),
                       sampled_rss_peak_bytes=rec.get('rss_peak_bytes'), samples=count,
                       descendant_samples=descendants, max_processes=max_processes,
                       max_sample_gap_seconds=gap, quality=quality, metrics_incomplete=incomplete,
                       monitor_error=rec.get('monitor_error'), cpu_ids=rec.get('cpu_ids',[]),
                       request=rec.get('request',{}), source=str(path))
            rows.append(row)
            if first is not None and last > first:
                events += [(first, 1), (last, -1)]
    active = peak = 0
    overlap = 0.0
    previous = None
    for at, delta in sorted(events):
        if previous is not None and active >= 2: overlap += at-previous
        active += delta
        peak = max(peak, active)
        previous = at
    return dict(attempts=rows, sampled_stage_overlap_seconds=overlap, max_observed_stage_intervals=peak,
                enforcement='observe_only', exact_memory_peak=False,
                note='Intervals span first-to-last samples; they are not command timing or speedup measurements. RSS may double-count shared pages and miss peaks. Parent-only rows do not measure tool memory.')


def log_view(c, sample=None, stage=None, lines=40):
    if not 1 <= lines <= 1000: raise WorkflowError('--lines must be between 1 and 1000')
    if stage:
        if stage not in graph(c) and stage != 'prepared': raise WorkflowError('Unknown/disabled stage')
        ids = [s['id'] for s in c['samples']]
        if sample is None and len(ids) == 1: sample = ids[0]
        if sample not in ids: raise WorkflowError('Select a configured --sample')
        paths = sorted((work(c,sample)/stage).glob('*.log'))
    else:
        launch = latest_launch(c)
        paths = [Path(launch['scheduler_log'])] if launch and launch.get('scheduler_log') else []
    data = []
    for path in paths:
        if not path.is_file(): continue
        with path.open('rb') as f:
            size = path.stat().st_size
            if size > 131072: f.seek(-131072, 2)
            raw = f.read().decode('utf-8',errors='replace')
        data.append(dict(path=str(path), tail='\n'.join(raw.splitlines()[-lines:]), byte_limit=131072))
    return dict(logs=data, note='Read-only bounded tails. Without --stage, shows the latest supervised scheduler log.')


def report(c, output):
    from .cli import run_status
    target = Path(output).resolve()
    if target.exists(): raise WorkflowError('Report requires a new output directory')
    for key in ('work_root','results_root'):
        if target.is_relative_to((Path(c[key])/c['run_id']).resolve()):
            raise WorkflowError('Report output must be outside the source run')
    state = run_status(c)
    runtime = runtime_summary(c)
    branches, inputs, retention = [], [], []
    def optional(path):
        if not path.is_file(): return None
        inputs.append(dict(path=str(path), size=path.stat().st_size, mtime_ns=path.stat().st_mtime_ns))
        return read_json(path)
    for s in c['samples']:
        if {'edta','edta_tetrimmer'} <= set(enabled(c)):
            from .delivery import retention_summary
            retention.append(dict(sample=s['id'], **retention_summary(c,s['id'])))
            inputs.extend(retention[-1]['sources'])
        comparison = optional(results(c,s['id'])/'comparison.json') or {}
        coverage = {r['branch']:r for r in comparison.get('coverage_layers',[])}
        for name in enabled(c):
            lib, _, _ = BRANCHES[name]
            librec = optional(work(c,s['id'])/lib/'complete.json') or {}
            qc = optional(results(c,s['id'])/name/'qc.json') or {}
            audit = optional(work(c,s['id'])/'tetrimmer/upstream/teflow_audit.json') if name == 'edta_tetrimmer' else None
            branches.append(dict(sample=s['id'], branch=name,
                export_available=(results(c,s['id'])/name/'manifest.json').is_file(),
                library_details=librec.get('details'), coverage=coverage.get(name), qc=qc,
                tetrimmer_retained_origins=(audit or {}).get('retained_origins'),
                interpretation='Descriptive evidence; no automatic best library'))
    result = dict(schema_version=1, created=now(), teflow_version=__version__, run_id=c['run_id'],
                  snapshot=True, stage_status=state, launcher=latest_launch(c), runtime=runtime,
                  branches=branches, selected_branch=None, accuracy_claim=False,
                  sources=inputs, edta_tetrimmer_retention=retention, old_results_modified=False,
                  limitations=['Receipt completion is not biological accuracy.',
                    'EDTA and TEtrimmer exports remain separate; fallback sequences are not refined consensuses.',
                    'Coverage differences between runs with different discovered libraries cannot establish a parallelism effect.',
                    'Memory is observed, not hard limited; no resource defaults are adjusted from this report.',
                    'A live run can change while a snapshot is read; historical paths may be unavailable on another host.'])
    if any(not Path(r['path']).is_file() or Path(r['path']).stat().st_mtime_ns != r['mtime_ns'] for r in inputs):
        raise WorkflowError('Source summary changed while reporting; retry in a new directory')
    target.mkdir(parents=True, exist_ok=False)
    write_json(target/'report.json',result)
    table(target/'stages.tsv', [dict(sample=r['sample'],stage=r['stage'],status=r['status']) for r in state['stages']],
          ['sample','stage','status'])
    fields = ['sample','stage','attempt','phase','elapsed_seconds','sampled_rss_peak_bytes','samples',
              'descendant_samples','max_processes','max_sample_gap_seconds','quality','metrics_incomplete','monitor_error']
    table(target/'runtime.tsv', runtime['attempts'], fields)
    lines = [f"# TEflow {c['run_id']} — run report", '', f"Generated: {result['created']}", '',
             f"Artifact status: **{state['status']}** (existence/metadata only).",
             f"Launcher: **{(result['launcher'] or {}).get('observed_state','legacy / no supervised receipt')}**.", '',
             '| Sample | Branch | Export | Classified TE / genome | TEtrimmer sequence origins |',
             '|---|---|---|---|---|']
    for row in branches:
        pct = (row['coverage'] or {}).get('te_fraction_of_genome')
        lines.append('| '+ ' | '.join([row['sample'],row['branch'],str(row['export_available']),
                     f'{pct:.2%}' if pct is not None else 'not available',
                     json.dumps(row['tetrimmer_retained_origins'],ensure_ascii=False) if row['tetrimmer_retained_origins'] else 'not available'])+' |')
    lines += ['', 'No library is selected automatically.', '',
              f"Runtime attempts: {len(runtime['attempts'])}; sampled stage overlap: {runtime['sampled_stage_overlap_seconds']:.2f} seconds.",
              runtime['note'], '', 'Review `runtime.tsv` for sample counts, parent-only observations and monitor errors.', '']
    for r in retention:
        lines += [f"ET lineage ({r['sample']}): {r['retained_unique_parents']} retained unique E parents / {r['input_families']} inputs; {r['missing_parent_families']} without retained descendants.",
                  f"E classified-TE coverage of missing parents: {r['missing_family_te_coverage_bp']} bp; exclusive of retained-parent E hits: {r['missing_family_exclusive_te_coverage_bp']} bp. None means unavailable.", r['interpretation'], '']
    lines += ['- '+value for value in result['limitations']]
    (target/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return dict(status='REPORT_WRITTEN', output=str(target), report=str(target/'report.md'),
                artifact_status=state['status'], old_results_modified=False)
