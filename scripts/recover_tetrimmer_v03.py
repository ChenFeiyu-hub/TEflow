#!/usr/bin/env python3
"""Audited, one-time v02 -> v03 recovery. Completed EDTA outputs are copied, not recomputed.

The default is a read-only check. --apply installs no packages and launches no genome job.
It prepares TE-Aid's local protein DB, freezes a NEW run and imports hash-verified EDTA/RM
artifacts. Failed TEtrimmer output is never imported or marked complete.
"""
from __future__ import annotations
import argparse
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from teflow.common import (WorkflowError, load_config, read_json, write_json, sha256, digest,
                           work, source_fingerprint)
from teflow.runtime import (config_fingerprint, freeze, stage_cache, finish_stage,
                            release_lock, run)
from teflow.inputs import prepare
from teflow.stages import doctor, dependency_inputs
from teflow.teaid import installed_repeatpeps, prepare_database

AUDITED_V02_SOURCE = "96f56de14b03b50eb0902721782c6ea63a16ec655e4fa02fb6dbe273b1e26019"


def verify_hashes(files, within=None):
    for path, expected in files.items():
        p = Path(path).resolve()
        if within is not None and not p.is_relative_to(Path(within).resolve()):
            raise WorkflowError("Receipt references an out-of-scope artifact: " + str(p))
        if not p.is_file() or sha256(p) != expected:
            raise WorkflowError("Original artifact missing/changed: " + str(p))


def verify_completed(folder):
    folder = Path(folder).resolve()
    if (folder / ".lock").exists():
        raise WorkflowError("Old stage lock exists: " + str(folder))
    record = read_json(folder / "complete.json")
    if record.get("status") != "complete" or digest(record["material"]) != record["fingerprint"]:
        raise WorkflowError("Invalid completed stage receipt: " + str(folder))
    verify_hashes(record["outputs"], folder)
    verify_hashes(record["material"]["inputs"])
    return record


def verify_origin(c):
    root = Path(c["work_root"]) / c["run_id"]
    record = read_json(root / "run_manifest.json")
    if c["run_id"] != "at_pilot_v02" or record["material"]["source_sha256"] != AUDITED_V02_SOURCE:
        raise WorkflowError("Recovery is restricted to the audited v02 source; other runs need separate review")
    if digest(record["material"]) != record["fingerprint"]:
        raise WorkflowError("Old run manifest fingerprint mismatch")
    if config_fingerprint(c) != record["material"]["config_sha256"]:
        raise WorkflowError("Old configuration changed")
    verify_hashes(record["material"]["software"])
    verify_hashes({r["path"]: r["sha256"] for r in record["material"]["databases"]})
    for s in c["samples"]:
        verify_hashes({s[k]: h for k, h in record["material"]["inputs"][s["id"]].items()})
        base = work(c, s["id"])
        prepared = read_json(base / "prepared/manifest.json")
        verify_hashes({str(base / "prepared" / k): v for k, v in prepared["outputs"].items()}, base / "prepared")
        for stage in ("edta", "rm_edta"):
            receipt = verify_completed(base / stage)
            if receipt["material"]["source"] != AUDITED_V02_SOURCE:
                raise WorkflowError("Completed stage came from a different source")
            expected_key = dict(stage=stage, cores=c["execution"]["threads"],
                                parameters=c["parameters"], tools=c["tools"])
            if receipt["material"]["key"] != expected_key:
                raise WorkflowError("Completed stage parameters differ from the audited configuration")
    return record


def import_stage(old, new, sid, stage):
    source = work(old, sid) / stage
    record = verify_completed(source)
    dest = work(new, sid) / stage
    cores = new["execution"]["threads"]
    key = dict(stage=stage, cores=cores, parameters=new["parameters"], tools=new["tools"])
    cached, request = stage_cache(dest, key, dependency_inputs(new, sid, stage))
    if cached:
        raise WorkflowError("Import destination already completed")
    try:
        outputs = []
        for path, expected in record["outputs"].items():
            rel = Path(path).resolve().relative_to(source.resolve())
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            if sha256(target) != expected:
                raise WorkflowError("Imported artifact copy mismatch: " + str(target))
            outputs.append(target)
        provenance = dest / "imported_from.json"
        write_json(provenance, dict(source_run_id=old["run_id"],
                                   source_manifest_sha256=sha256(source / "complete.json"),
                                   source_receipt=record, destination_source=source_fingerprint(),
                                   policy="Audited v0.1.3 to v0.1.4 only; same input sequences, EDTA/RM commands, tools and databases. Copy completed outputs; no failed intermediate reuse."))
        details = dict(record["details"], execution="imported_verified_outputs", source_run_id=old["run_id"])
        finish_stage(dest, request, outputs + [provenance], details)
    finally:
        release_lock(dest)


def no_active_work(root):
    for p in Path("/proc").glob("[0-9]*/cmdline"):
        if int(p.parent.name) == os.getpid():
            continue
        try:
            parts = p.read_bytes().split(b"\0")
            text = b" ".join(parts).decode(errors="replace")
        except (OSError, ProcessLookupError):
            continue
        if str(root) in text and any(x in text for x in ("TEtrimmer.py", "TE-Aid", "EDTA.pl", "RepeatClassifier", "teflow stage", "snakemake/__main__", "run_server.sh")):
            raise WorkflowError("Relevant workflow process still active; inspect PID " + p.parent.name)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--repeatpeps", type=Path)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    if sys.platform != "linux":
        raise WorkflowError("Recovery must run on the Linux server")
    root = a.root.resolve()
    old = load_config(root / "at_pilot_v02.local.json")
    if Path(old["work_root"]).resolve() != root / "work":
        raise WorkflowError("Unexpected work_root for this targeted recovery")
    no_active_work(root)
    origin = verify_origin(old)
    source = a.repeatpeps.resolve() if a.repeatpeps else installed_repeatpeps(old)
    newpath = root / "at_pilot_v03.local.json"
    newroot = root / "work/at_pilot_v03"
    if newpath.exists() or newroot.exists() or (Path(old["results_root"]) / "at_pilot_v03").exists():
        raise WorkflowError("v03 already exists; preserve it and inspect its recovery log instead of overwriting")
    print(json.dumps(dict(old_run_verified=True, repeatpeps_source=str(source),
                          repeatpeps_sha256=sha256(source), action="apply" if a.apply else "check_only")), flush=True)
    if not a.apply:
        return
    os.environ["TEFLOW_REPOSITORY"] = str(REPO)
    os.environ["PYTHONPATH"] = str(REPO / "src") + os.pathsep + os.environ.get("PYTHONPATH", "")
    os.environ["TEFLOW_ALLOW_PRODUCTION"] = "1"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + str(os.getpid())
    logs = root / "repair_logs" / ("tetrimmer-v03-" + stamp)
    logs.mkdir(parents=True, exist_ok=False)
    print("Recovery logs: " + str(logs), flush=True)
    shutil.copy2(old["_config_path"], logs / "v02.original.json")
    installation = prepare_database(old, source, logs / "teaid")
    # None of the old frozen software/database assets may change during DB preparation.
    verify_origin(old)
    new = {k: copy.deepcopy(v) for k, v in old.items() if not k.startswith("_")}
    new["run_id"] = "at_pilot_v03"
    new["description"] = "TE-Aid offline protein DB; original-sequence fallback audit; EDTA/RM copied from verified v02 receipts"
    locked = {r["path"]: r for r in new["databases"]["files"]}
    for path, h in installation["files"].items():
        locked[path] = dict(path=path, sha256=h, bytes=Path(path).stat().st_size, role="teaid_protein")
    new["databases"]["files"] = list(locked.values())
    write_json(newpath, new)
    new = load_config(newpath)
    freeze(new)
    doctor(new, newroot / "doctor", dependency_check=True)
    for s in new["samples"]:
        sid = s["id"]
        prepared = prepare(new, sid)
        previous = read_json(work(old, sid) / "prepared/manifest.json")
        if prepared["outputs"] != previous["outputs"]:
            raise WorkflowError("Prepared genome/CDS changed; old EDTA results cannot be imported")
        for stage in ("edta", "rm_edta"):
            import_stage(old, new, sid, stage)
    write_json(newroot / "recovery_provenance.json", dict(source_run_id=old["run_id"],
               source_fingerprint=origin["fingerprint"], imported=["edta", "rm_edta"],
               recomputed=["prepare"], pending=["tetrimmer", "rm_refined", "tracks", "export"],
               database_install=installation))
    run(["bash", str(REPO / "scripts/run_server.sh"), str(newpath), "--dry-run"],
        REPO, logs / "v03.dry_run.log", 1800)
    (root / "at_pilot_v03.dry_run_passed").write_text(str(newpath) + "\n")
    print("V03 RECOVERY PREPARED AND DRY-RUN PASSED. No genome analysis launched.", flush=True)
    print("Config: " + str(newpath), flush=True)


if __name__ == "__main__":
    try:
        main()
    except (WorkflowError, OSError, KeyError, ValueError) as exc:
        print("Recovery stopped: " + str(exc), file=sys.stderr)
        raise SystemExit(2)
