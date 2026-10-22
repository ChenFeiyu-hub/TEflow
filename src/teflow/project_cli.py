"""Additive CLI v1; existing advanced and review commands remain available."""
from .assets import asset_path, asset_root, recipe_files
from .branches import BRANCHES
from .project import initialize, fork_config, capabilities, PROFILES
from .launcher import launch, check_project

PROJECT_COMMANDS = {"init", "check", "run", "fork-config", "capabilities", "assets", "reevaluate", "audit-results", "runtime-status", "runtime-reconcile",
                    "cancel", "run-preview", "report", "runtime-summary", "logs", "select"}


def execution_options(p):
    p.add_argument('--parallel-branches', action='store_true', help='Opt into single-species branch concurrency; memory is observed, not hard limited')
    p.add_argument('--jobs', type=int, default=2, help='Maximum active stages in branch mode')
    p.add_argument('--io-slots', type=int, default=2)
    p.add_argument('--memory-headroom-mb', type=int, default=4096)
    p.add_argument('--stage-resources', help='JSON object of stage/kind to threads, mem_mb and io requests')
    p.add_argument('--all-interspersed', action='store_true', help='Also export Unknown-inclusive softmask FASTA')


def add_project_commands(sub):
    p = sub.add_parser('select', help='Record an explicit branch/mask choice in a new delivery directory; no analysis')
    for key in ('config', 'output'): p.add_argument('--'+key, required=True)
    p.add_argument('--branch', required=True, choices=list(BRANCHES))
    p.add_argument('--policy', required=True, choices=('te_primary','all_interspersed'))
    p.add_argument('--sample')
    p.add_argument('--mode', choices=('symlink','copy'), default='symlink')
    p.add_argument('--reason', default='Explicit user selection')
    p = sub.add_parser("init", help="Create a generic genome project configuration; no analysis")
    for key in ("root", "genome", "sample-id", "run-id"):
        p.add_argument("--" + key, required=True)
    for key in ("env-root", "annotation", "cds", "reference-library", "hite-image", "output"):
        p.add_argument("--" + key)
    p.add_argument("--threads", type=int, default=32)
    p.add_argument('--taxon-group', choices=('plant','metazoa','fungi','other'), default='plant')
    p.add_argument("--mem-mb", type=int, default=131072)
    p.add_argument("--micromamba", default="micromamba")
    p.add_argument("--exclude-seqid", action="append", help="Repeat for each exact FASTA seqid to exclude")
    p.add_argument("--protein-qc", action="store_true", help="Derive host proteins from supplied annotation/CDS")
    execution_options(p)
    group = p.add_mutually_exclusive_group()
    group.add_argument("--profile", choices=list(PROFILES), help="Default: baseline (E + ET)")
    group.add_argument("--branch", action="append", choices=list(BRANCHES), help="Explicit branches, including their parents; repeat flag")
    p = sub.add_parser("check", help="Input audit and dependency probes, without freezing or genome discovery")
    p.add_argument("--config", required=True)
    p.add_argument("--versions-only", action="store_true", help="Skip execution probes; not a production acceptance check")
    p = sub.add_parser("run", help="Freeze, probe dependencies and launch Snakemake on Linux")
    p.add_argument("--config", required=True)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Freeze/probe and check DAG; no genome discovery")
    mode.add_argument("--resume", action="store_true", help="Resume unchanged interrupted work; never force-unlocks")
    p.add_argument("--target-stage", help="Run only the named enabled stage and its dependencies")
    for name, help_text in (
        ('cancel','Request cooperative cancellation of this live supervised run only'),
        ('run-preview','Read-only work scope; existing completion vs new work (no cache promise)'),
        ('report','Read-only Markdown/JSON/TSV report to a new directory'),
        ('runtime-summary','Read sampled memory and telemetry quality, including old 0.6 attempts'),
        ('logs','Read bounded scheduler or stage log tails')):
        view = sub.add_parser(name, help=help_text)
        view.add_argument('--config', required=True)
        if name == 'run-preview': view.add_argument('--target-stage')
        if name == 'report': view.add_argument('--output', required=True)
        if name == 'logs':
            view.add_argument('--sample')
            view.add_argument('--stage')
            view.add_argument('--lines', type=int, default=40)
    p = sub.add_parser("fork-config", help="Preserve settings in a new run and rebind known wrapper paths")
    for key in ("config", "output", "run-id"):
        p.add_argument("--" + key, required=True)
    p.add_argument('--threads',type=int)
    p.add_argument('--mem-mb',type=int)
    execution_options(p)
    for name in ('reevaluate','audit-results','runtime-status','runtime-reconcile'):
        p = sub.add_parser(name, help={'reevaluate':'Fresh offline evaluation of completed exports; no TE tools',
                                     'audit-results':'Read-only vocabulary/consensus-coordinate audit',
                                     'runtime-status':'Read stage leases and sampled memory',
                                     'runtime-reconcile':'Release only proven dead, quiescent leases; never signal processes'}[name])
        p.add_argument('--config',required=True)
        if name in ('reevaluate','audit-results'): p.add_argument('--output',required=True)
    sub.add_parser("capabilities", help="Versions, branch validation scope and extension contract as JSON")
    p = sub.add_parser("assets", help="Locate bundled versioned recipes")
    p.add_argument("--path", help="Print one path, e.g. workflow/Snakefile")


def dispatch_project(args):
    if args.action == 'select':
        from .common import load_config
        from .delivery import select
        return select(load_config(args.config), args.output, args.branch, args.policy, args.sample, args.mode, args.reason)
    if args.action in ('cancel','run-preview','report','runtime-summary','logs'):
        from .common import load_config
        from .reporting import preview, report, runtime_summary, log_view
        from .control import cancel
        c = load_config(args.config)
        if args.action == 'cancel': return cancel(c)
        if args.action == 'run-preview': return preview(c,args.target_stage)
        if args.action == 'report': return report(c,args.output)
        if args.action == 'runtime-summary': return runtime_summary(c)
        return log_view(c,args.sample,args.stage,args.lines)
    if args.action in ('reevaluate','audit-results','runtime-status','runtime-reconcile'):
        from .common import load_config
        c = load_config(args.config)
        if args.action in ('reevaluate','audit-results'):
            from .reevaluate import reevaluate, audit_results
            return (reevaluate if args.action=='reevaluate' else audit_results)(c,args.output)
        from .resources import pool_root
        from .resource_pool import inspect_pool, reconcile
        return (inspect_pool if args.action=='runtime-status' else reconcile)(pool_root(c))
    if args.action == "init":
        return initialize(args)
    if args.action == "check":
        return check_project(args)
    if args.action == "run":
        return launch(args)
    if args.action == "fork-config":
        return fork_config(args)
    if args.action == "capabilities":
        return capabilities()
    if args.path:
        print(asset_path(args.path))
        return 0
    return dict(root=str(asset_root()), files=sorted(recipe_files()))
