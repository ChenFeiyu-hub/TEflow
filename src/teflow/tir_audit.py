"""Read-only contracts for native v4 candidates, without changing annotations."""
from collections import Counter
import hashlib
from pathlib import Path
import re
from .common import WorkflowError, fasta, read_json, table, write_json

LABELS = ("DTA", "DTC", "DTH", "DTM", "DTT", "NonTIR")


def sequence_key(seq):
    seq = seq.upper()
    rev = seq.translate(str.maketrans("ACGTRYMKBDHVN", "TGCAYRKMVHDBN"))[::-1]
    return hashlib.sha256(min(seq, rev).encode("ascii")).hexdigest()


def inspect_native(fa, gff, reference=None):
    fa, gff = Path(fa), Path(gff)
    if not fa.is_file() or not gff.is_file():
        raise WorkflowError("TIR native FASTA/annotation output is missing")
    sites, expected, columns = [], Counter(), Counter()
    for line_no, line in enumerate(gff.read_text(encoding="utf-8").splitlines(), 1):
        if not line or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) not in (9, 15):
            raise WorkflowError(f"Native TIR row {line_no} needs 9 or 15 tab-separated fields")
        columns[len(fields)] += 1
        chrom, source, label = fields[:3]
        if label not in LABELS[:-1] or not fields[8].startswith("TIR:") or "_TSD:" not in fields[8]:
            raise WorkflowError(f"Unknown native TIR class/structure at row {line_no}")
        start, end = int(fields[3]), int(fields[4])
        if start < 1 or end < start or fields[6] not in ("+", "-", ".", "?"):
            raise WorkflowError(f"Invalid TIR coordinates at row {line_no}")
        if reference is not None:
            if chrom not in reference or end > len(reference[chrom]):
                raise WorkflowError(f"TIR site outside supplied genome at row {line_no}")
            expected[sequence_key(reference[chrom][start - 1:end])] += 1
        row = dict(native_row=line_no, seqid=chrom, start=start - 1, end=end, label=label,
                   source=source, structural_attributes=fields[8], score_status="not_present")
        if len(fields) == 15:
            if source != "Module4" or any(not re.fullmatch(r"[0-9]+", x) or not 0 <= int(x) <= 10000 for x in fields[9:]):
                raise WorkflowError(f"Invalid v4 CNN score fields at row {line_no}")
            scores = list(map(int, fields[9:]))
            row.update({"score_" + name: value for name, value in zip(LABELS, scores)})
            row["score_status"] = "upstream_scaled_scores_not_calibrated"
            row["top_score_labels"] = ",".join(name for name, value in zip(LABELS, scores) if value == max(scores))
        sites.append(row)
    observed = Counter()
    bases = 0
    for _, seq in fasta(fa, allow_empty=True):
        observed[sequence_key(seq)] += 1
        bases += len(seq)
    if sum(observed.values()) != len(sites):
        raise WorkflowError("TIR FASTA record count differs from annotation")
    if reference is not None and observed != expected:
        raise WorkflowError("TIR native sequences do not match genomic spans (including reverse complements)")
    unique = {(r["seqid"], r["start"], r["end"], r["label"]) for r in sites}
    summary = dict(status="pass", records=len(sites), unique_sites=len(unique), duplicate_site_records=len(sites) - len(unique),
                   bases=bases, classes=dict(Counter(r["label"] for r in sites)), column_counts=dict(columns),
                   sequence_span_check=reference is not None, zero_candidates=not sites,
                   annotation_contract="native_extended_table_not_standard_GFF3",
                   score_labels=list(LABELS), score_scale=10000, score_calibration="not_established")
    return summary, sites


def audit_edta_tir(folder, spec, reference=None):
    folder = Path(folder)
    successful = []
    receipts = sorted((folder / ".teflow-tir").glob("*/calls/*.json"))
    launches = sorted((folder / ".teflow-tir").glob("*/launch.json"))
    if launches:
        latest = max(launches, key=lambda p: read_json(p).get("started", ""))
        for path in (latest.parent / "calls").glob("*.json"):
            call = read_json(path)
            if any(flag in call.get("forwarded", []) for flag in ("-f", "-g", "--genome_file")) and call.get("returncode") != 0:
                raise WorkflowError("The current v4 discovery call did not complete successfully")
    for path in receipts:
        call = read_json(path)
        argv = call.get("forwarded", [])
        if any(flag in argv for flag in ("-f", "-g", "--genome_file")):
            if call.get("returncode") != 0 or call.get("status") != "complete":
                continue
            if (call.get("backend") != "v4-cpu" or call.get("version") != spec["version"]
                    or Path(call.get("tir_prefix", "")).resolve() != Path(spec["prefix"]).resolve()):
                raise WorkflowError("TIR discovery receipt disagrees with the frozen selected backend")
            successful.append(path)
    if not successful:
        raise WorkflowError("No successful actual v4 discovery call recorded; existing output files alone are insufficient")
    native = folder / "genome.fa.mod.EDTA.raw/TIR/TIR-Learner-Result"
    fa, gff = native / "TIR-Learner_FinalAnn.fa", native / "TIR-Learner_FinalAnn.gff3"
    if reference is None:
        reference = dict(fasta(folder / "genome.fa.mod"))
    summary, rows = inspect_native(fa, gff, reference)
    summary.update(backend="v4-cpu", version=spec["version"], verified_discovery_calls=len(successful),
                   biological_accuracy="not_assessed", comparison_to_v3="not_required_for_acceptance",
                   mutations="none; original annotations and scores retained")
    summary["known_limitations"] = ["v4.08 DTA/hAT TSD motif rule is under review; counts are not calibrated biological sensitivity"]
    dest = folder / "tir_audit.json"
    write_json(dest, summary)
    tab = folder / "tir_native_sites.tsv"
    table(tab, rows, ["native_row", "seqid", "start", "end", "label", "source", "structural_attributes", "score_status",
                      *["score_" + name for name in LABELS], "top_score_labels"])
    return summary, [dest, tab, fa, gff, *receipts, *launches]
