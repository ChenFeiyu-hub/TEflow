"""Bounded, explicitly selected locus comparisons using BLASTn and optional MAFFT.

No discovery, automatic boundary pairing, TE classification or masking decisions.
Coordinates in all derived tables are zero-based half-open. Aligned bases are
counted, never the span of a collection of HSPs or a forced MSA envelope.
"""
from collections import defaultdict
import math
from pathlib import Path
import shutil
import sys
import tarfile

from .common import (WorkflowError, ID, digest, fasta, fasta_write_record, now,
                     read_json, sha256, table, write_json)
from .evaluation import tsv, bp, intersect
from .formats import dust_fasta
from .library_qc import revcomp
from .repeat_alignments import Genome
from .review_context import annotation_models
from .runtime import run

FIELDS = 'qseqid sseqid pident length mismatch gapopen qstart qend sstart send evalue bitscore qlen slen qseq sseq'.split()
REQUIRED = 'locus_id group_id seqid start end strand role reason'.split()
SCOPE = ('Selected-locus homology evidence only; candidates were selected before this comparison. '
         'Coverage is not proof of a complete insertion, independence, or TE identity; '
         'absence of a reported HSP is not absence of homology. No annotation/library decisions.')


def code_identity():
    root = Path(__file__).resolve().parent
    return digest({p.name: sha256(p) for p in sorted(root.glob('*.py'))})


def _seal(path, material, files):
    record = dict(material=material, files=files)
    record['fingerprint'] = digest(record)
    write_json(path, record)
    return record


def _verify(root, name):
    root = Path(root).resolve()
    record = read_json(root / name)
    if record.get('fingerprint') != digest({k: v for k, v in record.items() if k != 'fingerprint'}):
        raise WorkflowError('Boundary receipt fingerprint changed: ' + name)
    for name, expected in record['files'].items():
        p = root / name
        if p.is_symlink() or not p.resolve().is_relative_to(root) or not p.is_file() or sha256(p) != expected:
            raise WorkflowError('Boundary evidence changed/missing: ' + name)
    return record


def _files(root):
    return {p.relative_to(root).as_posix(): sha256(p) for p in sorted(root.rglob('*')) if p.is_file()}


def prepare(genome, loci, output, annotation=None, flank=500, terminal=100, tools=None,
            msa_groups=(), evidence=(), dust_sensitivity=False):
    """Freeze a small explicit locus table and extracted DNA; no external tools."""
    root = Path(output).resolve()
    if root.exists(): raise WorkflowError('Boundary output directory exists: ' + str(root))
    if not 0 <= flank <= 10000 or not 1 <= terminal <= 1000:
        raise WorkflowError('Flank must be 0..10000 and terminal summary width 1..1000')
    genome, loci = Path(genome).resolve(), Path(loci).resolve()
    paths = [genome, loci] + ([Path(annotation).resolve()] if annotation else []) + [Path(p).resolve() for p in evidence]
    inputs = [dict(path=str(p), sha256=sha256(p), bytes=p.stat().st_size) for p in paths]
    rows = tsv(loci)
    if not 1 <= len(rows) <= 100 or not all(set(REQUIRED) <= r.keys() for r in rows):
        raise WorkflowError('Supply 1..100 loci with columns: ' + ', '.join(REQUIRED))
    g = Genome(genome)
    groups, ids, total = defaultdict(list), set(), 0
    for r in rows:
        for key in ('locus_id', 'group_id'):
            if not ID.fullmatch(r[key]): raise WorkflowError('Unsafe/invalid locus or group ID')
        if r['locus_id'] in ids: raise WorkflowError('Duplicate locus ID')
        ids.add(r['locus_id'])
        try: a, b = int(r['start']), int(r['end'])
        except ValueError as e: raise WorkflowError('Noninteger locus coordinates') from e
        c = r['seqid']
        if c not in g.lengths or not 0 <= a < b <= g.lengths[c] or r['strand'] not in ('+', '-'):
            raise WorkflowError('Invalid locus coordinates/strand: ' + r['locus_id'])
        if b-a > 100000 or r['role'] not in ('reference', 'candidate', 'control') or not r['reason'].strip():
            raise WorkflowError('Locus requires <=100 kb, explicit role and selection reason')
        lo, hi = max(0, a-flank), min(g.lengths[c], b+flank)
        cs = a-lo if r['strand'] == '+' else hi-b
        r.update(start=a, end=b, extracted_start=lo, extracted_end=hi,
                 core_start=cs, core_end=cs+b-a, length=b-a, sequence_length=hi-lo)
        groups[r['group_id']].append(r); total += hi-lo
    if total > 5000000: raise WorkflowError('Selected sequence budget exceeds 5 Mb')
    for name, group in groups.items():
        if len(group) < 2 or sum(r['role'] == 'reference' for r in group) != 1:
            raise WorkflowError('Every group needs one reference and at least one other locus: ' + name)
    if set(msa_groups) - groups.keys(): raise WorkflowError('Unknown MAFFT group')
    for name in msa_groups:
        if max(r['length'] for r in groups[name]) > 5000 or len(groups[name]) > 20:
            raise WorkflowError('Optional MAFFT is limited to <=20 core sequences of <=5 kb per group')
    tools = tools or dict(blastn=dict(command=['blastn'], expected_version=None),
                          mafft=dict(command=['mafft'], expected_version=None))
    for tool in ['blastn'] + (['mafft'] if msa_groups else []) + (['dustmasker'] if 'dustmasker' in tools else []):
        cmd = tools.get(tool, {}).get('command')
        if not isinstance(cmd, list) or not cmd or any(not isinstance(x, str) or not x for x in cmd):
            raise WorkflowError('Tool command must be a nonempty argv list: ' + tool)
    model = annotation_models(annotation, g) if annotation else None
    root.mkdir(parents=True)
    shutil.copyfile(loci, root / 'selection.tsv')
    gene_rows, cds_rows, group_records = [], [], []
    for i, (name, group) in enumerate(groups.items(), 1):
        folder = root / f'group{i:03d}'; folder.mkdir()
        with (folder / 'subjects.fa').open('w', encoding='ascii', newline='\n') as full, \
             (folder / 'cores.fa').open('w', encoding='ascii', newline='\n') as cores, \
             (folder / 'reference.fa').open('w', encoding='ascii', newline='\n') as ref:
            for r in group:
                seq = g[r['seqid']][r['extracted_start']:r['extracted_end']].upper()
                if r['strand'] == '-': seq = revcomp(seq)
                core = seq[r['core_start']:r['core_end']]
                r['N_bp'] = core.count('N')
                r['overlapping_CDS_union_bp'] = ''
                r['annotation_status'] = 'not_provided'
                fasta_write_record(full, r['locus_id'], seq)
                fasta_write_record(cores, r['locus_id'], core)
                if r['role'] == 'reference': fasta_write_record(ref, r['locus_id'], seq)
                if model:
                    span = [(r['seqid'], r['start'], r['end'])]
                    coding = []
                    for gid, gene in model['genes'].items():
                        if gene['seqid'] != r['seqid'] or gene['start'] >= r['end'] or gene['end'] <= r['start']: continue
                        ov = intersect(span, model['cds'].get(gid, [])); coding += ov
                        gene_rows.append(dict(locus_id=r['locus_id'], group_id=name, **gene, CDS_overlap_bp=bp(ov)))
                        for c, a, b in ov:
                            x, y = (a-r['extracted_start'], b-r['extracted_start']) if r['strand'] == '+' else (r['extracted_end']-b, r['extracted_end']-a)
                            cds_rows.append(dict(locus_id=r['locus_id'], gene_id=gid, start=x, end=y))
                    r['overlapping_CDS_union_bp'] = bp(coding)
                    r['annotation_status'] = 'provided_descriptive_only'
        group_records.append(dict(group_id=name, folder=folder.name, reference=next(r['locus_id'] for r in group if r['role']=='reference'),
                                  records=len(group), mafft=name in msa_groups))
    table(root / 'loci.tsv', rows, REQUIRED + ['extracted_start', 'extracted_end', 'core_start', 'core_end', 'length',
          'sequence_length', 'N_bp', 'overlapping_CDS_union_bp', 'annotation_status'])
    table(root / 'genes.tsv', gene_rows, ['locus_id', 'group_id', 'gene_id', 'seqid', 'start', 'end', 'strand', 'biotype', 'CDS_overlap_bp'])
    table(root / 'cds_oriented.tsv', cds_rows, ['locus_id', 'gene_id', 'start', 'end'])
    # Detect inputs edited during extraction before issuing a prepared receipt.
    if any(sha256(p['path']) != p['sha256'] for p in inputs): raise WorkflowError('Input changed during boundary preparation')
    m = dict(created=now(), inputs=inputs, groups=group_records, tools=tools, source_code=code_identity(),
             flank=flank, terminal_summary_width=terminal, scope=SCOPE,
             dust_sensitivity=bool(dust_sensitivity),
             coordinate_system='0-based half-open; FASTA oriented to declared locus strand',
             sequences='Unmasked reference genome, uppercased; not masked library consensuses',
             source_inputs_needed_after_preparation=False)
    record = _seal(root / 'boundary.json', m, _files(root))
    return dict(status='prepared', output=str(root), fingerprint=record['fingerprint'], loci=len(rows), extracted_bp=total)


def plan(review, threads=1):
    root = Path(review).resolve(); rec = _verify(root, 'boundary.json'); m = rec['material']
    if m['source_code'] != code_identity(): raise WorkflowError('Boundary implementation changed; prepare a new review')
    if not 1 <= threads <= 8: raise WorkflowError('Boundary threads must be 1..8')
    out = root / 'alignments'; tools = m['tools']
    commands = [dict(name='blastn.version', argv=tools['blastn']['command']+['-version'], tool='blastn')]
    if any(g['mafft'] for g in m['groups']): commands.append(dict(name='mafft.version', argv=tools['mafft']['command']+['--version'], tool='mafft'))
    if 'dustmasker' in tools: commands.append(dict(name='dustmasker.version', argv=tools['dustmasker']['command']+['-version-full'], tool='dustmasker'))
    for g in m['groups']:
        folder = root / g['folder']
        commands.append(dict(name=g['folder']+'.blastn', group=g['group_id'], argv=tools['blastn']['command']+[
            '-task', 'blastn', '-query', str(folder/'reference.fa'), '-subject', str(folder/'subjects.fa'),
            '-out', str(out/(g['folder']+'.blast.tsv')), '-word_size', '11', '-evalue', '1e-5',
            '-dust', 'yes', '-soft_masking', 'true', '-max_target_seqs', str(g['records']),
            '-num_threads', str(threads), '-outfmt', '6 '+' '.join(FIELDS)]))
        if m.get('dust_sensitivity'):
            argv=list(commands[-1]['argv']); argv[argv.index('-dust')+1]='no'
            argv[argv.index('-out')+1]=str(out/(g['folder']+'.nodust.blast.tsv'))
            commands.append(dict(name=g['folder']+'.nodust.blastn',group=g['group_id'],argv=argv))
        if 'dustmasker' in tools:
            commands.append(dict(name=g['folder']+'.dustmasker',group=g['group_id'],argv=tools['dustmasker']['command']+[
                '-in',str(folder/'subjects.fa'),'-out',str(out/(g['folder']+'.dust.fa')),
                '-outfmt','fasta','-window','64','-level','20','-linker','1']))
        if g['mafft']:
            commands.append(dict(name=g['folder']+'.mafft', group=g['group_id'], argv=[sys.executable, '-m', 'teflow.boundary_mafft',
                str(out/(g['folder']+'.msa.fa'))]+tools['mafft']['command']+[
                '--thread', '1', '--localpair', '--maxiterate', '1000', str(folder/'cores.fa')]))
    return dict(status='plan_verified', computation_launched=False, review=str(root), threads=threads,
                prepared_fingerprint=rec['fingerprint'], commands=commands, scope=SCOPE)


def _pos(a, b):
    return list(range(a-1, b)) if a <= b else list(range(a-1, b-2, -1))


def read_hsps(path, queries, subjects):
    """Validate every reported base, coordinate, length, identity and gap count."""
    with Path(path).open(encoding='ascii') as f:
        for line_no, line in enumerate(f, 1):
            fields = line.rstrip('\n').split('\t')
            if len(fields) != len(FIELDS): raise WorkflowError(f'Invalid BLAST field count at line {line_no}')
            r = dict(zip(FIELDS, fields))
            try:
                for k in ('length', 'mismatch', 'gapopen', 'qstart', 'qend', 'sstart', 'send', 'qlen', 'slen'): r[k] = int(r[k])
                for k in ('pident', 'evalue', 'bitscore'): r[k] = float(r[k])
                q, s = queries[r['qseqid']], subjects[r['sseqid']]
            except (ValueError, KeyError) as e: raise WorkflowError('Invalid BLAST value/ID') from e
            if any(not math.isfinite(r[k]) for k in ('pident', 'evalue', 'bitscore')) or r['evalue'] < 0:
                raise WorkflowError('Nonfinite/negative BLAST score')
            if r['qlen'] != len(q) or r['slen'] != len(s) or not all(1<=r[k]<=len(seq) for seq,keys in ((q,('qstart','qend')),(s,('sstart','send'))) for k in keys):
                raise WorkflowError('BLAST coordinates/length disagree with frozen sequences')
            qp, sp = _pos(r['qstart'], r['qend']), _pos(r['sstart'], r['send'])
            qs, ss = r['qseq'].upper(), r['sseq'].upper()
            if len(qs) != r['length'] or len(ss) != r['length'] or not r['length'] or any(x==y=='-' for x,y in zip(qs,ss)):
                raise WorkflowError('BLAST alignment columns invalid')
            expected_q = q[min(qp):max(qp)+1]; expected_s = s[min(sp):max(sp)+1]
            if r['qstart'] > r['qend']: expected_q = revcomp(expected_q)
            if r['sstart'] > r['send']: expected_s = revcomp(expected_s)
            if qs.replace('-', '') != expected_q.upper() or ss.replace('-', '') != expected_s.upper():
                raise WorkflowError('BLAST aligned sequence does not match frozen FASTA')
            ident = sum(x==y for x,y in zip(qs,ss))
            mismatches = sum(x!=y and x!='-' and y!='-' for x,y in zip(qs,ss))
            gaps = sum(x=='-' and (i==0 or seq[i-1]!='-') for seq in (qs,ss) for i,x in enumerate(seq))
            if abs(100*ident/r['length']-r['pident']) > 0.0011 or mismatches != r['mismatch'] or gaps != r['gapopen']:
                raise WorkflowError('BLAST identity/mismatch/gap summary disagrees with columns')
            qi, si, pairs = iter(qp), iter(sp), []
            for x,y in zip(qs,ss):
                a = next(qi) if x!='-' else None; b = next(si) if y!='-' else None
                if a is not None and b is not None: pairs.append((a,b,x==y))
            r.update(hsp_id=line_no, pairs=pairs,
                     orientation='same' if (r['qend']>=r['qstart'])==(r['send']>=r['sstart']) else 'opposite')
            yield r


def _runs(values):
    out = []
    for v in sorted(values):
        if out and v == out[-1][1]: out[-1][1] += 1
        else: out.append([v, v+1])
    return out


def _region(p, row, width):
    a,b = int(row['core_start']), int(row['core_end'])
    w = min(width, (b-a)//2)
    return '5F' if p<a else '5I' if p<a+w else 'internal' if p<b-w else '3I' if p<b else '3F'


def analyze(root, out):
    rec = _verify(root, 'boundary.json'); m = rec['material']
    loci = {r['locus_id']: r for r in tsv(root/'loci.tsv')}
    summaries, hsps, regions, coverage = [], [], [], []
    comparisons=[dict(g,search_mode=mode) for g in m['groups'] for mode in (['dust','no_dust'] if m.get('dust_sensitivity') else ['dust'])]
    for group in comparisons:
        subjects = {k:v.upper() for k,v in fasta(root/group['folder']/'subjects.fa')}
        queries = {group['reference']: subjects[group['reference']]}
        by_subject = defaultdict(list)
        suffix='.nodust.blast.tsv' if group['search_mode']=='no_dust' else '.blast.tsv'
        for r in read_hsps(out/(group['folder']+suffix), queries, subjects):
            by_subject[r['sseqid']].append(r)
            h = {k:v for k,v in r.items() if k not in ('qseq','sseq','pairs')}
            hsps.append(dict(group_id=group['group_id'], search_mode=group['search_mode'], **h))
        for sid in subjects:
            qid = group['reference']; q, s = loci[qid], loci[sid]
            for ori in ('same','opposite'):
                hits = [r for r in by_subject[sid] if r['orientation']==ori]
                spans = defaultdict(set); cells = defaultdict(lambda: [set(), set()])
                for r in hits:
                    for a,b,ident in r['pairs']:
                        qr, sr = _region(a,q,m['terminal_summary_width']), _region(b,s,m['terminal_summary_width'])
                        cells[(qr,sr)][0].add(a); cells[(qr,sr)][1].add(b)
                        if int(q['core_start'])<=a<int(q['core_end']) and int(s['core_start'])<=b<int(s['core_end']):
                            spans['query_core'].add(a); spans['subject_core'].add(b)
                            if ident: spans['query_core_identical'].add(a); spans['subject_core_identical'].add(b)
                        if qr==sr=='internal':
                            spans['query_internal'].add(a); spans['subject_internal'].add(b)
                result = dict(group_id=group['group_id'], search_mode=group['search_mode'], reference=qid, subject=sid, role=s['role'], orientation=ori, HSPs=len(hits))
                for side, row in (('query',q),('subject',s)):
                    length=int(row['length']); internal=length-2*min(m['terminal_summary_width'],length//2)
                    for feature, denom in (('core',length),('internal',internal)):
                        n=len(spans[side+'_'+feature]); result[side+'_'+feature+'_paired_bp']=n
                        result[side+'_'+feature+'_fraction']=n/denom if denom else ''
                    result[side+'_core_identical_bp']=len(spans[side+'_core_identical'])
                # Overlapping/duplicated HSPs are unioned. This does not establish
                # collinearity, order or one continuous complete TE alignment.
                result['longest_single_HSP_query_core_paired_bp']=max((len({a for a,b,_ in r['pairs'] if int(q['core_start'])<=a<int(q['core_end']) and int(s['core_start'])<=b<int(s['core_end'])}) for r in hits), default=0)
                summaries.append(result)
                for (qr,sr),(a,b) in sorted(cells.items()):
                    regions.append(dict(group_id=group['group_id'],search_mode=group['search_mode'],reference=qid,subject=sid,orientation=ori,query_region=qr,
                                        subject_region=sr,query_paired_bp=len(a),subject_paired_bp=len(b)))
                for feature, values in spans.items():
                    for a,b in _runs(values): coverage.append(dict(group_id=group['group_id'],search_mode=group['search_mode'],reference=qid,subject=sid,orientation=ori,feature=feature,start=a,end=b))
        if group['mafft'] and group['search_mode']=='dust':
            validate_msa(out/(group['folder']+'.msa.fa'), dict(fasta(root/group['folder']/'cores.fa')))
    table(out/'pair_summary.tsv', summaries, list(summaries[0]))
    table(out/'verified_hsps.tsv', hsps, ['group_id','search_mode']+FIELDS[:-2]+['hsp_id','orientation'])
    table(out/'region_pairs.tsv', regions, ['group_id','search_mode','reference','subject','orientation','query_region','subject_region','query_paired_bp','subject_paired_bp'])
    table(out/'coverage_runs.tsv', coverage, ['group_id','search_mode','reference','subject','orientation','feature','start','end'])
    complexity=[]
    for group in m['groups']:
        seqs=dict(fasta(root/group['folder']/'subjects.fa'))
        mask=dust_fasta(out/(group['folder']+'.dust.fa'),root/group['folder']/'subjects.fa') if 'dustmasker' in m['tools'] else None
        for sid,seq in seqs.items():
            r=loci[sid]; a,b=int(r['core_start']),int(r['core_end']); w=min(m['terminal_summary_width'],(b-a)//2)
            core=seq[a:b].upper(); internal=(sid,a+w,b-w)
            complexity.append(dict(group_id=group['group_id'],locus_id=sid,role=r['role'],core_bp=b-a,
                core_GC_fraction=(core.count('G')+core.count('C'))/(b-a),core_AT_fraction=(core.count('A')+core.count('T'))/(b-a),
                DUST_status='provided' if mask is not None else 'not_run',core_DUST_bp=bp(intersect(mask,[(sid,a,b)])) if mask is not None else '',
                internal_bp=b-a-2*w,internal_DUST_bp=bp(intersect(mask,[internal])) if mask is not None and internal[1]<internal[2] else ''))
    table(out/'sequence_complexity.tsv',complexity,list(complexity[0]))
    self_controls={r['group_id']:r['query_core_fraction'] for r in summaries if r['role']=='reference' and r['orientation']=='same' and r['search_mode']=='dust'}
    return dict(HSPs=len(hsps), groups=len(m['groups']), loci=len(loci), source_bases_verified=True,
                primary_self_core_coverage=self_controls,
                self_control_status='all_full' if all(x==1.0 for x in self_controls.values()) else 'inspect_incomplete_self_hits',
                scope=SCOPE, coverage_definition='Union of actually paired alignment columns, separate orientation; not a collinear chain')


def validate_msa(path, originals):
    seqs, key = {}, None
    for raw in Path(path).read_text(encoding='ascii').splitlines():
        line=raw.strip()
        if not line: continue
        if line.startswith('>'):
            key=line[1:].split()[0]
            if key in seqs: raise WorkflowError('Duplicate MAFFT ID')
            seqs[key]=''
        elif key is None: raise WorkflowError('Malformed MAFFT FASTA')
        else: seqs[key]+=line.upper()
    if set(seqs)!=set(originals) or len({len(x) for x in seqs.values()})!=1:
        raise WorkflowError('MAFFT IDs/alignment lengths differ')
    if any(seqs[k].replace('-','')!=v.upper() for k,v in originals.items()):
        raise WorkflowError('MAFFT ungapped sequence differs from frozen input')
    return dict(sequences=len(seqs), columns=len(next(iter(seqs.values()))))


def execute(review, threads=1, timeout=3600):
    root=Path(review).resolve(); p=plan(root,threads); out=root/'alignments'
    if not 1<=timeout<=86400: raise WorkflowError('Timeout must be 1..86400 seconds')
    if out.exists(): raise WorkflowError('Boundary alignment directory exists; use a new review')
    out.mkdir()
    binaries={}
    for cmd in p['commands']:
        resolved=shutil.which(cmd['argv'][0])
        paths=([Path(resolved)] if resolved else [])+[Path(x) for x in cmd['argv'] if Path(x).is_file()]
        if '-p' in cmd['argv']:
            prefix=Path(cmd['argv'][cmd['argv'].index('-p')+1])
            paths+=list((prefix/'conda-meta').glob('*.json'))
            paths+=[prefix/'bin'/x for x in cmd['argv'] if '/' not in x and (prefix/'bin'/x).is_file()]
        for path in paths: binaries[str(path.resolve())]=sha256(path)
    write_json(out/'request.json', dict(p, created=now(), timeout=timeout, executable_and_environment_hashes=binaries))
    try:
        for cmd in p['commands']:
            text=run(cmd['argv'],out,out/(cmd['name']+'.log'),timeout=timeout,cpu_limit=threads)
            if cmd.get('tool'):
                expected=read_json(root/'boundary.json')['material']['tools'][cmd['tool']].get('expected_version')
                if expected and expected not in text: raise WorkflowError('Unexpected version: '+cmd['tool'])
        summary=analyze(root,out)
        if any(sha256(path)!=expected for path,expected in binaries.items()): raise WorkflowError('Tool/input changed during execution')
        rec=_seal(out/'complete.json', dict(created=now(),prepared_fingerprint=p['prepared_fingerprint'],summary=summary), _files(out))
        return dict(status='complete', fingerprint=rec['fingerprint'], summary=summary)
    except BaseException as e:
        write_json(out/'failed.json',dict(created=now(),error=str(e),prepared_fingerprint=p['prepared_fingerprint']))
        raise


def pack(review, output):
    root=Path(review).resolve(); record=_verify(root,'boundary.json')
    files=set(record['files'])|{'boundary.json'}
    if (root/'alignments/complete.json').exists():
        rec=_verify(root/'alignments','complete.json')
        if rec['material']['prepared_fingerprint']!=record['fingerprint']: raise WorkflowError('Boundary result belongs to another preparation')
        files|={'alignments/'+p for p in rec['files']}|{'alignments/complete.json'}
    elif (root/'alignments').exists():
        # Only bounded execution diagnostics on failure, not unverified output.
        files|={p.relative_to(root).as_posix() for p in (root/'alignments').glob('*') if p.is_file() and (p.name.endswith('.log') or p.suffix=='.json')}
    target=Path(output).resolve()
    if target.exists(): raise WorkflowError('Feedback destination exists')
    target.parent.mkdir(parents=True,exist_ok=True)
    with tarfile.open(target,'w:gz') as archive:
        for name in sorted(files):
            p=root/name
            if p.is_symlink() or not p.resolve().is_relative_to(root): raise WorkflowError('Unsafe feedback path')
            archive.add(p,arcname='boundary_review/'+name,recursive=False)
    return dict(archive=str(target),files=len(files),scope=SCOPE)
