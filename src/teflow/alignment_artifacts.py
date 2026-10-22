"""Find alignment auxiliaries without recomputing or rewriting old receipts."""
from pathlib import Path
from .common import WorkflowError, read_json, sha256


def locate_alignment(folder):
    folder = Path(folder).resolve()
    out = folder / "genome.fa.out"
    command = folder / "run.log.command.json"
    if not out.is_file():
        raise WorkflowError("RepeatMasker .out missing: " + str(out))
    expected_out = sha256(out)
    candidates = [folder]
    if command.is_file():
        record = read_json(command)
        if record.get("cwd") and record.get("returncode") == 0 and "-a" in record.get("argv", []):
            candidates.append(Path(record["cwd"]).resolve())
    checked = []
    for source in dict.fromkeys(candidates):
        alignment = source / "genome.fa.align"
        checked.append(str(alignment))
        if not alignment.is_file() or not alignment.stat().st_size:
            continue
        if source != folder:
            if (not (source / out.name).is_file() or sha256(source / out.name) != expected_out
                    or not (source / command.name).is_file() or sha256(source / command.name) != sha256(command)):
                raise WorkflowError("Original alignment directory does not match imported .out/command: " + str(source))
        receipt_path = source / "complete.json"
        locked = {Path(p).resolve(): h for p, h in read_json(receipt_path).get("outputs", {}).items()} if receipt_path.exists() else {}
        expected = locked.get(alignment.resolve())
        actual = sha256(alignment)
        if expected and actual != expected:
            raise WorkflowError("Receipt-locked alignment changed: " + str(alignment))
        return dict(status="available", path=str(alignment), sha256=actual,
                    receipt_locked=bool(expected), evidence="original_receipt" if expected else "auxiliary_hash_recorded_now",
                    matched_out_sha256=expected_out, source_directory=str(source), checked_paths=checked)
    return dict(status="not_available_legacy_or_no_hits", path=None, checked_paths=checked,
                action="Inspect original execution directory or archives; no automatic rerun")
