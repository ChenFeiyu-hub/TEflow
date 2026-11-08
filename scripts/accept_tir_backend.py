#!/usr/bin/env python3
"""Accept installed v4 packaging and optionally re-audit a completed experiment.

Runs dependency/model probes, never genome discovery or an installation.
"""
import argparse
import json
from pathlib import Path
import sys
import tarfile

recipes = Path(__file__).resolve().parents[1]
python_root = recipes / "src" if (recipes / "src/teflow").is_dir() else recipes.parent.parent
sys.path.insert(0, str(python_root))
from teflow.common import WorkflowError, fasta, load_config, now, read_json, write_json
from teflow.stages import doctor
from teflow.tir_backend import selected
from teflow.tir_audit import inspect_native


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("config", "output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--completed-experiment", help="Optional existing tir4_full.* directory; read only")
    args = parser.parse_args()
    out = Path(args.output).resolve()
    if sys.platform != "linux" or out.exists():
        parser.error("Use Linux and a new output directory")
    c = load_config(args.config)
    if c["execution"]["mode"] != "server" or c.get("fixture_only") or selected(c)["backend"] != "v4-cpu":
        parser.error("A real server configuration explicitly selecting v4-cpu is required")
    if args.completed_experiment and out.is_relative_to(Path(args.completed_experiment).resolve()):
        parser.error("Write acceptance outside the historical experiment directory")
    out.mkdir(parents=True, exist_ok=False)
    result = dict(started=now(), status="running", config=c["_config_path"], selected_backend=selected(c),
                  genome_analysis_launched=False, installations_performed=False, old_outputs_modified=False,
                  scope="Production adapter dependency/CPU-model checks plus optional historical output audit; not a new end-to-end genome run")
    try:
        result["doctor"] = doctor(c, out / "doctor", dependency_check=True)
        if args.completed_experiment:
            old = Path(args.completed_experiment).resolve()
            report = read_json(old / "report.json")
            if report.get("status") != "FULL_EDTA_COMPARISON_READY":
                raise WorkflowError("Historical experiment is not a completed comparison")
            native = old / "runs/v4/genome.fa.mod.EDTA.raw/TIR/TIR-Learner-Result"
            summary, _ = inspect_native(native / "TIR-Learner_FinalAnn.fa", native / "TIR-Learner_FinalAnn.gff3",
                                        dict(fasta(old / "runs/v4/genome.fa.mod")))
            write_json(out / "historical_native_audit.json", summary)
            result["historical_native_audit"] = dict(summary, source=str(native), genome_run_repeated=False,
                                                      note="Historical output verification, not certification that every dependency build is still identical")
        result["status"] = "TIR4_PACKAGING_ACCEPTANCE_PASSED"
    except Exception as exc:
        result.update(status="TIR4_PACKAGING_ACCEPTANCE_FAILED", error=type(exc).__name__ + ": " + str(exc))
    result["finished"] = now()
    archive = out.with_suffix(out.suffix + ".feedback.tar.gz")
    included, skipped = [], []
    for p in sorted(out.rglob("*")):
        if not p.is_file() or p.is_symlink() or p.suffix not in (".json", ".log"):
            continue
        if p.stat().st_size > 2 * 1024 * 1024:
            skipped.append(str(p.relative_to(out)))
        else:
            included.append(p)
    result.update(feedback=str(archive), feedback_skipped_large_files=skipped)
    write_json(out / "acceptance.json", result)
    included.append(out / "acceptance.json")
    with tarfile.open(archive, "x:gz") as tf:
        for p in included:
            tf.add(p, arcname=str(p.relative_to(out)), recursive=False)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "TIR4_PACKAGING_ACCEPTANCE_PASSED" else 1


if __name__ == "__main__":
    sys.exit(main())
