"""Explicit downstream choices and descriptive EDTA/TEtrimmer lineage."""
import csv
import os
from pathlib import Path
import shutil
from . import __version__
from .branches import enabled
from .common import WorkflowError, file_stamp, now, read_json, write_json, results, work
from .evaluation import bp, subtract
from .publishing import atomic_directory


def retention_summary(c, sid):
    out, base = results(c, sid), work(c, sid)
    def first(*paths):
        return next((p for p in paths if p.is_file()), None)
    library = first(out/'edta/family_provenance.tsv', base/'edta/library.fa.provenance.tsv')
    parents = first(out/'edta_tetrimmer/parents.tsv', base/'tetrimmer/upstream/teflow_parent_map.tsv')
    answer = dict(status='unavailable', input_families=None, retained_unique_parents=None,
                  missing_parent_families=None, missing_family_te_coverage_bp=None,
                  missing_family_exclusive_te_coverage_bp=None, sources=[],
                  interpretation='Coverage refers to E annotations of parents without retained ET descendants. It is not E-minus-ET genomic coverage or an accuracy estimate.')
    def rows(path):
        stamp = file_stamp(path)
        with path.open(encoding='utf-8') as f:
            yield from csv.DictReader(f, delimiter='\t')
        if file_stamp(path) != stamp:
            raise WorkflowError('Lineage source changed while reading: ' + str(path))
        answer['sources'].append(dict(path=str(path), **stamp))
    if library is None or parents is None:
        answer['reason'] = 'EDTA provenance and retained ET parent map are required'
        return answer
    all_ids = {r['family_id'] for r in rows(library)}
    retained = set()
    for r in rows(parents):
        if 'parent_branch' in r:
            if r['parent_branch'] == 'edta': retained.add(r['parent_family_id'])
        else:
            retained.add(r['input_name'])
    if retained - all_ids:
        raise WorkflowError('ET parent map contains IDs absent from the corresponding E library')
    missing = all_ids - retained
    answer.update(status='counts_only', input_families=len(all_ids), retained_unique_parents=len(retained),
                  missing_parent_families=len(missing))
    masks = out/'edta/mask_sources.tsv'
    if not masks.is_file():
        answer['reason'] = 'E mask_sources.tsv unavailable; missing-parent coverage is unknown'
        return answer
    lost_hits, kept_hits = [], []
    for r in rows(masks):
        if r['family_id'] not in all_ids:
            raise WorkflowError('E annotation family absent from its provenance')
        if r['tier'] != 'te': continue
        target = lost_hits if r['family_id'] in missing else kept_hits
        target.append((r['seqid'], int(r['start']), int(r['end'])))
    answer.update(status='computed', missing_family_te_coverage_bp=bp(lost_hits),
                  missing_family_exclusive_te_coverage_bp=bp(subtract(lost_hits, kept_hits)))
    return answer


def select(c, output, branch, policy, sample=None, mode='symlink', reason='Explicit user selection'):
    from .cli import run_status
    ids = [s['id'] for s in c['samples']]
    if sample is None and len(ids) == 1: sample = ids[0]
    if sample not in ids or branch not in enabled(c):
        raise WorkflowError('Select a configured sample and enabled branch')
    if policy not in ('te_primary', 'all_interspersed') or mode not in ('symlink', 'copy'):
        raise WorkflowError('Unsupported selection policy or delivery mode')
    target = Path(output).resolve()
    for root in ('work_root', 'results_root'):
        if target.is_relative_to((Path(c[root])/c['run_id']).resolve()):
            raise WorkflowError('Selection output must be outside the source run')
    status = run_status(c)
    stage = next(r for r in status['stages'] if r['sample'] == sample and r['stage'] == 'export_' + branch)
    if not stage['status'].startswith('complete'):
        raise WorkflowError('Selected branch export is not complete and verified: ' + stage['status'])
    source = results(c, sample)/branch
    manifest = source/'manifest.json'
    stamp = file_stamp(manifest)
    declared = read_json(manifest)
    fasta = 'genome.softmasked.fa' if policy == 'te_primary' else 'genome.softmasked.all_interspersed.fa'
    mask = 'repeat.mask.bed' if policy == 'te_primary' else 'repeat.mask.all_interspersed.bed'
    selected = {'genome.softmasked.fa': fasta, 'repeat.mask.bed': mask,
                'library.fa': 'library.fa', 'te_fragments.gff3': 'te_fragments.gff3',
                'family_provenance.tsv': 'family_provenance.tsv', 'mask_sources.tsv': 'mask_sources.tsv',
                'source_manifest.json': 'manifest.json'}
    for name in ('parents.tsv', 'native_sites.tsv', 'native_sites.schema.json'):
        if name in declared['outputs']: selected[name] = name
    sources = {}
    for name, rel in selected.items():
        path = source/rel
        if not path.is_file() or not path.resolve().is_relative_to(source.resolve()):
            raise WorkflowError('Selected artifact missing or outside branch: '+str(path))
        if rel != 'manifest.json' and rel not in declared['outputs']:
            raise WorkflowError('Selected artifact is not registered by its export: '+rel)
        sources[name] = dict(path=str(path.resolve()), **file_stamp(path))
    if file_stamp(manifest) != stamp:
        raise WorkflowError('Source manifest changed while selecting')
    receipt = dict(schema_version=1, created=now(), teflow_version=__version__, run_id=c['run_id'],
                   sample=sample, branch=branch, mask_policy=policy, mode=mode, reason=reason,
                   automatic_selection=False, source_validation='completed_stage_existence_and_metadata',
                   source_manifest_identity=stamp, sources=sources,
                   scope='Explicit delivery choice, not a biological quality ranking. GFF3 contains homology fragments, not complete insertions.')
    with atomic_directory(target) as pending:
        for name, rec in sources.items():
            path = Path(rec['path'])
            if mode == 'copy': shutil.copyfile(path, pending/name)
            else:
                try: (pending/name).symlink_to(os.path.relpath(path, target))
                except OSError as exc: raise WorkflowError('Cannot create delivery links; choose --mode copy: '+str(exc)) from exc
            if file_stamp(path) != {k:rec[k] for k in ('size','mtime_ns','ctime_ns','device','inode')}:
                raise WorkflowError('Source changed while creating delivery: '+str(path))
        for rec in sources.values():
            if file_stamp(rec['path']) != {k:rec[k] for k in ('size','mtime_ns','ctime_ns','device','inode')}:
                raise WorkflowError('Source changed before publishing selection: '+rec['path'])
        write_json(pending/'selection.json', receipt)
        notes = [f'# TEflow selected delivery: {sample}', '', f'Branch: **{branch}**; masking: **{policy}**; mode: **{mode}**.', '',
                 reason, '', 'Use `genome.softmasked.fa` with the documented requirements of your gene-annotation pipeline.',
                 '`library.fa` can be registered as a reference library in a new run. `te_fragments.gff3` is fragment-level evidence.',
                 'The mask includes classified TE, tandem repeats and DUST' + (' plus Unknown.' if policy == 'all_interspersed' else '; Unknown is excluded.'),
                 'This is an explicit choice, not automatic selection of the best library.',
                 'Links depend on the original results remaining available; use copy mode for a portable delivery.']
        if branch == 'edta_tetrimmer':
            notes.append('ET can omit many input families and contains original-input fallbacks. Do not assume it is a complete replacement for E.')
        (pending/'SELECTION.md').write_text('\n\n'.join(notes)+'\n', encoding='utf-8')
    return dict(status='SELECTION_WRITTEN', output=str(target), branch=branch, mask_policy=policy, mode=mode, source_results_modified=False)
