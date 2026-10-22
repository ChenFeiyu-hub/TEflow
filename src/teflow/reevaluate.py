"""Offline evaluation of existing results. No executable or input genome is needed."""
from collections import Counter
import copy
from pathlib import Path
from . import __version__
from .branches import enabled, BRANCHES
from .classification import classify, MAPPING_VERSION
from .common import WorkflowError, now, read_json, write_json, table, results, work, fasta
from .evaluation import tsv, classification_inventory, prediction_tracks, bp, compare_branches
from .formats import rm_out


def file_record(path):
    p = Path(path).resolve()
    s = p.stat()
    return dict(path=str(p), bytes=s.st_size, mtime_ns=s.st_mtime_ns)


def audit_results(c, output):
    """Read raw RM files and libraries, retain bounded mismatch examples; no hard invariant."""
    target = Path(output).resolve()
    if target.exists(): raise WorkflowError('Audit output already exists: '+str(target))
    rows, vocab, inputs = [], Counter(), []
    rm_vocab = Counter()
    for s in c['samples']:
        base = work(c,s['id'])
        prep = read_json(base/'prepared/manifest.json')
        lengths = {r['alias']:r['length'] for r in prep['sequences'] if r['included']}
        for branch in enabled(c):
            libstage, rmstage, _ = BRANCHES[branch]
            library, rmfile = base/libstage/'library.fa', base/rmstage/'genome.fa.out'
            if not library.exists() or not rmfile.exists():
                rows.append(dict(sample=s['id'], branch=branch, status='not_available'))
                continue
            lib = {}
            for name, seq in fasta(library,allow_empty=True):
                family, _, raw = name.partition('#')
                vocab[raw or 'Unknown'] += 1
                lib[family] = len(seq)
            hits = rm_out(rmfile,lengths,lib,lib)
            rm_vocab.update(r['classification'] for r in hits)
            counts = Counter(r['consensus_coordinate_status'] for r in hits)
            examples = [r for r in hits if r['consensus_coordinate_status']!='verified'][:10]
            rows.append(dict(sample=s['id'],branch=branch,status='review_required' if examples else 'consistent',
                             fragments=len(hits), coordinates=dict(counts), examples=examples))
            inputs += [file_record(library),file_record(rmfile)]
    vocabulary = []
    for raw in sorted(vocab.keys() | rm_vocab.keys()):
        try: value = classify(raw)
        except WorkflowError as e: value = dict(mapping_status='unmapped_root',error=str(e))
        vocabulary.append(dict(raw_class=raw,library_occurrences=vocab[raw],rm_fragment_occurrences=rm_vocab[raw],**value))
    result = dict(status='audit_complete',created=now(),teflow_version=__version__,mapping_version=MAPPING_VERSION,
                  branches=rows,vocabulary=vocabulary,inputs=inputs,
                  annotation_changed=False,full_length_copy_claim=False,
                  note='Coordinate disagreements are diagnostics, not proof of invalid genome intervals or a tool failure; inspect source/library correspondence and raw alignments')
    write_json(target,result)
    return dict(status=result['status'], report=str(target),branches=rows,
                unmapped_roots=[r['raw_class'] for r in vocabulary if r['mapping_status']=='unmapped_root'])


def reevaluate(c, output):
    out = Path(output).resolve()
    if out.exists(): raise WorkflowError('Reevaluation requires a new directory: '+str(out))
    for key in ('work_root','results_root'):
        if out.is_relative_to((Path(c[key])/c['run_id']).resolve()):
            raise WorkflowError('Reevaluation output must be outside the original run')
    sources, preflight = [], []
    branches = enabled(c)
    for s in c['samples']:
        old, base = results(c,s['id']), work(c,s['id'])
        prepared = base/'prepared'
        if not (prepared/'manifest.json').is_file():
            raise WorkflowError('Prepared manifest required for original sequence coordinates: '+str(prepared))
        for b in branches:
            for name in ('library.fa','mask_sources.tsv','qc.json','te.mask.bed','repeat_unknown.bed',
                         'non_te.bed','tandem_repeat.bed','low_complexity.bed','repeat.mask.bed'):
                p = old/b/name
                if not p.is_file(): raise WorkflowError('Reevaluation needs completed branch export: '+str(p))
                preflight.append(file_record(p))
        preflight.append(file_record(prepared/'manifest.json'))
        sources.append((s,old,prepared))
    out.mkdir(parents=True)
    provenance = dict(status='running',created=now(),teflow_version=__version__,mapping_version=MAPPING_VERSION,
                      source_config=file_record(c['_config_path']),source_files=preflight,
                      source_run_id=c['run_id'],source_receipts={},old_results_modified=False,
                      scope='Genome-wide class inventory, regional class totals, coverage unions and pairwise differences',
                      omitted='No discovery, RepeatMasker, FASTA generation, promoter scan, reference reranking or automatic library choice',
                      identity_note='Source file sizes/timestamps recorded; no checksum validation step')
    for s,old,prepared in sources:
        manifest = Path(c['work_root'])/c['run_id']/'run_manifest.json'
        if manifest.exists():
            provenance['source_receipts'][s['id']] = read_json(manifest).get('fingerprint')
    write_json(out/'reevaluation.json',provenance)
    try:
        rc = copy.deepcopy(c)
        rc['evaluation'] = {**rc.get('evaluation',{}),'promoter_analysis':False}
        for s,old,prepared in sources:
            dest = out/s['id']; dest.mkdir()
            for b in branches:
                folder = dest/b; folder.mkdir()
                fragments = tsv(old/b/'mask_sources.tsv')
                classification_inventory(old/b/'library.fa',fragments,folder/'classification_inventory.tsv')
                tracks = prediction_tracks(fragments)
                table(folder/'regional_evaluation.tsv',
                      [dict(region='genome',category=k,predicted_bp=bp(v)) for k,v in sorted(tracks.items())],
                      ['region','category','predicted_bp'])
            compare_branches(rc,s,prepared,dest,branches,sources=old)
        # File stat change while reading invalidates the report, without changing its sources.
        if any(file_record(r['path']) != r for r in preflight):
            raise WorkflowError('A source file changed while reevaluating; retain this failed report and repeat in a new directory')
        provenance.update(status='complete',finished=now())
    except BaseException as e:
        provenance.update(status='failed',error=str(e))
        write_json(out/'reevaluation.json',provenance)
        raise
    write_json(out/'reevaluation.json',provenance)
    return dict(status='complete',output=str(out),mapping_version=MAPPING_VERSION,old_results_modified=False)
