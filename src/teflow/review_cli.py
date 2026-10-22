"""Candidate review CLI, independent of the main workflow scheduler."""
from .common import WorkflowError, load_config
from .candidate_review import (from_workflow, prepare_review, review_plan, run_review,
                               export_decisions, pack_review)


def add_review_commands(sub):
    p = sub.add_parser("review-prepare", help="Prepare bounded evidence from completed results; no external tools")
    p.add_argument("--config", help="Completed workflow config; source run is never modified")
    p.add_argument("--sample"); p.add_argument("--branch")
    for key in ("genome", "library", "rm-out", "rm-align", "annotation", "prepared-manifest", "native-loci",
                "native-sites", "native-parents", "combined-parents", "host-proteins", "host-cds"):
        p.add_argument("--" + key, help="Explicit-file mode input")
    p.add_argument("--diamond", default="diamond", help="Explicit-file mode executable")
    p.add_argument("--families", required=True, help="Unique family IDs, one per line; # comments allowed")
    p.add_argument("--output", required=True, help="New review directory")
    p.add_argument("--max-loci", type=int, default=10, help="Additional nonoverlapping raw fragments per family, maximum 100")
    p.add_argument("--flank", type=int, default=500)
    p.add_argument("--evalue", type=float, default=1e-5)
    for name in ("review-plan", "review-run"):
        p = sub.add_parser(name, help="Plan/run selected-candidate protein QC only")
        p.add_argument("--review", required=True); p.add_argument("--threads", type=int, default=8)
        if name == "review-run": p.add_argument("--timeout", type=int, default=21600, help="Per-command seconds")
    p = sub.add_parser("review-export", help="Export explicitly reviewed candidate libraries, not genomic masks")
    p.add_argument("--review", required=True); p.add_argument("--decisions", required=True); p.add_argument("--output", required=True)
    p = sub.add_parser("review-pack", help="Compact feedback without original genome, annotation or protein DB")
    p.add_argument("--review", required=True); p.add_argument("--output", required=True)


def dispatch_review(args):
    if args.action == "review-prepare":
        fields = ("genome", "library", "rm_out", "rm_align", "annotation", "prepared_manifest", "native_loci",
                  "native_sites", "native_parents", "combined_parents", "host_proteins", "host_cds")
        explicit = {k: getattr(args, k) for k in fields if getattr(args, k)}
        if args.config:
            if explicit or not args.sample or not args.branch or args.diamond != "diamond":
                raise WorkflowError("Config mode needs --sample/--branch and cannot override scientific inputs or DIAMOND")
            paths, provenance, tool = from_workflow(load_config(args.config), args.sample, args.branch)
            if not tool: tool = dict(command=["diamond"], expected_version=None)
        else:
            if args.sample or args.branch or not {"genome", "library", "rm_out", "rm_align"} <= explicit.keys():
                raise WorkflowError("File mode needs --genome, --library, --rm-out and --rm-align")
            if "host_proteins" in explicit and "host_cds" in explicit:
                raise WorkflowError("Supply either protein FASTA or CDS, not both")
            paths, provenance, tool = explicit, None, dict(command=[args.diamond], expected_version=None)
        return prepare_review(paths, args.output, args.families, provenance, tool, args.max_loci, args.flank, args.evalue)
    if args.action == "review-plan": return review_plan(args.review, args.threads)
    if args.action == "review-run": return run_review(args.review, args.threads, args.timeout)
    if args.action == "review-export": return export_decisions(args.review, args.decisions, args.output)
    if args.action == "review-pack": return pack_review(args.review, args.output)
    raise WorkflowError("Unknown review command")
