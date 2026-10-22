"""TEtrimmer 1.7.2 output contracts, including verified original-sequence fallback."""
from __future__ import annotations
import collections
import csv
from pathlib import Path
from .common import WorkflowError, fasta, table, write_json, sha256


def audit_tetrimmer(folder, input_library, *, reviewed_cleanup=None):
    folder = Path(folder)
    summ = folder / "summary.txt"
    lib = folder / "TEtrimmer_consensus_merged.fasta"
    if not summ.is_file() or not lib.is_file():
        raise WorkflowError("TEtrimmer must produce summary.txt and TEtrimmer_consensus_merged.fasta")
    with summ.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not {"input_name", "output_name", "status", "evaluation", "low_copy"} <= set(reader.fieldnames or []):
            raise WorkflowError("Unsupported TEtrimmer summary schema (expected v1.7.2 CSV)")
        rows = list(reader)
    inputs = {n.split("#", 1)[0]: s.upper() for n, s in fasta(input_library)}
    translation = {n: n for n in inputs}
    mapping = folder / "Sequence_name_mapping.txt"
    if mapping.exists():
        with mapping.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f, delimiter="\t")
            if not {"original_input_seq_name", "TEtrimmer_modified_seq_name"} <= set(reader.fieldnames or []):
                raise WorkflowError("Unsupported TEtrimmer name mapping")
            mappings = list(reader)
        translation = {r["original_input_seq_name"].split("#", 1)[0]:
                       r["TEtrimmer_modified_seq_name"].split("#", 1)[0] for r in mappings}
        if len(mappings) != len(translation) or set(translation) != set(inputs):
            raise WorkflowError("TEtrimmer input mapping does not cover the input library uniquely")
    if len(set(translation.values())) != len(translation):
        raise WorkflowError("Ambiguous TEtrimmer name mapping")
    original = {v: k for k, v in translation.items()}
    by_input, by_output = collections.defaultdict(list), collections.defaultdict(list)
    for r in rows:
        by_input[r["input_name"].split("#", 1)[0]].append(r)
        by_output[r["output_name"].split("#", 1)[0]].append(r)
    bad = [r for r in rows if r["status"].strip().lower() not in ("processed", "skipped")]
    if set(original) != set(by_input) or bad:
        raise WorkflowError(f"Incomplete TEtrimmer run: missing={len(set(original)-set(by_input))}, "
                            f"unexpected={len(set(by_input)-set(original))}, nonterminal={len(bad)}")
    rejected = {"Need_check", "Need_ext"}
    provenance, retained = [], set()
    for name, seq in fasta(lib, allow_empty=True):
        base = name.split("#", 1)[0]
        if base in retained:
            raise WorkflowError("Duplicate retained TEtrimmer ID: " + base)
        candidates = by_output.get(base, [])
        # When several attempted subfamilies all fail, upstream can retain their parent.
        parent_fallback = not candidates and base in by_input
        if parent_fallback:
            candidates = by_input[base]
        if not candidates or (len(candidates) != 1 and not parent_fallback):
            raise WorkflowError("Missing/ambiguous TEtrimmer summary for retained sequence: " + base)
        parents = {r["input_name"].split("#", 1)[0] for r in candidates}
        if len(parents) != 1:
            raise WorkflowError("Ambiguous retained TEtrimmer parent: " + base)
        parent = next(iter(parents))
        evaluations = {r["evaluation"].strip() for r in candidates}
        statuses = {r["status"].strip().lower() for r in candidates}
        exact = seq.upper() == inputs[original[parent]]
        is_fallback = bool(evaluations & rejected) or "skipped" in statuses or parent_fallback
        if is_fallback:
            valid_states = all(r["evaluation"].strip() in rejected or r["status"].strip().lower() == "skipped"
                               for r in candidates)
            try:
                copies = [int(r["input_full_blast_n"]) for r in candidates]
            except (KeyError, ValueError):
                copies = []
            if not (base == parent and exact and valid_states and copies and min(copies) >= 2):
                raise WorkflowError("Invalid TEtrimmer original-sequence fallback: " + base)
            origin = "original_input_fallback"
        elif all(r["low_copy"].strip().lower() == "true" for r in candidates):
            if not exact or base != parent:
                raise WorkflowError("Invalid TEtrimmer low-copy original sequence: " + base)
            origin = "original_input_low_copy"
        else:
            if evaluations - {"Good", "Perfect", "Reco_check"} or statuses != {"processed"}:
                raise WorkflowError("Unsupported retained TEtrimmer evaluation/status: " + base)
            origin = "refined_consensus"
        retained.add(base)
        provenance.append(dict(input_name=original[parent], upstream_input_name=parent,
                               output_name=base, evaluation=";".join(sorted(evaluations)),
                               low_copy=";".join(sorted({r["low_copy"] for r in candidates})),
                               status=";".join(sorted(statuses)), sequence_origin=origin,
                               exact_input_match=exact, retained_length=len(seq),
                               summary_output_length=";".join(sorted({r.get("output_length", "") for r in candidates}))))
    # A truncated feedback tail is evidence of an unresolved error, never evidence of a clean run.
    errors = [dict(path=p.relative_to(folder).as_posix(), bytes=p.stat().st_size, sha256=sha256(p))
              for p in sorted(folder.rglob("error_file.txt*")) if p.is_file() and p.stat().st_size]
    # Normal runs remain strict. Only the separately verified, checksum-pinned
    # recovery case can adjudicate its exact error file; there is no CLI ignore flag.
    reviewed = False
    if reviewed_cleanup is not None:
        from .reviewed_teaid_case import CASE
        if (reviewed_cleanup.get("case_id") != CASE["case_id"] or
                reviewed_cleanup.get("status") != "verified_sequence_level_reuse" or
                reviewed_cleanup.get("error_files") != errors or errors != CASE["error_files"] or
                sha256(input_library) != CASE["input_library_sha256"] or
                sha256(lib) != CASE["files"]["upstream/TEtrimmer_consensus_merged.fasta"]):
            raise WorkflowError("Reviewed TE-Aid cleanup does not match the pinned recovery case")
        # Recheck all evidence after copying, not only the sequence count.
        for rel, expected in CASE["files"].items():
            if rel.startswith("upstream/") and rel not in CASE["regenerated_audit_files"]:
                p = folder / rel[len("upstream/"):]
                if not p.is_file() or sha256(p) != expected:
                    raise WorkflowError("Reviewed TE-Aid evidence changed: " + rel)
        reviewed = True
    review = [dict(r, retained=r["output_name"].split("#", 1)[0] in retained,
                   input_retained_as_fallback=any(p["upstream_input_name"] == r["input_name"].split("#", 1)[0]
                                                 and p["sequence_origin"] == "original_input_fallback" for p in provenance)) for r in rows]
    table(folder / "teflow_review.tsv", review,
          list(rows[0]) + ["retained", "input_retained_as_fallback"] if rows else ["retained"])
    table(folder / "teflow_parent_map.tsv", provenance,
          ["input_name", "upstream_input_name", "output_name", "evaluation", "low_copy", "status",
           "sequence_origin", "exact_input_match", "retained_length", "summary_output_length"])
    result = dict(input_families=len(inputs), terminal_inputs=len(by_input), summary_rows=len(rows),
                  retained_families=len(retained), statuses=dict(collections.Counter(r["status"] for r in rows)),
                  evaluations=dict(collections.Counter(r["evaluation"] for r in rows)),
                  retained_origins=dict(collections.Counter(r["sequence_origin"] for r in provenance)),
                  error_files=errors,
                  status="complete_with_reviewed_warning" if reviewed else "quarantined" if errors else "complete_with_review",
                  interpretation="Summary evaluations may describe a rejected extension; retained_length describes the actual FASTA. Labels are not calibrated accuracy.")
    if reviewed:
        result["reviewed_cleanup"] = reviewed_cleanup
    write_json(folder / "teflow_audit.json", result)
    if errors and not reviewed:
        raise WorkflowError("TEtrimmer has nonempty error logs; inspect teflow_audit.json; do not promote to complete: "
                            + ", ".join(r["path"] for r in errors))
    return result
