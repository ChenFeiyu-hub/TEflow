"""Exact-case recovery of a completed TEtrimmer run quarantined on cleanup stderr.

Original failed receipts and artifacts stay immutable. The new run records the
actual producer separately from its future isolated TE-Aid execution command.
"""
from __future__ import annotations
import copy
import os
from pathlib import Path
import shutil
import tempfile

from .common import (WorkflowError, ID, read_json, write_json, sha256, digest,
                     work, sample, now, fasta, load_config, source_fingerprint)
from .runtime import (config_fingerprint, freeze, stage_cache, finish_stage, release_lock)
from .reviewed_teaid_case import CASE


def verify_files(folder, files):
    folder = Path(folder).resolve()
    for rel, expected in files.items():
        path = (folder / rel).resolve()
        if not path.is_relative_to(folder) or not path.is_file() or sha256(path) != expected:
            raise WorkflowError("Reviewed evidence missing/changed: " + rel)


def no_active_work(c):
    root = Path(c["work_root"]) / c["run_id"]
    if any(root.glob("*/*/.lock")):
        raise WorkflowError("Old stage lock exists; resolve active work before recovery")
    for p in Path("/proc").glob("[0-9]*/cmdline"):
        if int(p.parent.name) == os.getpid():
            continue
        try:
            text = p.read_bytes().replace(b"\0", b" ").decode(errors="replace")
            cwd = (p.parent / "cwd").resolve()
        except OSError:
            continue
        related = str(root) in text or c["_config_path"] in text or cwd.is_relative_to(root)
        if related and any(x in text for x in ("snakemake", "run_server.sh", "TEtrimmer.py", "TE-Aid", "teflow stage")):
            raise WorkflowError("Old run still has an active process: PID " + p.parent.name)


def copy_evidence(source, target):
    """Copy only pinned evidence. Keep previous failure/audit records separately."""
    source, target = Path(source), Path(target)
    outputs = []
    archived = {"request.json", "failed.json", *CASE["regenerated_audit_files"]}
    for rel, expected in CASE["files"].items():
        dest = target / ("source_evidence/" + rel if rel in archived else rel)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / rel, dest)
        if sha256(dest) != expected:
            raise WorkflowError("Copied reviewed artifact differs: " + rel)
        outputs.append(dest)
    return outputs


def validate_reviewed_outputs(folder, input_library):
    """Read-only verification of the complete pinned case, including MSA consensus."""
    from .tetrimmer_audit import audit_tetrimmer
    folder = Path(folder)
    verify_files(folder, CASE["files"])
    if sha256(input_library) != CASE["input_library_sha256"]:
        raise WorkflowError("Reviewed input library changed")
    errors = [dict(path=p.relative_to(folder / "upstream").as_posix(), bytes=p.stat().st_size, sha256=sha256(p))
              for p in sorted((folder / "upstream").rglob("error_file.txt*")) if p.is_file() and p.stat().st_size]
    if errors != CASE["error_files"]:
        raise WorkflowError("Additional or changed error evidence; no recovery permitted")
    command = read_json(folder / "run.log.command.json")
    if command.get("status") != "complete" or command.get("returncode") != 0:
        raise WorkflowError("Original TEtrimmer command did not complete successfully")
    # Reproduce the published A/C/G/T-only majority consensus without importing
    # upstream executables or changing the original output files.
    sequences, chunks = [], []
    for line in (folder / CASE["affected_msa"]).read_text(encoding="ascii").splitlines():
        if line.startswith(">"):
            if chunks:
                sequences.append("".join(chunks).upper())
            chunks = []
        else:
            chunks.append(line.strip())
    if chunks:
        sequences.append("".join(chunks).upper())
    if len(sequences) != CASE["sequence_count"] or {len(s) for s in sequences} != {CASE["consensus_length"]}:
        raise WorkflowError("Affected alignment dimensions changed")
    consensus = []
    for column in zip(*sequences):
        counts = {b: column.count(b) for b in "ACGT"}
        total = sum(counts.values()); best = max(counts, key=counts.get)
        consensus.append(best if total and counts[best] / total >= CASE["consensus_threshold"] else "N")
    library = {n.split("#", 1)[0]: s for n, s in fasta(folder / "upstream/TEtrimmer_consensus_merged.fasta")}
    if library.get(CASE["affected_id"]) != "".join(consensus):
        raise WorkflowError("Affected final sequence does not match the proof alignment")
    review = dict(case_id=CASE["case_id"], status="verified_sequence_level_reuse", error_files=errors,
                  affected_id=CASE["affected_id"], msa_consensus_exact=True,
                  scope=CASE["review_scope"], orf_tables=CASE["orf_tables"],
                  evidence_sha256=CASE["files"], biological_validation="not_established")
    with tempfile.TemporaryDirectory(prefix="teflow-review-") as tmp:
        copy_evidence(folder, tmp)
        result = audit_tetrimmer(Path(tmp) / "upstream", input_library, reviewed_cleanup=review)
    if any(result[k] != v for k, v in CASE["expected_counts"].items()):
        raise WorkflowError("Reviewed library counts changed")
    if result["retained_origins"] != CASE["expected_origins"]:
        raise WorkflowError("Reviewed sequence provenance changed")
    return review


def verify_origin(old):
    from .migration import verify_receipt
    if (old["run_id"] != CASE["source_run_id"] or old.get("fixture_only") or
            config_fingerprint(old) != CASE["source_config_sha256"]):
        raise WorkflowError("Recovery is restricted to the reviewed at_compare_v021 configuration")
    root = Path(old["work_root"]) / old["run_id"]
    origin = read_json(root / "run_manifest.json")
    if (sha256(root / "run_manifest.json") != CASE["source_manifest_sha256"] or
            digest(origin["material"]) != origin["fingerprint"] or
            origin["material"]["source_sha256"] != CASE["source_sha256"]):
        raise WorkflowError("Source run identity differs from the reviewed evidence")
    no_active_work(old)
    folder = work(old, CASE["sample"]) / "tetrimmer"
    if (folder / "complete.json").exists():
        raise WorkflowError("Source stage has been promoted outside this recovery; preserve and review it")
    request = read_json(folder / "request.json")
    if request["fingerprint"] != CASE["source_request_fingerprint"] or digest(request["material"]) != request["fingerprint"]:
        raise WorkflowError("Source request fingerprint differs")
    print("Verifying frozen inputs, installed software and databases; no download or genome analysis...", flush=True)
    hashes = dict(origin["material"]["software"])
    hashes.update({r["path"]: r["sha256"] for r in origin["material"]["databases"]})
    hashes.update(request["material"]["inputs"])
    for sid, entries in origin["material"]["inputs"].items():
        if sid == "_qc":
            hashes.update({old["qc"][k]: h for k, h in entries.items()})
        else:
            hashes.update({sample(old, sid)[k]: h for k, h in entries.items()})
    for path, expected in hashes.items():
        if not Path(path).is_file() or sha256(path) != expected:
            raise WorkflowError("Original frozen asset changed: " + path)
    for stage in ("edta", "rm_edta"):
        verify_receipt(work(old, CASE["sample"]) / stage)
    return validate_reviewed_outputs(folder, work(old, CASE["sample"]) / "edta/library.fa")


def new_configuration(old, output, run_id, repo):
    output, repo = Path(output).resolve(), Path(repo).resolve()
    if not ID.fullmatch(run_id) or run_id == old["run_id"] or output.exists():
        raise WorkflowError("A new configuration and run ID are required; nothing is overwritten")
    if any((Path(old[k]) / run_id).exists() for k in ("work_root", "results_root")):
        raise WorkflowError("Destination run already exists; inspect it before any further operation")
    c = {k: copy.deepcopy(v) for k, v in old.items() if not k.startswith("_")}
    c["run_id"] = run_id
    command = c["tools"]["tetrimmer"]["command"]
    if len(command) != 5 or command[1:3] != ["run", "-p"] or command[-1] != "TEtrimmer":
        raise WorkflowError("Expected the audited original TEtrimmer environment command")
    wrapper = repo / "scripts/run_tetrimmer_isolated.sh"
    if not wrapper.is_file():
        raise WorkflowError("Isolation wrapper is missing")
    command[-1] = str(wrapper)
    if "hite" in c["tools"]:
        hite = c["tools"]["hite"]
        indices = [i for i, v in enumerate(hite["command"]) if Path(v).name == "run_hite_container.py"]
        if len(indices) != 1:
            raise WorkflowError("Unexpected HiTE wrapper command")
        new = repo / "scripts/run_hite_container.py"
        if sha256(new) != sha256(hite["command"][indices[0]]):
            raise WorkflowError("HiTE wrapper content must remain unchanged")
        hite["command"][indices[0]] = str(new)
        hite["probe_command"] = hite["command"] + ["--teflow-probe"]
    c["description"] = (str(c.get("description", "")) + " | Reviewed TE-Aid cleanup recovery from " + old["run_id"] +
                        "; old run preserved; existing ET sequences reused without rerunning discovery.").strip(" |")
    return c


def import_reviewed_tetrimmer(old, new, review):
    from .stages import dependency_inputs, stage_key
    from .cli import scheduler_marker
    from .formats import canonical_library
    from .tetrimmer_audit import audit_tetrimmer
    sid = CASE["sample"]
    source, target = work(old, sid) / "tetrimmer", work(new, sid) / "tetrimmer"
    # Repeat the small evidence checks immediately before copying and issuing a receipt.
    verified = validate_reviewed_outputs(source, work(old, sid) / "edta/library.fa")
    if verified != review:
        raise WorkflowError("Review record changed during recovery")
    if sha256(work(new, sid) / "edta/library.fa") != CASE["input_library_sha256"]:
        raise WorkflowError("Destination EDTA library differs from reviewed input")
    if target.exists() and any(target.iterdir()):
        raise WorkflowError("Reviewed import target is not empty")
    inputs = dependency_inputs(new, sid, "tetrimmer")
    if read_json(inputs[3]).get("status") != "pass":
        raise WorkflowError("Passing destination doctor is required")
    cached, request = stage_cache(target, stage_key(new, "tetrimmer", new["execution"]["threads"]), inputs)
    if cached:
        raise WorkflowError("Reviewed import destination already completed")
    try:
        outputs = copy_evidence(source, target)
        details = audit_tetrimmer(target / "upstream", work(new, sid) / "edta/library.fa", reviewed_cleanup=review)
        canonical_library(target / "upstream/TEtrimmer_consensus_merged.fasta", target / "library.fa", "T", "TEtrimmer-1.7.2")
        record = dict(case_id=CASE["case_id"], imported_at=now(), source_run=old["run_id"],
                      source_sha256=CASE["source_sha256"], destination_source_sha256=source_fingerprint(),
                      actual_production_command=read_json(source / "run.log.command.json"),
                      future_execution_command=new["tools"]["tetrimmer"]["command"],
                      computation_rerun=False, sequence_content_changed=False,
                      compatibility=CASE["future_execution"], review=review)
        write_json(target / "reviewed_import.json", record)
        write_json(target / "upstream/reviewed_cleanup.json", review)
        outputs += [target / n for n in ("library.fa", "library.fa.provenance.tsv", "reviewed_import.json",
                    "upstream/reviewed_cleanup.json", "upstream/teflow_audit.json", "upstream/teflow_review.tsv", "upstream/teflow_parent_map.tsv")]
        details.update(execution="reviewed_import_without_rerun", imported_from=old["run_id"], warning_preserved=True)
        finish_stage(target, request, outputs, details)
        scheduler_marker(new, sid, "tetrimmer", target / "complete.json")
        return record
    except BaseException as e:
        write_json(target / "failed.json", dict(status="failed_reviewed_import", error=str(e), time=now()))
        raise
    finally:
        release_lock(target)


def recover(config, output, run_id, repo, apply=False):
    if os.name != "posix" or not Path("/proc").is_dir():
        raise WorkflowError("Server recovery requires Linux")
    old = load_config(config)
    c = new_configuration(old, output, run_id, repo)
    review = verify_origin(old)
    if not apply:
        return dict(status="review_passed", action="check_only", review=review, computation_launched=False)
    # The new namespace alone is mutated. No installs, changes to installed
    # upstream source, error deletion, or old receipt changes occur here.
    write_json(output, c)
    new = load_config(output)
    from .stages import doctor
    from .migration import import_stage
    root = Path(new["work_root"]) / new["run_id"]
    doctor(new, root / "doctor", dependency_check=True)
    freeze(new)
    for stage in ("edta", "rm_edta"):
        print("Importing verified " + stage + "...", flush=True)
        import_stage(old, new, CASE["sample"], stage)
    no_active_work(old)
    import_reviewed_tetrimmer(old, new, review)
    # A source hash check at completion documents that no old evidence was rewritten.
    verify_files(work(old, CASE["sample"]) / "tetrimmer", CASE["files"])
    return dict(status="reviewed_recovery_prepared", config=str(Path(output).resolve()),
                run_id=run_id, preserved_source=old["run_id"], imported=["edta", "rm_edta", "tetrimmer"],
                computation_launched=False, next="Dry-run ET target, then run downstream RM/QC/export")
