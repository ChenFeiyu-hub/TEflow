"""Audited HELIANO 1.3.1 and pinned HiTE image command/output contracts."""
import csv
import hashlib
import math
import re
from pathlib import Path
from ..common import WorkflowError, fasta, fasta_write_record, table, write_json
from ..formats import canonical_library, rm_out, union
from ..library_qc import revcomp, non_hle_library
from ..branches import options
from ..runtime import stage_copy, rm_parallel_jobs


def audit_logs(paths):
    pattern = re.compile(r"Traceback \(most recent call last\)|\bERROR\b[:\s]|command not found|No such file or directory|Could not find|Segmentation fault|model file not found", re.I)
    errors = []
    for path in paths:
        with open(path, encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f, 1):
                if pattern.search(line):
                    errors.append(dict(path=str(path), line=i, text=line.strip()[:500]))
                    if len(errors) >= 20:
                        break
    if errors:
        raise WorkflowError("Upstream error text despite possible zero exit: " + str(errors[:3]))


def heliano_native(raw, genome, output):
    """The v1.3.1 OutputSequence uses start-1:end, despite the .bed suffix."""
    raw, output = Path(raw), Path(output)
    seqs = dict(fasta(genome))
    predicted = dict(fasta(raw / "RC.representative.fa", allow_empty=True))
    rows, seen = [], set()
    with open(raw / "RC.representative.bed", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            v = line.rstrip().split("\t")
            if len(v) != 11:
                raise WorkflowError("HELIANO v1.3.1 native row needs 11 columns")
            chrom, start, end, subfamily, copies, strand, pvalue, identity, variant, mobility, name = v
            a, b = int(start)-1, int(end)
            if chrom not in seqs or not 0 <= a < b <= len(seqs[chrom]) or strand not in ("+", "-") or name in seen or variant not in ("HLE1", "HLE2"):
                raise WorkflowError("Invalid HELIANO native coordinates/identity")
            seq = seqs[chrom][a:b].upper()
            expected = seq if strand == "+" else revcomp(seq)
            if predicted.get(name, "").upper() != expected:
                raise WorkflowError("HELIANO native sequence does not round-trip to genome: " + name)
            seen.add(name)
            rows.append(dict(seqid=chrom, start=a, end=b, native_id=name, subfamily=subfamily,
                             strand=strand, pvalue=float(pvalue), terminal_identity=float(identity),
                             variant=variant, mobility=mobility, occurrence=int(copies)))
    if seen != predicted.keys():
        raise WorkflowError("HELIANO BED/FASTA ID set differs")
    table(output, rows, ["seqid", "start", "end", "native_id", "subfamily", "strand", "pvalue", "terminal_identity", "variant", "mobility", "occurrence"])
    # This third file is produced at the end of main; an early exit(0) is not an empty success.
    if not (raw / "pairlist.tbl").is_file():
        raise WorkflowError("HELIANO did not reach its terminal-pair output contract")
    return rows


def run_heliano(c, base, folder, cores, call, resume):
    pars = options(c, "heliano")
    genome = folder / "genome.fa"
    stage_copy(base / "prepared/genome.fa", genome)
    # A retry gets a new native output directory; partial async jobs are never trusted as cache.
    raw = folder / "raw"
    if raw.exists():
        candidates = sorted(folder.glob("raw.attempt*"))
        raw = folder / ("raw.attempt%03d" % (len(candidates)+1))
    args = ["-g", genome, "-o", raw, "-n", cores, "-w", pars["window"],
            "-dm", pars["domain_distance"], "-dn", pars["terminal_distance"],
            "-is1", pars["insertion_site_hle1"], "-is2", pars["insertion_site_hle2"],
            "-sim_tir", pars["terminal_identity"], "-flank_sim", pars["flank_similarity"],
            "-p", pars["pvalue"], "-s", pars["bitscore"], "-pt", 1, "-tb", 0]
    if pars["nearest"]:
        args.append("--nearest")
    call("heliano", args, raw.name)
    audit_logs([folder / (raw.name + ".log")])
    native = heliano_native(raw, genome, folder / "native_sites.tsv")
    mapping = {r["native_id"]: r for r in native}
    source = raw / "RC.representative.fa"
    relation_rows = []
    if native and pars["library_mode"] == "official_consensus":
        consensus = folder / (raw.name + ".consensus")
        workers = max(1, math.isqrt(cores))  # upstream has ThreadPool(n) * cd-hit -T n
        call("heliano_cons", ["-g", genome, "-r", raw / "RC.representative.bed", "-o", consensus, "-n", workers], "consensus")
        audit_logs([folder / "consensus.log"])
        source = consensus / "RC.representative.cons.fa"
        records = list(fasta(source))
        parents = {r["subfamily"] for r in native}
        found = {n.rsplit(".", 1)[0] for n, _ in records}
        if found != parents:
            raise WorkflowError("HELIANO consensus lost subfamilies (async worker errors may be hidden)")
    else:
        records = list(fasta(source, allow_empty=True))
    tagged = folder / "source.tagged.fa"
    with tagged.open("w", encoding="ascii") as out:
        for name, seq in records:
            fasta_write_record(out, name + "#RC/Helitron", seq)
    prov = canonical_library(tagged, folder / "raw.library.fa", "H", "HELIANO-1.3.1:" + pars["library_mode"])
    for r in prov:
        parents = [mapping[r["original_name"]]] if pars["library_mode"] == "native_representatives" else [x for x in native if x["subfamily"] == r["original_name"].rsplit(".", 1)[0]]
        for parent in parents:
            relation_rows.append(dict(family_id=r["family_id"], native_id=parent["native_id"], subfamily=parent["subfamily"],
                                     relation="native_sequence" if pars["library_mode"] == "native_representatives" else "subfamily_support_not_exact_alignment", variant=parent["variant"]))
    table(folder / "library.parents.tsv", relation_rows, ["family_id", "native_id", "subfamily", "relation", "variant"])
    n = non_hle_library(base / "edta/library.fa", base / "qc_edta/library_qc.tsv", folder / "non_hle.fa")
    query = folder / "candidates.fa"
    # Derived query is regenerated on an explicit failed-stage retry.
    query.write_bytes((folder / "raw.library.fa").read_bytes())
    intervals = {}
    hits = []
    if records and n:
        call("repeatmasker", ["-e", "rmblast", "-pa", rm_parallel_jobs(cores), "-s", "-nolow", "-no_is", "-div", c["parameters"]["max_divergence"], "-lib", folder / "non_hle.fa", "-dir", folder, query], "nested")
        # RM query IDs include the complete '#classification' header.
        lengths = {name: len(seq) for name, seq in fasta(query)}
        ids = {name.split("#")[0]:len(seq) for name, seq in fasta(folder / "non_hle.fa")}
        hits = rm_out(folder / "candidates.fa.out", lengths, ids, ids)
        for r in hits:
            intervals.setdefault(r["seqid"], []).append((r["seqid"], r["start"], r["end"]))
    table(folder / "nested_hits.tsv", hits, ["seqid", "start", "end", "family_id", "classification", "divergence"])
    excluded, masks = [], []
    with (folder / "library.fa").open("w", encoding="ascii") as out:
        for name, seq in fasta(query, allow_empty=True):
            bases = list(seq.upper())
            for _, a, b in union(intervals.get(name, [])):
                bases[a:b] = "N" * (b-a)
                masks.append(dict(query_id=name, start=a, end=b, source="edta_non_hle", transformation="N_mask_preserve_length"))
            newseq = "".join(bases)
            if any(x in "ACGT" for x in newseq):
                fasta_write_record(out, name, newseq)
            else:
                excluded.append(dict(query_id=name, reason="no_acgt_after_nested_mask"))
    table(folder / "nested_mask.tsv", masks, ["query_id", "start", "end", "source", "transformation"])
    table(folder / "excluded.tsv", excluded, ["query_id", "reason"])
    retained = {n.split("#")[0]: seq for n, seq in fasta(folder / "library.fa", allow_empty=True)}
    provenance = [dict(r, raw_sequence_sha256=r["sequence_sha256"],
                       sequence_sha256=hashlib.sha256(retained[r["family_id"]].encode()).hexdigest(),
                       transformation="edta_non_hle_N_mask") for r in prov if r["family_id"] in retained]
    fields = list(prov[0]) if prov else ["family_id", "original_id", "original_name", "classification", "length", "sequence_sha256", "source_tool", "source_library_sha256"]
    table(folder / "library.fa.provenance.tsv", provenance, fields + ["raw_sequence_sha256", "transformation"])
    details = dict(native_sites=len(native), library_entries=len(retained), library_mode=pars["library_mode"],
                   zero_candidates=not native, cleanup_dependency="edta_non_hle", nested_hits=len(hits),
                   native_coordinate_convention="upstream_1_based_closed_verified_by_sequence",
                   consensus_caveat="Official program extends 50 bp and removes gap/N characters; no exact boundary guarantee" if pars["library_mode"] == "official_consensus" else None)
    write_json(folder / "adapter_audit.json", details)
    return details, list(folder.glob("*.fa")) + list(folder.glob("*.tsv")) + [folder / "adapter_audit.json", raw / "RC.representative.bed", raw / "RC.representative.fa", raw / "pairlist.tbl"]


def run_hite(c, base, folder, cores, call, resume, specimen=None):
    if specimen is None:
        if len(c.get('samples', [])) != 1:
            raise WorkflowError('HiTE adapter needs an explicit sample for multiple samples')
        specimen = c['samples'][0]
    taxon_group = specimen.get('taxon_group', 'plant')
    genome = folder / "genome.fa"
    stage_copy(base / "prepared/genome.fa", genome)
    raw = folder / "raw"
    if raw.exists():
        raw = folder / ("raw.attempt%03d" % (len(list(folder.glob("raw.attempt*")))+1))
    # Always fresh attempts: upstream recover can reuse merely existing child outputs.
    scratch = folder / (raw.name + ".scratch"); scratch.mkdir()
    args = ["--genome", genome, "--out_dir", raw, "--work_dir", scratch, "--thread", cores,
            "--plant", int(taxon_group == 'plant'), "--te_type", "all", "--recover", 0, "--annotate", 0,
            "--search_struct", 1, "--BM_RM2", 0, "--BM_EDTA", 0, "--BM_HiTE", 0,
            "--debug", 1, "--is_wicker", 0, "--is_denovo_nonltr", 1, "--domain", 0]
    for key, value in options(c, "hite").items():
        args.extend(("--" + key, value))
    call("hite", args, raw.name)
    audit_logs([folder / (raw.name + ".log")] + list(raw.rglob("*.log")))
    library = raw / "confident_TE.cons.fa"
    if not list(fasta(library)):
        raise WorkflowError("HiTE empty/missing confident library is ambiguous, not verified zero candidates")
    from ..hite_image import provenance
    identity = provenance(c)
    prov = canonical_library(library, folder / "library.fa", "I", "HiTE-CLI-" + identity["cli_version"])
    details = dict(library_entries=len(prov), raw_output=str(raw), low_confidence_included=False,
                   taxon_group=taxon_group, taxon_group_source='explicit' if 'taxon_group' in specimen else 'legacy_default',
                   software_identity=identity,
                   reference_exposure="bundled homology resources and pretrained models; not reference-blind",
                   retry_policy="fresh_attempt_preserves_previous_raw")
    write_json(folder / "adapter_audit.json", details)
    outputs = [folder / "library.fa", folder / "library.fa.provenance.tsv", folder / "adapter_audit.json", library]
    outputs += [p for p in raw.iterdir() if p.is_file() and p.suffix in (".gff", ".gff3", ".bed")]
    return details, outputs
