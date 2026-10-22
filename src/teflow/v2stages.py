"""Schema-2 orchestration and per-branch exports."""
import csv
import html
import json
import shutil
from pathlib import Path
from .common import WorkflowError, fasta, read_json, write_json, table, sha256, sample, results, now
from .branches import BRANCHES, enabled, stage_branch
from .formats import canonical_library, export_branch
from .library_qc import library_qc, combine_libraries
from .evaluation import branch_evaluation, compare_branches, tsv
from .adapters.discovery import run_heliano, run_hite


def _provenance(c, base, branch, dest):
    libstage = BRANCHES[branch][0]
    for p in (base / libstage).glob("*.tsv"):
        shutil.copyfile(p, dest / p.name)
    rows = []
    if branch == "edta_tetrimmer":
        parents = tsv(base / "tetrimmer/upstream/teflow_parent_map.tsv")
        ids = {r["original_name"]: r["family_id"] for r in tsv(base / "tetrimmer/library.fa.provenance.tsv")}
        for r in parents:
            if r["output_name"] not in ids:
                raise WorkflowError("TEtrimmer retained output lacks a canonical child ID")
            rows.append(dict(family_id=ids[r["output_name"]], parent_branch="edta", parent_family_id=r["input_name"], transformation=r["sequence_origin"]))
    elif branch in ("edta_plus_heliano", "reference_plus_edta"):
        rows = tsv(base / libstage / "library.parents.tsv")
    elif branch in ("edta", "reference_only", "hite"):
        for r in tsv(base / libstage / "library.fa.provenance.tsv"):
            rows.append(dict(family_id=r["family_id"], parent_branch="upstream:" + r["source_tool"],
                             parent_family_id=r["original_id"], transformation="ID_normalization_only"))
    if rows:
        table(dest / "parents.tsv", rows, ["family_id", "parent_branch", "parent_family_id", "transformation"])


def export_one(c, sid, base, folder, branch):
    from .publishing import atomic_directory
    dest = results(c, sid) / branch
    with atomic_directory(dest, replace=True) as pending:
        outputs, q = _export_one(c, sid, base, folder, branch, pending)
        relative = [p.relative_to(pending) for p in outputs]
    return [dest / p for p in relative], q


def _export_one(c, sid, base, folder, branch, dest):
    libstage, rmstage, _ = BRANCHES[branch]
    library = base / libstage / "library.fa"
    q = export_branch(base / "prepared", library, base / rmstage / "genome.fa.out", dest, branch,
                      base / "tracks/tandem.dat", base / "tracks/dust.fa", c.get('exports', {}).get('softmask_policies'))
    shutil.copyfile(library, dest / "library.fa")
    shutil.copyfile(base / libstage / "library.fa.provenance.tsv", dest / "family_provenance.tsv")
    _provenance(c, base, branch, dest)
    quality = base / ("qc_" + branch)
    (dest / "library_qc").mkdir(exist_ok=True)
    for p in quality.iterdir():
        if p.is_file() and (p.suffix == ".tsv" or p.name == "qc.json"):
            shutil.copyfile(p, dest / "library_qc" / p.name)
    if branch == "edta":
        from .stages import restore_gff
        (dest / "native").mkdir(exist_ok=True)
        for kind in ("intact", "TEanno"):
            restore_gff(base / "edta" / ("genome.fa.mod.EDTA." + kind + ".gff3"), dest / "native" / (kind + ".gff3"), base / "prepared")
    if branch == "heliano":
        mapping = {r["alias"]: r["original_id"] for r in read_json(base / "prepared/manifest.json")["sequences"]}
        native = tsv(base / "heliano/native_sites.tsv")
        for row in native:
            row["seqid"] = mapping[row["seqid"]]
        table(dest / "native_sites.tsv", native, list(native[0]) if native else ["seqid", "start", "end", "native_id", "subfamily", "strand", "variant"])
        write_json(dest / "native_sites.schema.json", dict(coordinates="1-based closed", strand="genomic", seqid="original FASTA identifier", evidence="native structural candidate, not a verified insertion"))
    evaluation = branch_evaluation(c, sample(c, sid), base / "prepared", dest, library)
    q.update(fixture_only=bool(c.get("fixture_only")), evaluation=evaluation,
             interpretation="Standalone branch export; comparison completeness is checked separately")
    write_json(dest / "qc.json", q)
    outputs = [p for p in dest.rglob("*") if p.is_file() and p.name != "manifest.json"]
    write_json(dest / "manifest.json", dict(branch=branch, created=now(), outputs={str(p.relative_to(dest)): sha256(p) for p in outputs}, status="computed_awaiting_review"))
    return outputs + [dest / "manifest.json"], q


def execute_extended(c, sid, base, folder, stage, cores, call, resume):
    branch = stage_branch(stage)
    if stage == "heliano":
        details, outputs = run_heliano(c, base, folder, cores, call, resume)
    elif stage == "hite":
        details, outputs = run_hite(c, base, folder, cores, call, resume, sample(c, sid))
    elif stage == "reference_only":
        source = sample(c, sid)["reference_library"]
        rows = canonical_library(source, folder / "library.fa", "R", "user_registered_reference")
        if not rows:
            raise WorkflowError("Reference library must not be empty")
        details = dict(library_entries=len(rows), curation="user_supplied_not_inferred", reference_sha256=sha256(source))
        outputs = [folder / "library.fa", folder / "library.fa.provenance.tsv"]
    elif stage in ("edta_plus_heliano", "reference_plus_edta"):
        parents = ("edta", "heliano") if stage == "edta_plus_heliano" else ("reference_only", "edta")
        prefix = BRANCHES[stage][2]
        source = folder / "assembled.fa"
        count = combine_libraries([(b, base / BRANCHES[b][0] / "library.fa") for b in parents], source, prefix)
        canonical_library(source, folder / "library.fa", prefix, "exact_alias_assembly:" + "+".join(parents))
        shutil.copyfile(str(source) + ".parents.tsv", folder / "library.parents.tsv")
        details = dict(library_entries=count, assembly_policy="exact_full_sequence_or_RC_with_same_class_only",
                       parent_branches=parents, status="experimental_library_not_default_mask")
        outputs = [folder / "library.fa", folder / "library.fa.provenance.tsv", folder / "library.parents.tsv", source]
    elif stage.startswith("qc_"):
        details = library_qc(c, base / "prepared", base / BRANCHES[branch][0] / "library.fa", folder, cores)
        outputs = list(folder.glob("*.tsv")) + [folder / "qc.json"] + list(folder.glob("*.domtblout"))
    elif stage.startswith("export_"):
        return export_one(c, sid, base, folder, branch)
    elif stage == "export":
        out = results(c, sid); out.mkdir(exist_ok=True, parents=True)
        details = compare_branches(c, sample(c, sid), base / "prepared", out, enabled(c))
        report = "<meta charset='utf-8'><title>TE annotation workflow</title><h1>TE annotation workflow</h1>"
        report += "<p>" + ("SYNTHETIC FIXTURE ONLY" if c.get("fixture_only") else "Computation complete; biological review pending. No automatic winner.") + "</p><pre>" + html.escape(json.dumps(details, indent=2)) + "</pre>"
        (out / "index.html").write_text(report, encoding="utf-8")
        for filename in ("manifest.json", "seqids.tsv"):
            shutil.copyfile(base / "prepared" / filename, out / ("input_" + filename))
        outputs = [p for p in out.rglob("*") if p.is_file() and p != out / "manifest.json"
                   and not any(x.startswith('.') for x in p.relative_to(out).parts)]
        write_json(out / "manifest.json", dict(created=now(), run_id=c["run_id"], sample=sid,
                   fixture_only=bool(c.get("fixture_only")), status="computed_awaiting_review", selected_branch=None,
                   catalog_curation="pending", downstream_masking_policy="not_selected",
                   branches=enabled(c), outputs={str(p.relative_to(out)): sha256(p) for p in outputs}))
        outputs.append(out / "manifest.json")
    else:
        raise WorkflowError("Unsupported schema-2 stage: " + stage)
    return outputs, details
