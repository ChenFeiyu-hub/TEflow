"""Library evidence only: flags are not an automatic gene/TE filter."""
import csv
import hashlib
import itertools
import re
from collections import Counter
from pathlib import Path
from .common import WorkflowError, fasta, fasta_write_record, table, write_json, text_open
from .formats import tier, standard_class
from .classification import classify
from .runtime import run

COMP = str.maketrans("ACGTRYSWKMBDHVN", "TGCAYRSWMKVHDBN")
CODONS = dict(zip(("".join(x) for x in itertools.product("TCAG", repeat=3)),
                  "FFLLSSSSYY**CC*WLLLLPPPPHHQQRRRRIIIMTTTTNNKKSSRRVVVVAAAADDEEGGGG"))


def revcomp(seq):
    return seq.upper().translate(COMP)[::-1]


def seqkey(seq):
    return min(seq.upper(), revcomp(seq))


def translate(seq):
    return "".join(CODONS.get(seq[i:i+3].upper(), "X") for i in range(0, len(seq)-2, 3))


def host_proteins(cds, output):
    count = 0
    with open(output, "w", encoding="ascii") as out:
        for name, seq in fasta(cds):
            protein = translate(seq).rstrip("*")
            if len(seq) % 3 or "*" in protein or not protein:
                raise WorkflowError("Host CDS cannot be translated with standard nuclear code: " + name)
            fasta_write_record(out, name, protein)
            count += 1
    return count


def check_proteins(path):
    ids, current, size = set(), None, 0
    with text_open(path) as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            if line.startswith(">"):
                if current is not None and not size:
                    raise WorkflowError("Empty protein record")
                current = line[1:].split()[0] if line[1:].split() else ""
                if not current or current in ids:
                    raise WorkflowError("Invalid/duplicate protein ID")
                ids.add(current); size = 0
            else:
                if current is None or set(line.upper()) - set("ABCDEFGHIKLMNPQRSTVWXYZUOJ*"):
                    raise WorkflowError("Invalid protein FASTA: " + str(path))
                size += len(line)
    if not ids or not size:
        raise WorkflowError("Empty protein database")
    return len(ids)


def library_qc(c, prepared, library, folder, cores):
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    records = list(fasta(library, allow_empty=True))
    rows, seen, duplicate_rows = [], {}, []
    for name, seq in records:
        fid, cls = name.split("#", 1)
        key = hashlib.sha256(seqkey(seq).encode()).hexdigest()
        flags = []
        if "?" in cls:
            flags.append("upstream_classification_uncertain")
        nonacgt = sum(b not in "ACGT" for b in seq.upper())
        if nonacgt:
            flags.append("ambiguous_bases")
        if not any(b in "ACGT" for b in seq.upper()):
            flags.append("no_acgt")
        if key in seen:
            flags.append("exact_or_rc_duplicate")
            duplicate_rows.append(dict(family_id=fid, identical_to=seen[key], relation="full_sequence_or_reverse_complement"))
        seen.setdefault(key, fid)
        rows.append(dict(family_id=fid, classification=cls, standard_class=standard_class(cls), tier=tier(cls),
                         length=len(seq), non_acgt_bp=nonacgt, n_fraction=seq.upper().count("N")/len(seq),
                         gc_fraction=sum(b in "GC" for b in seq.upper())/len(seq), flags=flags,
                         host_protein_hits=0, te_protein_hits=0, pfam_hits=0))
        rows[-1].update(classify(cls))
    byid = {r["family_id"]: r for r in rows}
    policy = c.get("qc", {})
    evidence = dict(host_protein="not_requested", te_protein="not_requested", pfam="not_requested")
    timeout = c["execution"].get("stage_timeout_seconds")
    def call(tool, args, name):
        return run(c["tools"][tool]["command"] + list(map(str, args)), folder,
                   folder / (name + ".log"), timeout, cpu_limit=cores)
    for kind, setting in (("host", policy.get("host_proteins")), ("te", policy.get("te_proteins"))):
        if not setting:
            continue
        protein = Path(setting)
        if setting == "derived":
            protein = folder / "host.protein.fa"
            host_proteins(Path(prepared) / "host.cds.fa", protein)
        check_proteins(protein)
        hitfile = folder / (kind + ".blastx.tsv")
        if records:
            db = folder / (kind + ".db")
            call("diamond", ["makedb", "--in", protein, "--db", db, "--threads", cores], kind + ".makedb")
            call("diamond", ["blastx", "--query", library, "--db", db, "--out", hitfile, "--threads", cores,
                             "--evalue", policy.get("evalue", 1e-5), "--max-target-seqs", 5,
                             "--outfmt", 6, "qseqid", "sseqid", "pident", "length", "evalue", "bitscore", "qstart", "qend"], kind + ".blastx")
        else:
            hitfile.write_text("")
        for line in hitfile.read_text().splitlines():
            v = line.split("\t")
            fid = v[0].split("#", 1)[0]
            if len(v) != 8 or fid not in byid:
                raise WorkflowError("Invalid DIAMOND evidence row")
            if float(v[4]) <= policy.get("evalue", 1e-5):
                byid[fid][kind + "_protein_hits"] += 1
        evidence[kind + "_protein"] = "executed"
    if policy.get("pfam"):
        mapping, frames = {}, folder / "six_frames.faa"
        with frames.open("w", encoding="ascii") as out:
            for i, (name, seq) in enumerate(records):
                for fno, dna in enumerate((seq, revcomp(seq))):
                    for offset in range(3):
                        peptide = translate(dna[offset:]).replace("*", "X")
                        if peptide:
                            key = f"q{i:07d}_f{fno*3+offset}"
                            mapping[key] = name.split("#", 1)[0]
                            fasta_write_record(out, key, peptide)
        dom = folder / "pfam.domtblout"
        if mapping:
            call("hmmscan", ["--noali", "--cpu", cores, "--domtblout", dom,
                             Path(c["databases"]["pfam_dir"]) / "Pfam-A.hmm", frames], "pfam")
        else:
            dom.write_text("# Empty query library\n")
        domain_rows = []
        for line in dom.read_text().splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            v = line.split()
            if len(v) < 22 or v[3] not in mapping:
                raise WorkflowError("Invalid hmmscan domain evidence")
            if float(v[12]) <= policy.get("evalue", 1e-5):
                fid = mapping[v[3]]
                byid[fid]["pfam_hits"] += 1
                domain_rows.append(dict(family_id=fid, translated_query=v[3], domain=v[0], accession=v[1],
                                        independent_evalue=v[12], aa_start=v[17], aa_end=v[18]))
        table(folder / "domain_evidence.tsv", domain_rows, ["family_id", "translated_query", "domain", "accession", "independent_evalue", "aa_start", "aa_end"])
        evidence["pfam"] = "executed_standard_code_six_frames"
    for r in rows:
        if r["host_protein_hits"]:
            r["flags"].append("host_protein_similarity_review")
        # No domain absence is ever used as a deletion criterion.
        r["flags"] = ";".join(r["flags"])
    fields = ["family_id", "classification", "standard_class", "tier", "length", "non_acgt_bp", "n_fraction", "gc_fraction",
              "host_protein_hits", "te_protein_hits", "pfam_hits", "flags", 'mapping_version', 'order',
              'superfamily_code', 'classification_uncertain', 'structural_label', 'mapping_status']
    table(folder / "library_qc.tsv", rows, fields)
    table(folder / "exact_duplicates.tsv", duplicate_rows, ["family_id", "identical_to", "relation"])
    result = dict(families=len(rows), evidence=evidence, automatic_filter=False,
                  interpretation="Protein similarity and domain presence are evidence, not TE/gene truth; absence is not a negative label")
    write_json(folder / "qc.json", result)
    return result


def non_hle_library(source, qcfile, output):
    with open(qcfile, encoding="utf-8") as f:
        quality = {r["family_id"]: r for r in csv.DictReader(f, delimiter="\t")}
    count = 0
    with open(output, "w", encoding="ascii") as out:
        for name, seq in fasta(source, allow_empty=True):
            fid, cls = name.split("#", 1)
            q = quality[fid]
            if tier(cls) == "te" and standard_class(cls) != "HLE" and not int(q["host_protein_hits"]) and "no_acgt" not in q["flags"]:
                fasta_write_record(out, name, seq)
                count += 1
    return count


def combine_libraries(sources, output, prefix):
    """Only exact full-sequence/RC aliases are collapsed; no invented consensus."""
    representatives, rows = {}, []
    with open(output, "w", encoding="ascii") as out:
        for branch, path in sources:
            for name, seq in fasta(path, allow_empty=True):
                original, cls = name.split("#", 1)
                # A classification conflict preserves both records, not an arbitrary winner.
                key = (seqkey(seq), cls)
                if key not in representatives:
                    fid = f"{prefix}{len(representatives)+1:07d}"
                    representatives[key] = fid
                    fasta_write_record(out, fid + "#" + cls, seq)
                rows.append(dict(family_id=representatives[key], parent_branch=branch, parent_family_id=original,
                                 classification=cls, transformation="exact_or_rc_alias_only"))
    table(str(output) + ".parents.tsv", rows, ["family_id", "parent_branch", "parent_family_id", "classification", "transformation"])
    return len(representatives)
