"""Verified raw RepeatMasker alignment columns; final .out is only a linkage key.

Coordinates returned here are zero based, half open. Supported dialect: the
RepeatMasker -a nucleotide format with raw match ID and final group ID, as
produced by the workflow's RMBlast backend. Unsupported dialects fail closed.
"""
import re
from collections import defaultdict
from pathlib import Path
from .common import WorkflowError, fasta
from .evaluation import bp, intersect
from .library_qc import revcomp

SEQ = re.compile(r"^\s*(C\s+)?(\S+)\s+(\d+)\s+([A-Za-z-]+)\s+(\d+)\s*$")


class Genome:
    """Index uncompressed FASTA record offsets; cache at most one chromosome.

    Supports variable line lengths. No copy/index is written beside the input.
    Memory use is bounded by the largest chromosome, not the whole assembly.
    """
    def __init__(self, path):
        self.path = Path(path)
        if str(path).endswith(".gz"):
            raise WorkflowError("Candidate review needs uncompressed genome FASTA")
        self.records = {}; key = None; self.cached = (None, None)
        with self.path.open("rb") as handle:
            while True:
                offset = handle.tell(); line = handle.readline()
                if not line: break
                if line.startswith(b">"):
                    if key is not None: self.records[key][1] = offset
                    fields = line[1:].split()
                    if not fields: raise WorkflowError("Empty genome FASTA header")
                    key = fields[0].decode("ascii")
                    if key in self.records: raise WorkflowError("Duplicate genome seqid: " + key)
                    self.records[key] = [handle.tell(), None, 0]
                elif line.strip():
                    if key is None: raise WorkflowError("Genome sequence precedes FASTA header")
                    seq = line.strip().upper()
                    if set(seq) - set(b"ACGTRYSWKMBDHVN"):
                        raise WorkflowError("Invalid genome sequence: " + key)
                    self.records[key][2] += len(seq)
            if key is not None: self.records[key][1] = handle.tell()
        if not self.records or any(not r[2] for r in self.records.values()):
            raise WorkflowError("Empty genome sequence")
        self.lengths = {k: r[2] for k, r in self.records.items()}

    def __getitem__(self, key):
        if key not in self.records: raise WorkflowError("Unknown genome seqid: " + key)
        if self.cached[0] != key:
            a, b, _ = self.records[key]
            with self.path.open("rb") as handle:
                handle.seek(a)
                seq = b"".join(handle.read(b-a).split()).decode("ascii").upper()
            self.cached = (key, seq)
        return self.cached[1]


def read_library(path):
    seqs, names = {}, {}
    for name, seq in fasta(path):
        fid = name.split("#", 1)[0]
        if fid in seqs: raise WorkflowError("Duplicate library family: " + fid)
        seqs[fid] = seq.upper(); names[fid] = name
    return seqs, names


def require(ok, message, block):
    if not ok:
        raise WorkflowError(f"Alignment {block.get('alignment_id', '?')} (line {block.get('line', '?')}): {message}")


def finish_block(block, rows, genome, library):
    require(rows and len(rows) % 2 == 0, "missing/unpaired sequence rows", block)
    qparts, rparts = [], []
    qpos = block["start"]; step = 1 if block["strand"] == "+" else -1
    rpos = block["repeat_start"] if step == 1 else block["repeat_end"]-1
    for q, r in zip(rows[::2], rows[1::2]):
        require(q["name"] == block["query_alias"] and not q["reverse"], "query label/strand", block)
        # RM abbreviates the printed library label; the full header defines identity.
        require(block["library_name"].startswith(r["name"]), "repeat label", block)
        require(r["reverse"] == (step == -1), "repeat strand", block)
        require(q["start"]-1 == qpos and r["start"]-1 == rpos, "chunk continuity", block)
        require(len(q["seq"]) == len(r["seq"]), "alignment column lengths", block)
        require(all(x != "-" or y != "-" for x, y in zip(q["seq"], r["seq"])), "double gap", block)
        qp, rp = q["seq"].replace("-", ""), r["seq"].replace("-", "")
        require(len(qp) == q["end"]-q["start"]+1 and len(rp) == abs(r["end"]-r["start"])+1,
                "chunk coordinate length", block)
        require(qp == genome[block["seqid"]][q["start"]-1:q["end"]], "genome sequence mismatch", block)
        a, b = sorted([r["start"], r["end"]])
        expected = library[block["family_id"]][a-1:b]
        require(rp == (expected if step == 1 else revcomp(expected)), "library sequence mismatch", block)
        qpos = q["end"]; rpos = r["end"]-1+step
        qparts.append(q["seq"]); rparts.append(r["seq"])
    require(qpos == block["end"] and rpos == (block["repeat_end"] if step == 1 else block["repeat_start"]-1),
            "header/chunk end mismatch", block)
    block.update(qseq="".join(qparts), rseq="".join(rparts))
    block.update(columns=len(block["qseq"]), query_gap_columns=block["qseq"].count("-"),
                 repeat_gap_columns=block["rseq"].count("-"))
    return block


def iter_alignments(path, genome, library, aliases=None):
    """Stream every block and verify both sequences, including unselected families."""
    aliases = aliases or {k: k for k in genome.lengths}
    block = None; rows = []; count = 0
    with open(path, encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, 1):
            values = line.split()
            sequence_row = SEQ.match(line)
            if values and values[0].isdigit() and not sequence_row:
                if block: yield finish_block(block, rows, genome, library)
                count += 1
                try:
                    minus = values[8] == "C"; offset = int(minus)
                    if len(values) != 14+offset or not values[-1].isdigit(): raise ValueError("header dialect")
                    name = values[8+offset]; fid, cls = name.split("#", 1)
                    lo, hi, left = ((int(values[12]), int(values[11]), int(values[10].strip("()"))) if minus else
                                    (int(values[9]), int(values[10]), int(values[11].strip("()"))))
                    alias = values[4]; chrom = aliases[alias]
                    a, b = int(values[5])-1, int(values[6])
                    block = dict(alignment_id=f"aln{count:09d}", line=lineno, query_alias=alias, seqid=chrom,
                                 start=a, end=b, strand="-" if minus else "+", family_id=fid, classification=cls,
                                 library_name=name, score=int(values[0]), divergence=float(values[1]),
                                 repeat_start=lo-1, repeat_end=hi, repeat_left=left,
                                 source_match_id=values[-2], upstream_group=values[-1])
                    require(0 <= a < b <= genome.lengths[chrom] and b+int(values[7].strip("()")) == genome.lengths[chrom],
                            "query header coordinates", block)
                    require(1 <= lo <= hi <= len(library[fid]) and hi+left == len(library[fid]), "library header coordinates", block)
                    require(all(0 <= float(v) <= 100 for v in values[1:4]), "percentages", block)
                except (KeyError, ValueError, IndexError) as e:
                    raise WorkflowError(f"Unsupported/invalid RepeatMasker alignment header at {path}:{lineno}: {e}") from e
                rows = []
            elif (m := sequence_row):
                if not block: raise WorkflowError(f"Alignment sequence without header: {path}:{lineno}")
                rows.append(dict(reverse=bool(m[1]), name=m[2], start=int(m[3]), seq=m[4].upper(), end=int(m[5])))
    if block: yield finish_block(block, rows, genome, library)
    if not count: raise WorkflowError("No recognized raw alignment blocks: " + str(path))


def link_final(records, blocks):
    groups = defaultdict(list)
    for b in blocks: groups[(b["seqid"], b["strand"], b["upstream_group"])].append(b)
    for r in records:
        candidates = [b for b in groups[(r["seqid"], r["strand"], r["upstream_group"]) ]
                      if b["start"] < r["end"] and b["end"] > r["start"]]
        span = [(r["seqid"], r["start"], r["end"])]
        covered = bp(intersect(span, [(b["seqid"], b["start"], b["end"]) for b in candidates]))
        same = any(b["family_id"] == r["family_id"] for b in candidates)
        other = any(b["family_id"] != r["family_id"] for b in candidates)
        status = ("uncovered_or_partial" if covered != r["end"]-r["start"] else
                  "same_family_only" if not other else "mixed_raw_families" if same else "different_family_only")
        yield dict(fragment_id=r["fragment_id"], seqid=r["seqid"], start=r["start"], end=r["end"], strand=r["strand"],
                   final_family=r["family_id"], upstream_group=r["upstream_group"], status=status,
                   covered_bp=covered, uncovered_bp=r["end"]-r["start"]-covered,
                   raw_families=";".join(sorted({b["family_id"] for b in candidates})),
                   alignment_ids=";".join(b["alignment_id"] for b in candidates))


def project_spans(block, spans):
    """Project reported nucleotide span envelopes, not protein residue certainty.

    Return paired support and query insertions separately, as BED intervals.
    """
    spans = sorted(spans)
    step = 1 if block["strand"] == "+" else -1
    q = block["start"]; r = block["repeat_start"] if step == 1 else block["repeat_end"]-1
    paired, insertions = [], []
    def append(rows, pos):
        if rows and rows[-1][2] == pos: rows[-1] = (block["seqid"], rows[-1][1], pos+1)
        else: rows.append((block["seqid"], pos, pos+1))
    for qc, rc in zip(block["qseq"], block["rseq"]):
        if qc != "-":
            if rc == "-": append(insertions, q)
            elif any(a <= r < b for a, b in spans): append(paired, q)
            q += 1
        if rc != "-": r += step
    require(q == block["end"], "projection length mismatch", block)
    return paired, insertions
