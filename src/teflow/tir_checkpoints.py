"""Bounded offline inspection of native v4 checkpoints; never reclassifies TEs."""
import argparse
import csv
import gzip
import json
from pathlib import Path
import re
from .common import WorkflowError, table, write_json

CHECKPOINTS = ("TIRVish_json.txt.gz", "GRF_json.txt.gz", "post_CNN_TIRVish_json.txt.gz", "post_CNN_GRF_json.txt.gz")


def candidates(data):
    """v4.08: chunk-local closed coordinates including TSDs -> genome BED without TSDs."""
    fields = ("seq_start_incl_tsd", "seq_stop_incl_tsd", "tsd1_size", "tsd2_size", "tir1_size", "tir2_size")
    if not isinstance(data, dict):
        raise WorkflowError("Checkpoint root is not an object")
    for chunk, blocks in data.items():
        for seqid, block in blocks.items():
            if not all(isinstance(block.get(k), list) for k in fields):
                raise WorkflowError("Unrecognized v4 checkpoint arrays")
            n = len(block[fields[0]])
            optional = [k for k in ("final_tir_label", "cnn_scores", "sequence_kept_after_overlaps") if k in block]
            if any(len(block[k]) != n for k in (*fields, *optional)):
                raise WorkflowError("Checkpoint candidate array lengths disagree")
            offset = block.get("chunking_offset")
            if type(offset) is not int or offset < 0:
                raise WorkflowError("Missing/invalid chunking offset")
            for i in range(n):
                s, e, t1, t2, r1, r2 = [block[k][i] for k in fields]
                if any(type(v) is not int for v in (s, e, t1, t2, r1, r2)) or min(t1, t2, r1, r2) < 0:
                    raise WorkflowError("Invalid candidate coordinates or lengths")
                start, end = s + t1 + offset - 1, e - t2 + offset
                if s < 1 or start < 0 or end <= start:
                    raise WorkflowError("Invalid candidate genomic interval")
                row = dict(chunk=str(chunk), seqid=re.sub(r";;\d+", "", seqid), start=start, end=end,
                           native_index=i, tsd1_size=t1, tsd2_size=t2, tir1_size=r1, tir2_size=r2)
                row.update({k: block[k][i] for k in optional})
                yield row


def audit(native_dir, sites_file, output, max_mib=128, max_matches=10000):
    native_dir, sites_file, output = map(Path, (native_dir, sites_file, output))
    if output.exists():
        raise WorkflowError("Use a new audit output directory")
    if output.resolve().is_relative_to(native_dir.resolve()):
        raise WorkflowError("Write the audit outside the native results directory")
    if not native_dir.is_dir() or not 1 <= max_mib <= 512 or not 1 <= max_matches <= 100000:
        raise WorkflowError("Missing native directory or invalid bounded audit limits")
    with sites_file.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        if not {"alias", "start_0based", "end_exclusive"} <= set(reader.fieldnames or []):
            raise WorkflowError("Sites need alias, start_0based, end_exclusive columns")
        targets = []
        for i, source in enumerate(reader, 1):
            row = dict(site=i, alias=source["alias"], start=int(source["start_0based"]), end=int(source["end_exclusive"]))
            if not row["alias"] or row["start"] < 0 or row["end"] <= row["start"] or i > 10000:
                raise WorkflowError("Invalid site interval or too many sites")
            targets.append(row)
    if not targets:
        raise WorkflowError("Empty audit site list")
    by_chrom = {}
    for row in targets:
        by_chrom.setdefault(row["alias"], []).append(row)
    records, counts, matches = [], [], []
    for name in CHECKPOINTS:
        path = native_dir / name
        rec = dict(file=name, path=str(path.resolve()), status="missing")
        per_site = {t["site"]: dict(site=t["site"], checkpoint=name, exact=0, overlap=0, reciprocal_80pct=0) for t in targets}
        if path.is_file():
            try:
                with gzip.open(path, "rb") as stream:
                    text = stream.read(max_mib * 1024 * 1024 + 1)
                if len(text) > max_mib * 1024 * 1024:
                    raise WorkflowError("Checkpoint exceeds the decompressed size limit; no absence inference allowed")
                data = json.loads(text)
                total, selected_count, file_matches = 0, 0, []
                for candidate in candidates(data):
                    total += 1
                    for t in by_chrom.get(candidate["seqid"], []):
                        overlap = min(candidate["end"], t["end"]) - max(candidate["start"], t["start"])
                        if overlap <= 0:
                            continue
                        selected_count += 1
                        count = per_site[t["site"]]
                        count["overlap"] += 1
                        count["exact"] += (candidate["start"], candidate["end"]) == (t["start"], t["end"])
                        a, b = overlap / (t["end"] - t["start"]), overlap / (candidate["end"] - candidate["start"])
                        count["reciprocal_80pct"] += a >= .8 and b >= .8
                        if len(matches) + len(file_matches) < max_matches:
                            file_matches.append(dict(candidate, site=t["site"], checkpoint=name, overlap_bp=overlap,
                                                target_fraction=a, candidate_fraction=b))
                rec.update(status="read", total_candidates=total, target_matches=selected_count)
                matches.extend(file_matches)
                counts.extend(dict(v, status="read") for v in per_site.values())
            except (OSError, ValueError, TypeError, KeyError, AttributeError, WorkflowError) as exc:
                rec.update(status="unavailable", error=type(exc).__name__ + ": " + str(exc))
        if rec["status"] != "read":
            counts.extend(dict(site=t["site"], checkpoint=name, status=rec["status"], exact=None, overlap=None, reciprocal_80pct=None) for t in targets)
        records.append(rec)
    output.mkdir(parents=True, exist_ok=False)
    table(output / "sites.tsv", targets, ["site", "alias", "start", "end"])
    table(output / "checkpoint_counts.tsv", counts, ["site", "checkpoint", "status", "exact", "overlap", "reciprocal_80pct"])
    write_json(output / "matches.json", matches)
    total_matches = sum(r.get("target_matches", 0) for r in records)
    result = dict(status="AUDIT_READY" if all(r["status"] == "read" for r in records) else "AUDIT_PARTIAL",
                  files=records, sites=len(targets), matches=total_matches, matches_saved=len(matches),
                  match_details_truncated=total_matches > len(matches), coordinates="0-based half-open, excluding TSDs",
                  limits=dict(max_uncompressed_mib_per_file=max_mib, max_saved_matches=max_matches),
                  biological_truth="not_assessed", upstream_mutations=False,
                  interpretation="Pre-checkpoint presence versus post-checkpoint absence does not distinguish CNN rejection from TIR/TSD filters. Overlap is not identity. Missing/unreadable files are not zero calls.")
    write_json(output / "audit.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("native-dir", "sites", "output"):
        parser.add_argument("--" + key, required=True)
    parser.add_argument("--max-mib", type=int, default=128)
    parser.add_argument("--max-matches", type=int, default=10000)
    args = parser.parse_args()
    try:
        print(json.dumps(audit(args.native_dir, args.sites, args.output, args.max_mib, args.max_matches), indent=2))
        return 0
    except (WorkflowError, OSError, ValueError) as exc:
        parser.exit(2, str(exc) + "\n")
