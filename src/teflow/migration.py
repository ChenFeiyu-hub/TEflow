"""Generic imports accept completed EDTA/RM only; reviewed TE-Aid recovery is separate."""
import os
import platform
import shutil
from pathlib import Path
from .common import WorkflowError, read_json, write_json, sha256, digest, work, sample, now
from .runtime import (freeze, check_frozen, config_fingerprint, software_inventory, stage_cache,
                      finish_stage, release_lock, process_identity, group_alive)
from .inputs import prepare
from .branches import graph


def verify_receipt(folder):
    folder = Path(folder).resolve()
    if (folder / ".lock").exists():
        raise WorkflowError("Source stage is locked: " + str(folder))
    r = read_json(folder / "complete.json")
    if r.get("status") != "complete" or digest(r["material"]) != r["fingerprint"]:
        raise WorkflowError("Source completion receipt is inconsistent")
    for name, h in r["outputs"].items():
        p = Path(name).resolve()
        if not p.is_relative_to(folder) or not p.is_file() or sha256(p) != h:
            raise WorkflowError("Source output changed or outside stage: " + name)
    if not r["outputs"]:
        raise WorkflowError("No source outputs")
    return r


def import_stage(old, new, sid, stage):
    from .stages import dependency_inputs, stage_key
    from .cli import scheduler_marker
    if stage not in ("edta", "rm_edta") or stage not in graph(new):
        raise WorkflowError("0.2 imports only completed EDTA and its unchanged public RM stage")
    if old["run_id"] == new["run_id"] or work(old, sid).resolve() == work(new, sid).resolve():
        raise WorkflowError("Import requires distinct runs")
    if bool(old.get("fixture_only")) != bool(new.get("fixture_only")):
        raise WorkflowError("Cannot import synthetic fixtures into a production run")
    oldroot = Path(old["work_root"]) / old["run_id"]
    origin = read_json(oldroot / "run_manifest.json")
    if origin["fingerprint"] != digest(origin["material"]) or origin["material"]["config_sha256"] != config_fingerprint(old):
        raise WorkflowError("Source run/config fingerprint mismatch")
    for key, expected in origin["material"]["inputs"][sid].items():
        if sha256(sample(old, sid)[key]) != expected:
            raise WorkflowError("Source input changed: " + key)
    freeze(new)
    prepare(new, sid)
    source, target = work(old, sid) / stage, work(new, sid) / stage
    receipt = verify_receipt(source)
    if target.exists() and any(target.iterdir()):
        raise WorkflowError("Import target is not empty; no overwrite permitted")
    oldprep = read_json(work(old, sid) / "prepared/manifest.json")
    for rel, expected in oldprep["outputs"].items():
        if sha256(work(old, sid) / "prepared" / rel) != expected:
            raise WorkflowError("Source prepared reference changed")
    for rel in ("genome.fa", "host.cds.fa"):
        a, b = work(old, sid) / "prepared" / rel, work(new, sid) / "prepared" / rel
        if a.exists() != b.exists() or (a.exists() and sha256(a) != sha256(b)):
            raise WorkflowError("Prepared scientific input differs: " + rel)
    cores = new["execution"]["threads"]
    if receipt["material"]["key"].get("cores") != cores or old["parameters"] != new["parameters"]:
        raise WorkflowError("Discovery/mapping parameters or thread budget differ")
    tool = "edta" if stage == "edta" else "repeatmasker"
    if old["tools"][tool] != new["tools"][tool]:
        raise WorkflowError("Upstream command/version changed")
    fresh_software = software_inventory(new)
    cmd = old["tools"][tool]["command"]
    prefix = str(Path(cmd[cmd.index("-p")+1]).resolve()) + os.sep if "-p" in cmd else None
    checked = 0
    for path, expected in origin["material"]["software"].items():
        if (prefix and str(Path(path)).startswith(prefix)) or path in [str(Path(x).resolve()) for x in cmd if Path(x).is_file()]:
            if fresh_software.get(path) != expected:
                raise WorkflowError("Relevant installed upstream software changed: " + path)
            checked += 1
    if not checked and not new.get("fixture_only"):
        raise WorkflowError("No source software identity evidence for selected upstream tool")
    locked = {r["path"]: r["sha256"] for r in new.get("databases", {}).get("files", [])}
    for entry in old.get("databases", {}).get("files", []):
        if entry.get("role") == "repeat_classification" and locked.get(entry["path"]) != entry["sha256"]:
            raise WorkflowError("Classification database changed")
    if stage == "rm_edta":
        verify_receipt(work(old, sid) / "edta")
        if sha256(work(old, sid) / "edta/library.fa") != sha256(work(new, sid) / "edta/library.fa"):
            raise WorkflowError("RepeatMasker query library differs")
    inputs = dependency_inputs(new, sid, stage)
    if read_json(inputs[3]).get("status") != "pass":
        raise WorkflowError("A passing doctor receipt is required before import")
    cached, request = stage_cache(target, stage_key(new, stage, cores), inputs)
    try:
        outputs = []
        for path in receipt["outputs"]:
            p = Path(path); dest = target / p.resolve().relative_to(source.resolve())
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, dest)
            if sha256(dest) != receipt["outputs"][path]:
                raise WorkflowError("Imported copy changed")
            outputs.append(dest)
        if stage == "rm_edta":
            from .alignment_artifacts import locate_alignment
            auxiliary = locate_alignment(source)
            if auxiliary["path"] and not (target / "genome.fa.align").exists():
                alignment = target / "genome.fa.align"
                shutil.copyfile(auxiliary["path"], alignment)
                if sha256(alignment) != auxiliary["sha256"]:
                    raise WorkflowError("Alignment changed during auxiliary import")
                outputs.append(alignment)
            write_json(target / "alignment_source.json", auxiliary)
            outputs.append(target / "alignment_source.json")
        record = dict(source_run=old["run_id"], source_run_sha256=sha256(oldroot / "run_manifest.json"),
                      source_receipt_sha256=sha256(source / "complete.json"), source_fingerprint=receipt["fingerprint"],
                      verified_upstream_files=checked, stage=stage, imported_at=now(), outputs=receipt["outputs"],
                      compatibility="same staged genome/CDS, parameters, cores, selected command/version, software and classification locks")
        write_json(target / "imported_from.json", record)
        finish_stage(target, request, outputs + [target / "imported_from.json"], dict(receipt["details"], imported_from=old["run_id"]))
        # A second import must not make an unchanged prepared marker newer than
        # the first imported stage and create a spurious downstream rerun DAG.
        prepared = work(new, sid) / "prepared/manifest.json"
        marker = work(new, sid) / ".dag/prepared.done"
        expected_marker = dict(receipt=str(prepared), sha256=sha256(prepared))
        if not marker.is_file() or read_json(marker) != expected_marker:
            scheduler_marker(new, sid, "prepared", prepared)
        scheduler_marker(new, sid, stage, target / "complete.json")
        return record
    except BaseException as e:
        write_json(target / "failed.json", dict(status="failed_import", error=str(e), time=now()))
        raise
    finally:
        release_lock(target)


def unlock_stage(c, sid, stage):
    if stage not in graph(c):
        raise WorkflowError("Unknown enabled stage")
    check_frozen(c)
    folder = work(c, sid) / stage
    lock = folder / ".lock"
    if not lock.is_dir():
        raise WorkflowError("No stage lock exists")
    owner = read_json(lock / "owner.json")
    if owner.get("host") != platform.node():
        raise WorkflowError("Cannot prove a remote-host lock is stale")
    if not owner.get("boot_id") or not owner.get("start_ticks"):
        raise WorkflowError("Owner lacks Linux identity evidence; no lock removed")
    current = process_identity(owner["pid"])
    if not current.get("boot_id"):
        raise WorkflowError("Safe stale-lock verification requires Linux /proc")
    if current.get("boot_id") == owner.get("boot_id") and current.get("start_ticks") and current.get("start_ticks") == owner.get("start_ticks"):
        raise WorkflowError("Stage owner process is still alive")
    for path in folder.rglob("*.command.json"):
        rec = read_json(path)
        if rec.get("status") == "running" and (not rec.get("pid") or group_alive(rec)):
            raise WorkflowError("Unresolved live process group; no lock removed")
    write_json(folder / "stale_lock_review.json", dict(owner=owner, reviewed=now(), action="remove_only_proven_stale_stage_lock"))
    release_lock(folder)
    return dict(status="stale_lock_removed", stage=stage, next="Use --resume after reviewing failed outputs")
