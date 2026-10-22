"""Public command line; computational tools are never launched by validation."""
from __future__ import annotations
import argparse
import json
import os
import shutil
import sys
import tarfile
from pathlib import Path
from . import __version__
from .common import WorkflowError, load_config, read_json, write_json, sha256, work, now
from .inputs import audit_sample, prepare
from .runtime import freeze, PFAM_FILES
from .stages import STAGES, doctor, execute
from .branches import BRANCHES, DEFAULT_BRANCHES, graph, enabled, required_tools

VERSIONS = {"edta": "2.3.0", "tetrimmer": "1.7.2", "repeatmasker": "4.2.4", "trf": "4.10.0", "dustmasker": "2.17.0"}
OPTIONAL_VERSIONS = {"heliano": "1.3.1", "heliano_cons": "1.0.2", "hite": "3.3.3", "diamond": "2.1.11", "hmmscan": "3.4"}


def configure_v2(c, env_root, micromamba, profile="arabidopsis-compare", image=None, protein_qc=False, names=None):
    env = Path(env_root).resolve()
    root = Path(c["work_root"]).parent
    from .assets import asset_root
    repo = asset_root()
    names = names if names is not None else DEFAULT_BRANCHES if profile == "arabidopsis-compare" else ["edta", "edta_tetrimmer"]
    c.update(schema_version=2, branches={b: dict(enabled=b in names) for b in BRANCHES},
             qc=dict(host_proteins="derived" if protein_qc else None, te_proteins=None, pfam=False, evalue=1e-5),
             evaluation=dict(promoter_analysis=False, promoter_upstream=1500, promoter_near=500, widths=list(range(4, 21))))
    if "edta_tetrimmer" in names:
        c["tools"]["tetrimmer"] = dict(
            command=[micromamba, "run", "-p", str(env / "tetrimmer"), "bash",
                     str(repo / "scripts/run_tetrimmer_isolated.sh")], expected_version="1.7.2")
    for name in ("heliano", "heliano_cons"):
        if "heliano" in names:
            c["tools"][name] = dict(command=[micromamba, "run", "-p", str(env / "heliano"), name], expected_version=OPTIONAL_VERSIONS[name])
    if "hite" in names:
        image = str(Path(image).resolve()) if image else str(root / "containers/hite-3.3.3.sif")
        cmd = [micromamba, "run", "-p", str(env / "engine"), "python", str(repo / "scripts/run_hite_container.py"), "--image", image, "--bind", str(root), "--"]
        c["tools"]["hite"] = dict(command=cmd, expected_version="3.3.3", image=image, probe_command=cmd + ["--teflow-probe"])
        if Path(image).is_file():
            from .hite_image import inspect_image
            print("Reading HiTE image fingerprint...", file=sys.stderr, flush=True)
            identity = inspect_image(image)
            c["tools"]["hite"]["image_identity"] = identity
            if identity["recognized"]:
                c["tools"]["hite"]["expected_version"] = identity["reported_version"]
    if protein_qc:
        c["tools"]["diamond"] = dict(command=[micromamba, "run", "-p", str(env / "qc"), "diamond"], expected_version=OPTIONAL_VERSIONS["diamond"])
    return c


def server_config(args):
    root, env, data = (Path(getattr(args, k)).expanduser().resolve() for k in ("root", "env_root", "data_root"))
    samples = [dict(id="arabidopsis_TAIR10", genome=str(data / "arabidopsis" / "TAIR10.fa"),
                    annotation=str(data / "arabidopsis" / "Araport11.gtf"), exclude_seqids=["Mt", "Pt"], derive_cds=True),
               dict(id="chlamydomonas_CC4532_v6", genome=str(data / "chlamydomonas" / "CreinhardtiiCC_4532_707_v6.0.fa"),
                    annotation=str(data / "chlamydomonas" / "CreinhardtiiCC_4532_707_v6.1.gene_exons.gff3"),
                    exclude_seqids=["plastome", "mitogenome", "mating_type_plus"], derive_cds=True)]
    samples = samples if args.sample == "both" else [samples[0 if args.sample == "arabidopsis" else 1]]
    providers = {"edta": ("edta", "EDTA.pl"), "tetrimmer": ("tetrimmer", "TEtrimmer"),
                 "repeatmasker": ("masking", "RepeatMasker"), "trf": ("masking", "trf"), "dustmasker": ("masking", "dustmasker")}
    tools = {k: dict(command=[args.micromamba, "run", "-p", str(env / provider), binary],
                     expected_version=VERSIONS[k]) for k, (provider, binary) in providers.items()}
    c = dict(schema_version=1, run_id=args.run_id, work_root=str(root / "work"), results_root=str(root / "results"),
             samples=samples, tools=tools, execution=dict(mode="server", threads=args.threads, mem_mb=args.mem_mb),
             parameters=dict(max_divergence=40), databases=dict(pfam_dir=str(root / "databases" / "pfam"), files=[]))
    profile = getattr(args, "profile", "baseline")
    if profile == "arabidopsis-compare" and args.sample != "arabidopsis":
        raise WorkflowError("The 0.2 comparison profile is scoped to Arabidopsis; use baseline for other samples")
    configure_v2(c, env, args.micromamba, profile, getattr(args, "hite_image", None), getattr(args, "protein_qc", False))
    c["evaluation"]["promoter_analysis"] = getattr(args, "promoter_analysis", False)
    if Path(args.output).exists():
        raise WorkflowError("Refusing to overwrite configuration: " + args.output)
    write_json(args.output, c)
    return dict(config=str(Path(args.output).resolve()), next="Install dependencies, configure databases, lock-databases, doctor, then dry-run")


def lock_databases(args):
    path = Path(args.config).resolve()
    c = read_json(path)
    active = required_tools(c)
    pfam = Path(args.pfam_dir).resolve() if args.pfam_dir else None
    if active & {"tetrimmer", "hmmscan"} and pfam is None:
        raise WorkflowError("Enabled TEtrimmer/Pfam QC requires --pfam-dir")
    candidates = [(pfam / name, "pfam") for name in PFAM_FILES] if pfam else []
    for value in args.classification_dir or []:
        root = Path(value).resolve()
        if not root.is_dir():
            raise WorkflowError("Classification database directory missing: " + str(root))
        candidates += [(p, "repeat_classification") for p in sorted(root.rglob("*")) if p.is_file() and p.suffix.lower() not in {".log", ".lock", ".tmp", ".pyc"}]
    for value in args.extra_dir or []:
        root = Path(value).resolve()
        if not root.is_dir():
            raise WorkflowError("Extra database directory missing: " + str(root))
        candidates += [(p, "additional_tool_database") for p in sorted(root.rglob("*")) if p.is_file()]
    from .teaid import database_prefix, database_files
    if "tetrimmer" in active:
        candidates += [(p, "teaid_protein") for p in database_files(database_prefix(c))]
    files = {}
    for p, role in candidates:
        if not p.is_file() or not p.stat().st_size:
            raise WorkflowError("Database asset missing/empty: " + str(p))
        files[str(p)] = dict(path=str(p), role=role, sha256=sha256(p), bytes=p.stat().st_size)
    if active & {"edta", "tetrimmer"} and not any(r["role"] == "repeat_classification" for r in files.values()):
        raise WorkflowError("No classification database files found")
    c["databases"] = dict(pfam_dir=str(pfam) if pfam else None, files=list(files.values()),
                          inventory_note="User-specified actual installed databases; verify each upstream environment points here")
    write_json(path, c)
    return dict(config=str(path), database_files=len(files), total_bytes=sum(r["bytes"] for r in files.values()),
                next="Do not modify these database files during the run")


def feedback(c, output):
    """Small diagnostics, no genome, alignments or potentially huge stdout bundles."""
    target = Path(output).resolve()
    if target.exists():
        raise WorkflowError("Refusing to overwrite feedback archive")
    target.parent.mkdir(parents=True, exist_ok=True)
    roots = [(Path(c["work_root"]) / c["run_id"], "work"),
             (Path(c["results_root"]) / c["run_id"], "results")]
    selected, omitted = [], []
    allowed_names = {"run_manifest.json", "recovery_provenance.json", "imported_from.json", "doctor.json", "complete.json", "failed.json", "request.json", "manifest.json", "adapter_audit.json", "evaluation.json", "classification_inventory.tsv", "library_qc.tsv", "regional_evaluation.tsv", "branch_discordance.tsv", "parents.tsv", "library.parents.tsv", "native_sites.tsv",
                     "summary.txt", "Sequence_name_mapping.txt", "teflow_audit.json", "comparison.tsv", "comparison.json", "qc.json", "teflow_review.tsv", "teflow_parent_map.tsv", "seqids.tsv", "input_seqids.tsv", "reviewed_cleanup.json", "reviewed_import.json"}
    allowed_names.update({'coverage_layers.tsv','status.json','metrics.jsonl','preview.json','cancel.json','scheduler.log'})
    with tarfile.open(target, "w:gz") as archive:
        archive.add(c["_config_path"], arcname="configuration.json")
        for root, label in roots:
            if not root.exists():
                continue
            for p in sorted(root.rglob("*")):
                if p.is_file() and (p.name in allowed_names or (p.parent.name == 'launches' and p.suffix == '.json') or p.name.endswith(".command.json") or p.name == "error_file.txt" or (p.suffix == ".log" and (p.parent.name in set(graph(c)) | {"doctor"} or "doctor" in p.relative_to(root).parts))):
                    name = label + "/" + str(p.relative_to(root)).replace("\\", "/")
                    if p.stat().st_size <= 2 * 1024 * 1024:
                        archive.add(p, arcname=name)
                        selected.append(name)
                    else:
                        # Keep a bounded tail for large tool logs, never silently discard failures.
                        import io, tarfile as tf
                        with p.open("rb") as f:
                            f.seek(-128*1024, 2)
                            content = f.read()
                        info = tf.TarInfo(name + ".tail.txt")
                        info.size = len(content)
                        archive.addfile(info, io.BytesIO(content))
                        omitted.append(dict(path=name, bytes=p.stat().st_size, retained_tail_bytes=len(content)))
        import io
        raw = json.dumps(dict(created=now(), files=selected, truncated=omitted,
                              note="Genome, full alignments, database files and environment packages excluded"), indent=2).encode()
        info = tarfile.TarInfo("archive_inventory.json"); info.size = len(raw)
        archive.addfile(info, io.BytesIO(raw))
    return dict(archive=str(target), selected_files=len(selected), truncated_files=len(omitted))


def main(argv=None):
    p = argparse.ArgumentParser(prog="teflow", description="Auditable wrappers for published TE tools; no local production by default")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="action", required=True)
    for name in ("validate-inputs", "prepare", "freeze", "doctor", "stage", "pack-feedback", "settings", "plan", "status", "targets", "unlock-stage"):
        q = sub.add_parser(name)
        q.add_argument("--config", required=True)
        if name in ("validate-inputs", "doctor", "pack-feedback"):
            q.add_argument("--output", required=True)
        if name == "doctor":
            q.add_argument("--dependencies", action="store_true")
        if name in ("prepare", "stage", "unlock-stage"):
            q.add_argument("--sample", required=True)
        if name == "stage":
            q.add_argument("--name", required=True)
            q.add_argument("--threads", type=int)
            q.add_argument("--resume", action="store_true")
        if name == "unlock-stage":
            q.add_argument("--name", required=True)
        if name == "targets":
            q.add_argument("--name", required=True)
        if name == "settings":
            q.add_argument("--key", choices=("threads", "mem_mb", "run_root"), required=True)
    q = sub.add_parser("init-server")
    for k in ("root", "env-root", "data-root", "output"):
        q.add_argument("--" + k, required=True)
    q.add_argument("--mem-mb", required=True, type=int)
    q.add_argument("--threads", default=32, type=int)
    q.add_argument("--run-id", default="pilot_v01")
    q.add_argument("--micromamba", default="micromamba")
    q.add_argument("--sample", choices=("arabidopsis", "chlamydomonas", "both"), default="arabidopsis")
    q.add_argument("--profile", choices=("baseline", "arabidopsis-compare"), default="baseline")
    q.add_argument("--hite-image")
    q.add_argument("--protein-qc", action="store_true")
    q.add_argument("--promoter-analysis", action="store_true", help="Optional downstream promoter/window statistics")
    q = sub.add_parser("migrate-config")
    for name in ("config", "output", "run-id", "env-root"):
        q.add_argument("--" + name, required=True)
    q.add_argument("--micromamba", default="micromamba")
    q.add_argument("--profile", choices=("baseline", "arabidopsis-compare"), default="arabidopsis-compare")
    q.add_argument("--hite-image")
    q.add_argument("--protein-qc", action="store_true")
    q.add_argument("--promoter-analysis", action="store_true")
    q = sub.add_parser("import-stage")
    for name in ("config", "source-config", "sample", "name"):
        q.add_argument("--" + name, required=True)
    q = sub.add_parser("lock-databases")
    q.add_argument("--config", required=True)
    q.add_argument("--pfam-dir")
    q.add_argument("--classification-dir", action="append")
    q.add_argument("--extra-dir", action="append")
    from .review_cli import add_review_commands, dispatch_review
    add_review_commands(sub)
    from .boundary_cli import add_commands, dispatch
    add_commands(sub)
    from .project_cli import add_project_commands, dispatch_project, PROJECT_COMMANDS
    add_project_commands(sub)
    args = p.parse_args(argv)
    try:
        if args.action in PROJECT_COMMANDS:
            result = dispatch_project(args)
            if isinstance(result, int):
                return result
        elif args.action.startswith("boundary-"):
            result = dispatch(args)
        elif args.action.startswith("review-"):
            result = dispatch_review(args)
        elif args.action == "init-server":
            result = server_config(args)
        elif args.action == "lock-databases":
            result = lock_databases(args)
        elif args.action == "migrate-config":
            old = load_config(args.config)
            if old["run_id"] == args.run_id or Path(args.output).exists():
                raise WorkflowError("Migration requires a new run_id and a new output file")
            if args.profile == "arabidopsis-compare" and any(s["id"] != "arabidopsis_TAIR10" for s in old["samples"]):
                raise WorkflowError("Comparison migration is restricted to the Arabidopsis sample")
            c = {k: v for k, v in old.items() if not k.startswith("_")}
            c["run_id"] = args.run_id
            configure_v2(c, args.env_root, args.micromamba, args.profile, args.hite_image, args.protein_qc)
            c["evaluation"]["promoter_analysis"] = args.promoter_analysis
            write_json(args.output, c)
            load_config(args.output)
            result = dict(config=args.output, old_run_preserved=True, schema_version=2, next="Install only additional tools; freeze, doctor, prepare, then import verified EDTA/RM stages")
        elif args.action == "import-stage":
            from .migration import import_stage
            result = import_stage(load_config(args.source_config), load_config(args.config), args.sample, args.name)
        else:
            c = load_config(args.config)
            if args.action == "targets":
                if args.name not in graph(c):
                    raise WorkflowError("Target stage is not enabled: " + args.name)
                print("\n".join(str(work(c, s["id"]) / ".dag" / (args.name + ".done")) for s in c["samples"]))
                return 0
            if args.action == "settings":
                print(str(Path(c["work_root"]) / c["run_id"]) if args.key == "run_root" else c["execution"][args.key])
                return 0
            if args.action == "validate-inputs":
                audits = [audit_sample(s) for s in c["samples"]]
                result = dict(status="pass", created=now(), samples=audits, scope="Read-only input audit; no TE algorithms executed")
                write_json(args.output, result)
                result = dict(status="pass", output=args.output, samples=[dict(sample=a["sample"], selected_bp=a["selected_bp"], sequences=len(a["sequences"])) for a in audits])
            elif args.action == "prepare":
                from .resources import stage_context
                with stage_context(c,args.sample,'prepared'):
                    a = prepare(c, args.sample)
                result = dict(sample=args.sample, manifest=str(work(c, args.sample) / "prepared" / "manifest.json"), selected_bp=a["selected_bp"], cds_audit=a.get("cds_audit"))
                scheduler_marker(c, args.sample, "prepared", work(c, args.sample) / "prepared/manifest.json")
            elif args.action == "freeze":
                result = dict(fingerprint=freeze(c)["fingerprint"])
            elif args.action == "doctor":
                result = doctor(c, args.output, args.dependencies)
            elif args.action == "stage":
                r = execute(c, args.sample, args.name, args.threads, args.resume)
                result = dict(stage=args.name, sample=args.sample, status=r["status"], details=r["details"])
                scheduler_marker(c, args.sample, args.name, work(c, args.sample) / args.name / "complete.json")
            elif args.action == "plan":
                from .resources import resource_plan
                result = dict(schema_version=c["schema_version"], branches=enabled(c), required_tools=sorted(required_tools(c)), dependencies=graph(c), resources=resource_plan(c), computation_launched=False)
            elif args.action == "status":
                result = run_status(c)
            elif args.action == "unlock-stage":
                from .migration import unlock_stage
                result = unlock_stage(c, args.sample, args.name)
            else:
                result = feedback(c, args.output)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (WorkflowError, OSError, KeyError, json.JSONDecodeError) as e:
        print("teflow: " + str(e), file=sys.stderr)
        return 2


def scheduler_marker(c, sid, stage, receipt):
    write_json(work(c, sid) / ".dag" / (stage + ".done"), dict(receipt=str(receipt), sha256=sha256(receipt)))


def run_status(c):
    rows = []
    for s in c["samples"]:
        for stage in graph(c):
            folder = work(c, s["id"]) / stage
            status = "pending"
            if (folder / "complete.json").exists():
                receipt = read_json(folder / "complete.json")
                status = "complete_zero" if receipt.get("details", {}).get("zero_candidates") else "complete"
                if not all(Path(p).is_file() for p in receipt["outputs"]):
                    status = "invalid_artifact"
                elif receipt.get('output_stats'):
                    from .common import file_stamp
                    if any(file_stamp(p) != stamp for p,stamp in receipt['output_stats'].items()):
                        status = 'artifact_metadata_changed'
            elif (folder / ".lock").exists():
                status = "locked_review_process_state"
            elif (folder / "failed.json").exists():
                status = "failed"
            runtime = work(c,s['id'])/'.runtime'/stage
            observations = list(runtime.glob('*/status.json')) if runtime.exists() else []
            observed = read_json(max(observations,key=lambda p:p.stat().st_mtime_ns)) if observations else None
            if status in ('pending','locked_review_process_state') and observed:
                if observed['phase'] in ('running','waiting'):
                    from .resource_pool import identity_alive
                    owner = observed.get('owner')
                    alive = identity_alive(owner) if owner and sys.platform.startswith('linux') else None
                    status = observed['phase'] if alive is True else 'interrupted_review' if alive is False else 'owner_unverified'
                elif observed['phase'] in ('failed','admission_timeout','unresolved_children'): status = observed['phase']
            rows.append(dict(sample=s["id"], stage=stage, status=status, runtime=observed))
    bad = {'failed','admission_timeout','unresolved_children','invalid_artifact','artifact_metadata_changed','blocked_dependency','interrupted_review'}
    for _ in range(len(rows)):
        states = {(r['sample'],r['stage']):r['status'] for r in rows}
        for r in rows:
            if r['status']=='pending' and any(states[(r['sample'],d)] in bad for d in graph(c)[r['stage']]):
                r['status']='blocked_dependency'
    from .reporting import latest_launch
    return dict(status="complete" if all(r["status"].startswith("complete") for r in rows) else "incomplete", stages=rows,
                launcher=latest_launch(c),
                validation='existence_and_metadata_only; completion describes receipts, not biological accuracy',
                disabled_branches=[b for b in BRANCHES if b not in enabled(c)])


if __name__ == "__main__":
    raise SystemExit(main())
