"""Project setup and explicit configuration forks; no upstream algorithms run here."""
from pathlib import Path
import json
import tempfile
from . import __version__
from .assets import asset_root, asset_path
from .branches import BRANCHES, DEFAULT_BRANCHES, required_tools
from .common import WorkflowError, ID, load_config, now, sha256, write_json, read_json

PROFILES = {"edta": ["edta"], "baseline": ["edta", "edta_tetrimmer"], "arabidopsis-compare": DEFAULT_BRANCHES}


def apply_execution_options(c,args):
    from .common import read_json
    for key in ('threads','mem_mb'):
        if getattr(args,key,None) is not None: c['execution'][key] = getattr(args,key)
    if getattr(args,'parallel_branches',False):
        c['execution']['scheduling'] = dict(mode='branches',max_jobs=args.jobs,io_slots=args.io_slots,
            memory_headroom_mb=args.memory_headroom_mb,keep_going=True,
            stages=read_json(args.stage_resources) if args.stage_resources else {})
    elif getattr(args,'stage_resources',None):
        raise WorkflowError('--stage-resources requires --parallel-branches')
    if getattr(args,'all_interspersed',False):
        c['exports'] = dict(softmask_policies=['te_primary','all_interspersed'])


def save_new_config(c, output):
    output = Path(output).expanduser().resolve()
    if output.exists():
        raise WorkflowError("Refusing to overwrite configuration: " + str(output))
    for field in ("work_root", "results_root"):
        if (Path(c[field]) / c["run_id"]).exists():
            raise WorkflowError("New configuration requires unused run directories: " + c["run_id"])
    # Validate before creating the destination. All generated paths are absolute.
    with tempfile.TemporaryDirectory(prefix="teflow-config-") as temp:
        p = Path(temp) / "config.json"
        write_json(p, c)
        load_config(p)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="\n") as f:
        json.dump(c, f, indent=2, ensure_ascii=False, allow_nan=False)
        f.write("\n")
    return str(output)


def initialize(args):
    from .cli import configure_v2, VERSIONS
    for value in (args.run_id, args.sample_id):
        if not ID.fullmatch(value):
            raise WorkflowError("Unsafe run/sample ID: " + value)
    if args.threads < 4 or args.mem_mb < 1:
        raise WorkflowError("A production configuration needs at least 4 threads and positive mem_mb")
    root = Path(args.root).expanduser().resolve()
    env = Path(args.env_root).expanduser().resolve() if args.env_root else root / "envs"
    names = args.branch or PROFILES[args.profile or "baseline"]
    if len(set(names)) != len(names):
        raise WorkflowError("Duplicate --branch")
    if args.profile == "arabidopsis-compare" and args.sample_id != "arabidopsis_TAIR10":
        raise WorkflowError("The Arabidopsis preset requires sample-id arabidopsis_TAIR10; use explicit --branch elsewhere")
    s = dict(id=args.sample_id, exclude_seqids=args.exclude_seqid or [], taxon_group=getattr(args,'taxon_group','plant'))
    for key in ("genome", "annotation", "cds", "reference_library"):
        if getattr(args, key, None):
            path = Path(getattr(args, key)).expanduser().resolve()
            if not path.is_file():
                raise WorkflowError("Input file missing: " + str(path))
            s[key] = str(path)
    if s.get("annotation") and not s.get("cds"):
        s["derive_cds"] = True
    providers = {"edta": ("edta", "EDTA.pl"), "tetrimmer": ("tetrimmer", "TEtrimmer"),
                 "repeatmasker": ("masking", "RepeatMasker"), "trf": ("masking", "trf"), "dustmasker": ("masking", "dustmasker")}
    c = dict(schema_version=2, run_id=args.run_id, work_root=str(root / "work"), results_root=str(root / "results"),
             samples=[s], execution=dict(mode="server", threads=args.threads, mem_mb=args.mem_mb),
             parameters=dict(max_divergence=40), databases=dict(pfam_dir=str(root / "databases/pfam"), files=[]),
             tools={k: dict(command=[args.micromamba, "run", "-p", str(env / provider), binary], expected_version=VERSIONS[k])
                    for k, (provider, binary) in providers.items()})
    configure_v2(c, env, args.micromamba, image=args.hite_image, protein_qc=args.protein_qc, names=names)
    c["branches"] = {b: dict(enabled=b in names) for b in BRANCHES}
    c["tools"] = {k: v for k, v in c["tools"].items() if k in required_tools(c)}
    apply_execution_options(c,args)
    output = args.output or root / (args.run_id + ".local.json")
    path = save_new_config(c, output)
    return dict(status="configured", config=path, branches=names, computation_launched=False,
                next="Install enabled tools; configure and lock databases; teflow check; teflow run --dry-run")


def fork_config(args):
    sidecar = Path(str(Path(args.output).expanduser().resolve()) + ".fork.json")
    if sidecar.exists():
        raise WorkflowError("Fork receipt already exists: " + str(sidecar))
    old = load_config(args.config)
    if not ID.fullmatch(args.run_id) or args.run_id == old["run_id"]:
        raise WorkflowError("fork-config requires a different valid run_id")
    c = {k: v for k, v in old.items() if not k.startswith("_")}
    c["run_id"] = args.run_id
    apply_execution_options(c,args)
    changes = []
    supported = {"run_tetrimmer_isolated.sh", "run_hite_container.py"}
    for provider, spec in c["tools"].items():
        for key in ("command", "probe_command"):
            argv = spec.get(key)
            if not argv:
                continue
            for i, token in enumerate(list(argv)):
                # Only known teflow wrappers are rebound; custom adapters remain untouched.
                path = Path(token)
                if path.name in supported and path.parent.name == "scripts":
                    replacement = str(asset_path("scripts/" + path.name))
                    if token != replacement:
                        changes.append(dict(tool=provider, field=key, old=token, new=replacement))
                        argv[i] = replacement
            if provider == "tetrimmer" and Path(argv[-1]).name == "run_tetrimmer_isolated.sh" and "-p" in argv:
                position = argv.index("-p") + 2
                if position == len(argv) - 1:
                    argv.insert(position, "bash")
                    changes.append(dict(tool=provider, field=key, added_interpreter="bash"))
    output = save_new_config(c, args.output)
    receipt = dict(created=now(), teflow_version=__version__, source_config=str(Path(args.config).resolve()),
                   source_sha256=sha256(args.config), config=output, config_sha256=sha256(output), wrapper_changes=changes,
                   preserved_fields="branches, parameters, QC, evaluation, inputs, databases and upstream versions; execution/exports only changed when requested",
                   outputs_imported=False, computation_launched=False)
    # This is an external provenance sidecar, not an extra configuration schema field.
    write_json(sidecar, receipt)
    return dict(status="configured", **receipt, receipt=str(sidecar), next="Review plan, check dependencies, and freeze as a NEW run")


def capabilities():
    validation = read_json(Path(__file__).with_name('validation_status.json'))
    return dict(interface_version=2, teflow_version=__version__, config_schemas=[1, 2],
                production_platform="Linux", assets=str(asset_root()),
                profiles=PROFILES, branches={
                    b: dict(validation="arabidopsis_completed" if b in DEFAULT_BRANCHES else "fixture_only",
                            role="baseline" if b == 'edta' else "refinement_comparison" if b == 'edta_tetrimmer' else "optional_comparison",
                            independent=False if b in {"heliano", "edta_plus_heliano", "edta_tetrimmer", "reference_plus_edta"} else True)
                    for b in BRANCHES},
                library_merge="full_length_exact_or_reverse_complement_with_same_class_only",
                automatic_branch_selection=False, heliano_official_consensus="implemented_not_genome_validated",
                independence_definition="workflow parent dependency only; not reference-blind biological evaluation",
                extension_contract="docs/EXTENDING.md", scientific_defaults_changed=False,
                branch_concurrency=dict(scope='one_species',enforcement='observe_only',default='serial',
                    server_validation=validation),
                run_control=dict(protocol=1,cancellation='cooperative_owned_attempt',resume='explicit_unchanged_run',
                                 crashed_controller_adoption=False),
                multi_species_scheduler='deferred',classification_mapping_version='0.3')
