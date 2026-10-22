"""Strict adapters for upstream outputs and coordinate-only masking."""
from __future__ import annotations
import collections
import csv
import hashlib
import html
import re
from pathlib import Path
from urllib.parse import quote
from .common import WorkflowError, fasta, fasta_write_record, table, write_json, read_json, sha256


def canonical_library(source, output, prefix, source_tool):
    rows = []
    source_hash = sha256(source)
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="ascii", newline="\n") as f:
        for i, (name, seq) in enumerate(fasta(source, allow_empty=True), 1):
            fields = name.split("#")
            cls = fields[1] if len(fields) > 1 else "Unknown"
            if not re.fullmatch(r"[A-Za-z0-9_./?-]+", cls):
                raise WorkflowError("Unsupported upstream class in FASTA header: " + name)
            # Fail at library creation, before an expensive whole-genome search.
            from .classification import classify
            classify(cls)
            alias = f"{prefix}{i:07d}"
            seq = seq.upper()
            fasta_write_record(f, alias + "#" + cls, seq)
            rows.append(dict(family_id=alias, original_id=name, original_name=fields[0],
                             classification=cls, length=len(seq), sequence_sha256=hashlib.sha256(seq.encode()).hexdigest(),
                             source_tool=source_tool, source_library_sha256=source_hash))
    table(str(output) + ".provenance.tsv", rows, ["family_id", "original_id", "original_name", "classification", "length", "sequence_sha256", "source_tool", "source_library_sha256"])
    return rows


# Keep the public adapter import stable.
from .tetrimmer_audit import audit_tetrimmer


def rm_out(path, lengths, library_ids, library_lengths=None, *, strict_consensus=False):
    rows = []
    text = Path(path).read_text(encoding="utf-8", errors="strict")
    if not text.strip():
        raise WorkflowError("Empty RepeatMasker .out is ambiguous; explicit no-hit output required")
    recognized = "There were no repetitive sequences" in text or ("SW" in text and "score" in text)
    for n, line in enumerate(text.splitlines(), 1):
        v = line.split()
        if not v or not v[0].isdigit():
            continue
        if len(v) not in (15, 16) or (len(v) == 16 and v[15] != "*"):
            raise WorkflowError(f"Malformed RepeatMasker row {n}")
        try:
            a, b = int(v[5]), int(v[6])
            for x in v[1:4]:
                if not 0 <= float(x) <= 100:
                    raise ValueError("Invalid percentage")
            int(v[14])
        except ValueError as e:
            raise WorkflowError(f"Invalid RepeatMasker numbers at row {n}") from e
        if v[4] not in lengths or a < 1 or b < a or b > lengths[v[4]] or v[8] not in ("+", "C"):
            raise WorkflowError(f"RepeatMasker query coordinate mismatch at row {n}")
        if v[9] not in library_ids:
            raise WorkflowError("RepeatMasker hit not in frozen library: " + v[9])
        # .out is adjudicated by ProcessRepeats. Preserve its coordinates and
        # report discrepancies against the actual library, never silently clamp.
        left, ends = (v[11], v[12:14]) if v[8] == 'C' else (v[13], v[11:13])
        if not re.fullmatch(r'\(-?\d+\)', left) or any(not re.fullmatch(r'-?\d+', x) for x in ends):
            raise WorkflowError(f'Invalid RepeatMasker consensus coordinates at {path}:{n}')
        rep_start, rep_end = sorted(map(int, ends))
        rep_left = int(left[1:-1])
        inferred = rep_end + rep_left
        expected = library_lengths.get(v[9]) if library_lengths is not None else None
        anomaly = rep_start < 1 or rep_left < 0 or (expected is not None and rep_end > expected)
        status = 'out_of_bounds' if anomaly else 'not_checked' if expected is None else 'verified' if inferred == expected else 'length_mismatch'
        if library_lengths is not None and expected is None:
            raise WorkflowError(f'Missing library length for {v[9]} at {path}:{n}')
        if strict_consensus and status != 'verified':
            raise WorkflowError(f'Consensus length mismatch at {path}:{n}: {v[9]}, inferred={inferred}, library={expected}')
        rows.append(dict(fragment_id=f"rm{len(rows)+1:09d}", seqid=v[4], start=a-1, end=b,
                         strand="-" if v[8] == "C" else "+", family_id=v[9], classification=v[10],
                         divergence=float(v[1]), score=int(v[0]), upstream_group=v[14], overlap_flag=len(v) == 16,
                         rep_start=rep_start, rep_end=rep_end, rep_left=rep_left, consensus_length=inferred,
                         library_length=expected, consensus_coordinate_status=status, rep_tokens=' '.join(v[11:14])))
    if not rows and not recognized:
        raise WorkflowError("Unrecognized RepeatMasker empty-result format")
    return rows


from .classification import tier, standard_class


def union(rows):
    out = []
    for chrom, a, b in sorted(rows):
        if a < 0 or b <= a:
            raise WorkflowError("Invalid BED interval")
        if out and out[-1][0] == chrom and a <= out[-1][2]:
            out[-1] = (chrom, out[-1][1], max(b, out[-1][2]))
        else:
            out.append((chrom, a, b))
    return out


def bed_write(path, rows):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for chrom, a, b in union(rows):
            f.write(f"{chrom}\t{a}\t{b}\n")


def trf_dat(path, lengths):
    chrom, rows = None, []
    text = Path(path).read_text(encoding="utf-8")
    if "Tandem Repeats Finder" not in text:
        raise WorkflowError("TRF .dat header absent")
    for line in text.splitlines():
        if line.startswith("Sequence:"):
            chrom = line.split()[1]
            if chrom not in lengths:
                raise WorkflowError("Unknown TRF seqid")
        elif line.split() and line.split()[0].isdigit():
            fields = line.split()
            if len(fields) < 15:
                raise WorkflowError("Truncated TRF row")
            a, b = int(fields[0]), int(fields[1])
            if chrom is None or a < 1 or b < a or b > lengths[chrom]:
                raise WorkflowError("Invalid TRF coordinates")
            rows.append((chrom, a-1, b))
    return rows


def dust_fasta(path, original):
    rows, src = [], dict(fasta(original))
    seen = set()
    for name, seq in fasta(path):
        if name not in src or seq.upper() != src[name].upper():
            raise WorkflowError("dustmasker altered sequence content")
        seen.add(name)
        for m in re.finditer("[acgt]+", seq):
            rows.append((name, m.start(), m.end()))
    if seen != src.keys():
        raise WorkflowError("dustmasker lost records")
    return rows


def export_branch(prepared, library, rmfile, output, branch, tandem=None, dust=None, softmask_policies=None):
    prepared, output = Path(prepared), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    manifest = read_json(prepared / "manifest.json")
    mapping = {s["alias"]: s for s in manifest["sequences"] if s["included"]}
    lengths = {k: v["length"] for k, v in mapping.items()}
    libs = {name.split("#", 1)[0]: len(seq) for name, seq in fasta(library, allow_empty=True)}
    hits = rm_out(rmfile, lengths, libs, libs)
    policies = ['te_primary'] if softmask_policies is None else softmask_policies
    if not policies or set(policies) - {'te_primary', 'all_interspersed'}:
        raise WorkflowError('Unknown softmask policy')
    def restore(intervals):
        return [(mapping[x]["original_id"], a, b) for x, a, b in intervals]
    tracks = {t: restore([(r["seqid"], r["start"], r["end"]) for r in hits if tier(r["classification"]) == t]) for t in ("te", "unknown", "non_te")}
    tracks["tandem"] = restore(trf_dat(tandem, lengths)) if tandem else []
    tracks["low_complexity"] = restore(dust_fasta(dust, prepared / "genome.fa")) if dust else []
    names = {"te": "te.mask.bed", "unknown": "repeat_unknown.bed", "non_te": "non_te.bed", "tandem": "tandem_repeat.bed", "low_complexity": "low_complexity.bed"}
    for key, filename in names.items():
        bed_write(output / filename, tracks[key])
    # Repeat mask includes classified TE, tandem and low complexity; unknown is separate.
    combined = union(tracks["te"] + tracks["tandem"] + tracks["low_complexity"])
    bed_write(output / "repeat.mask.bed", combined)
    inclusive = union(combined + tracks['unknown'])
    bed_write(output / 'repeat.mask.all_interspersed.bed', inclusive)
    fragments = [dict(r, seqid=mapping[r["seqid"]]["original_id"], tier=tier(r["classification"])) for r in hits]
    table(output / "mask_sources.tsv", fragments, ["fragment_id", "seqid", "start", "end", "strand", "family_id", "classification", "tier", "divergence", "score", "upstream_group", "overlap_flag",
          'rep_start', 'rep_end', 'rep_left', 'consensus_length', 'library_length', 'consensus_coordinate_status','rep_tokens'])
    table(output / "auxiliary_mask_sources.tsv", [dict(seqid=chrom, start=a, end=b, source=key) for key in ("tandem", "low_complexity") for chrom, a, b in tracks[key]], ["seqid", "start", "end", "source"])
    with open(output / "te_fragments.gff3", "w", encoding="utf-8", newline="\n") as f:
        f.write("##gff-version 3\n")
        for r in fragments:
            at = ";".join(k + "=" + quote(str(v), safe="") for k, v in {"ID": r["fragment_id"], "Name": r["family_id"], "classification": r["classification"], "evidence": "homology_fragment", "upstream_group": r["upstream_group"]}.items())
            if r['consensus_coordinate_status'] == 'verified':
                # Column 7 already orients the genomic match; the library target
                # stays on its forward strand. Using '-' twice would imply a
                # direct (+/+) alignment under the GFF3 strand-product convention.
                at += ';Target=' + quote(r['family_id'], safe='') + f" {r['rep_start']} {r['rep_end']} +"
            else:
                at += ';consensus_coordinate_status=' + r['consensus_coordinate_status']
            f.write(f'{r["seqid"]}\tRepeatMasker\trepeat_region\t{r["start"]+1}\t{r["end"]}\t{r["score"]}\t{r["strand"]}\t.\t{at}\n')
    by_chr = collections.defaultdict(list)
    for name, a, b in combined:
        by_chr[name].append((a, b))
    total, ambiguous, gc = 0, 0, 0
    with open(output / "genome.softmasked.fa", "w", encoding="ascii", newline="\n") as f:
        for alias, seq in fasta(prepared / "genome.fa"):
            name = mapping[alias]["original_id"]
            total += len(seq)
            ambiguous += sum(seq.count(x) for x in "RYSWKMBDHVN")
            gc += seq.count("G") + seq.count("C")
            bases = bytearray(seq.upper(), "ascii")
            for a, b in by_chr[name]:
                bases[a:b] = bases[a:b].lower()
            masked = bases.decode()
            if masked.upper() != seq.upper():
                raise WorkflowError("Softmask sequence invariant failed")
            fasta_write_record(f, name, masked)
    if 'all_interspersed' in policies:
        inc_by_chr = collections.defaultdict(list)
        for name, a, b in inclusive:
            inc_by_chr[name].append((a, b))
        with open(output / 'genome.softmasked.all_interspersed.fa', 'w', encoding='ascii', newline='\n') as f:
            for alias, seq in fasta(prepared / 'genome.fa'):
                name = mapping[alias]['original_id']
                bases = bytearray(seq.upper(), 'ascii')
                for a, b in inc_by_chr[name]:
                    bases[a:b] = bases[a:b].lower()
                fasta_write_record(f, name, bases.decode('ascii'))
    qc = dict(branch=branch, biological_validation="pending_server_result_review", scope="selected_nuclear_sequences",
              fragments=len(hits), family_ids_with_hits=len({r["family_id"] for r in hits}),
              total_bp=total, ambiguous_bp=ambiguous, acgt_bp=total-ambiguous, gc_bp=gc,
              union_bp={k: sum(b-a for _, a, b in union(v)) for k, v in tracks.items()},
              repeat_mask_bp=sum(b-a for _, a, b in combined),
              low_complexity_status="provided" if dust else "not_run", tandem_status="provided" if tandem else "not_run",
              note="Fragments and merged mask intervals are not insertion-event counts; unknown families excluded from primary mask")
    qc.update(mask_sources_table_version=2,
              consensus_coordinates=dict(collections.Counter(r['consensus_coordinate_status'] for r in hits)),
              interspersed_incl_unknown_bp=sum(b-a for _,a,b in union(tracks['te'] + tracks['unknown'])),
              all_interspersed_mask_bp=sum(b-a for _,a,b in inclusive),
              masking_policies=dict(te_primary='classified TE + tandem + low complexity; excludes Unknown and other non-TE',
                  all_interspersed='classified TE + Unknown + tandem + low complexity; excludes other non-TE',
                  generated_fasta=['te_primary'] + (['all_interspersed'] if 'all_interspersed' in policies else [])))
    write_json(output / "qc.json", qc)
    return qc
