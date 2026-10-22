"""Read-only reference audit and reversible sequence-name staging."""
from __future__ import annotations
import collections
import re
from pathlib import Path
from urllib.parse import unquote
from .common import WorkflowError, fasta, fasta_write_record, sha256, text_open, table, write_json, read_json, work, sample, source_fingerprint


def attributes(text):
    if "=" in text.split(";", 1)[0]:
        return {k: unquote(v) for field in text.split(";") if "=" in field
                for k, v in [field.split("=", 1)]}
    return dict(re.findall(r'(\S+)\s+"([^"]*)"\s*;?', text))


def annotation_rows(path):
    with text_open(path) as f:
        for n, raw in enumerate(f, 1):
            if raw.startswith("##FASTA"):
                break
            if not raw.strip() or raw.startswith("#"):
                continue
            v = raw.rstrip("\r\n").split("\t")
            if len(v) != 9:
                raise WorkflowError(f"Annotation needs 9 columns at line {n}")
            try:
                a, b = int(v[3]), int(v[4])
            except ValueError as e:
                raise WorkflowError(f"Invalid annotation coordinates at line {n}") from e
            if a < 1 or b < a or v[6] not in ("+", "-", ".", "?"):
                raise WorkflowError(f"Invalid annotation interval at line {n}")
            yield v[0], v[2], a, b, v[6], v[7], attributes(v[8])


def audit_sample(s):
    seqs = []
    excluded = set(s.get("exclude_seqids", []))
    for i, (name, seq) in enumerate(fasta(s["genome"]), 1):
        seqs.append(dict(original_id=name, alias=f"s{i:06d}", length=len(seq),
                         n_bp=seq.upper().count("N"), lowercase_bp=sum(x.islower() for x in seq),
                         other_ambiguous_bp=sum(seq.upper().count(x) for x in "RYSWKMBDHV"),
                         included=name not in excluded))
    lengths = {x["original_id"]: x["length"] for x in seqs}
    if excluded - lengths.keys():
        raise WorkflowError("Excluded IDs absent from genome: " + ", ".join(sorted(excluded - lengths.keys())))
    if not any(x["included"] for x in seqs):
        raise WorkflowError("All sequences excluded")
    features = collections.Counter()
    if s.get("annotation"):
        for chrom, kind, a, b, strand, phase, attrs in annotation_rows(s["annotation"]):
            if chrom not in lengths or b > lengths[chrom]:
                raise WorkflowError(f"Annotation/FASTA mismatch: {chrom}:{a}-{b}")
            features[kind] += 1
    files = {k: dict(path=s[k], sha256=sha256(s[k])) for k in ("genome", "annotation", "cds") if s.get(k)}
    if s.get("cds"):
        for _ in fasta(s["cds"]):
            pass
    return dict(sample=s["id"], files=files, sequences=seqs, annotation_features=dict(features),
                selected_bp=sum(x["length"] for x in seqs if x["included"]),
                selected_acgt_denominator="selected_bp minus all ambiguous IUPAC bases (computed during export)",
                cds_policy="provided" if s.get("cds") else "derive_non_TE_complete_CDS" if s.get("derive_cds", False) else "not_provided")


def derive_cds(annotation, genome, out, included=None):
    """Conservative coordinate extraction, not protein-based TE filtering.

    Exclude explicitly annotated TE genes; require complete phase-consistent CDS.
    Retain the longest eligible transcript per gene. Other gene contamination is
    still possible and is reported; this is not a curated host protein set.
    """
    transcripts, parts, te_genes = {}, collections.defaultdict(list), set()
    te_label_features = 0
    stop_parts = collections.defaultdict(list)
    for chrom, kind, a, b, strand, phase, at in annotation_rows(annotation):
        gid = at.get("gene_id", at.get("ID", ""))
        if kind == "transposable_element_gene" or any(at.get(k, "").lower() in ("transposable_element", "transposable_element_gene", "te_gene") for k in ("gene_biotype", "biotype", "gene_type")):
            te_genes.add(gid)
            te_label_features += 1
        if kind in ("mRNA", "transcript"):
            tid = at.get("transcript_id", at.get("ID"))
            if tid:
                transcripts[tid] = at.get("gene_id", at.get("Parent", tid))
        if kind == "CDS":
            parents = at.get("transcript_id", at.get("Parent", "")).split(",")
            for tid in filter(None, parents):
                if "gene_id" in at:
                    transcripts[tid] = at["gene_id"]
                if phase not in ("0", "1", "2") or strand not in ("+", "-"):
                    raise WorkflowError("CDS requires a valid strand and phase")
                parts[tid].append((chrom, a, b, strand, int(phase)))
        if kind == "stop_codon":
            for tid in filter(None, at.get("transcript_id", at.get("Parent", "")).split(",")):
                stop_parts[tid].append((chrom, a, b, strand))
    by_chr = collections.defaultdict(list)
    for tid, rows in parts.items():
        if len({(x[0], x[3]) for x in rows}) != 1:
            raise WorkflowError("CDS transcript crosses contigs/strands: " + tid)
        by_chr[rows[0][0]].append((tid, rows))
    comp = str.maketrans("ACGTRYSWKMBDHVN", "TGCAYRSWMKVHDBN")
    best, reasons = {}, collections.Counter()
    for chrom, dna in fasta(genome):
        if included is not None and chrom not in included:
            continue
        dna = dna.upper()
        for tid, rows in by_chr.get(chrom, []):
            gid = transcripts.get(tid, tid)
            if gid in te_genes:
                reasons["annotated_TE_gene"] += 1
                continue
            rows = sorted(rows, key=lambda x: x[1], reverse=rows[0][3] == "-")
            chunks, total, valid = [], 0, True
            genomic_intervals = sorted((r[1], r[2]) for r in rows)
            if any(a2 <= b1 for (_, b1), (a2, _) in zip(genomic_intervals, genomic_intervals[1:])):
                raise WorkflowError("Overlapping CDS pieces: " + tid)
            for _, a, b, strand, phase in rows:
                if b > len(dna):
                    raise WorkflowError("CDS outside genome")
                if phase != (3 - total % 3) % 3:
                    valid = False
                seq = dna[a - 1:b]
                chunks.append(seq if strand == "+" else seq.translate(comp)[::-1])
                total += len(seq)
            seq = "".join(chunks)
            stops = {"TAA", "TAG", "TGA"}
            # Ensembl GTF excludes the stop codon from CDS; GFF3 often includes it.
            # Append only explicitly annotated, wholly downstream terminal bases.
            if seq[-3:] not in stops and tid in stop_parts:
                terminal = sorted(stop_parts[tid], key=lambda x: x[1], reverse=rows[0][3] == "-")
                strand = rows[0][3]
                after = all(ch == chrom and st == strand and b <= len(dna) and
                            ((a > max(r[2] for r in rows)) if strand == "+" else (b < min(r[1] for r in rows)))
                            for ch, a, b, st in terminal)
                if after and sum(b-a+1 for _, a, b, _ in terminal) == 3:
                    stop = "".join(dna[a-1:b] if strand == "+" else dna[a-1:b].translate(comp)[::-1] for _, a, b, _ in terminal)
                    if stop in stops:
                        seq += stop
                        reasons["annotated_separate_stop_appended"] += 1
            if not valid or len(seq) < 90 or len(seq) % 3 or not seq.startswith("ATG") or seq[-3:] not in stops or set(seq) - set("ACGT") or any(seq[i:i+3] in stops for i in range(0, len(seq)-3, 3)):
                reasons["incomplete_or_noncanonical_CDS"] += 1
                continue
            if gid not in best or (len(seq), tid) > (len(best[gid][1]), best[gid][0]):
                best[gid] = tid, seq
    if not best:
        raise WorkflowError("No complete non-TE CDS extracted; provide a verified CDS FASTA or explicitly disable derive_cds")
    with open(out, "w", encoding="ascii", newline="\n") as f:
        for i, (gid, (tid, seq)) in enumerate(sorted(best.items()), 1):
            fasta_write_record(f, f"cds{i:07d}", seq)
    table(str(out) + ".mapping.tsv", [dict(alias=f"cds{i:07d}", gene_id=g, transcript_id=v[0], length=len(v[1])) for i, (g, v) in enumerate(sorted(best.items()), 1)], ["alias", "gene_id", "transcript_id", "length"])
    return dict(accepted_genes=len(best), transcript_processing_counts=dict(reasons), te_label_features=te_label_features,
                annotated_te_genes=len(te_genes), te_label_status="present" if te_label_features else "not_observed_no_claim_of_complete_filtering",
                limitation="Only explicitly annotated TE genes excluded; no claim of complete host/TE discrimination")


def prepare(c, sid):
    s = sample(c, sid)
    folder = work(c, sid) / "prepared"
    audit = audit_sample(s)
    audit["source_fingerprint"] = source_fingerprint()
    if folder.exists() and any(folder.iterdir()):
        done = folder / "manifest.json"
        if done.exists():
            old = read_json(done)
            if all(old.get(k) == audit[k] for k in ("files", "sequences", "cds_policy", "source_fingerprint")) and all((folder / p).is_file() and sha256(folder / p) == h for p, h in old["outputs"].items()):
                return old
        raise WorkflowError("Prepared directory is incomplete or inputs changed; use a new run_id")
    folder.mkdir(parents=True, exist_ok=True)
    seqmap = {x["original_id"]: x for x in audit["sequences"]}
    with open(folder / "genome.fa", "w", encoding="ascii", newline="\n") as f:
        for name, seq in fasta(s["genome"]):
            entry = seqmap[name]
            if entry["included"]:
                fasta_write_record(f, entry["alias"], seq.upper())
    table(folder / "seqids.tsv", audit["sequences"], ["original_id", "alias", "length", "n_bp", "lowercase_bp", "included"])
    outputs = ["genome.fa", "seqids.tsv"]
    if s.get("cds"):
        with open(folder / "host.cds.fa", "w", encoding="ascii", newline="\n") as f:
            for i, (_, seq) in enumerate(fasta(s["cds"]), 1):
                fasta_write_record(f, f"cds{i:07d}", seq.upper())
        outputs.append("host.cds.fa")
    elif s.get("derive_cds"):
        if not s.get("annotation"):
            raise WorkflowError("derive_cds requires annotation")
        audit["cds_audit"] = derive_cds(s["annotation"], s["genome"], folder / "host.cds.fa", {x["original_id"] for x in audit["sequences"] if x["included"]})
        outputs += ["host.cds.fa", "host.cds.fa.mapping.tsv"]
    audit["outputs"] = {p: sha256(folder / p) for p in outputs}
    audit["coordinate_convention"] = "Sequence-name changes only; no coordinate shifts; excluded sequences not annotated"
    write_json(folder / "manifest.json", audit)
    return audit
