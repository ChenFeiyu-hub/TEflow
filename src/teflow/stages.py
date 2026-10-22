"""Version-specific adapters for the first controlled EDTA/TEtrimmer comparison."""
from __future__ import annotations
import csv
import html
import json
import random
import re
import shutil
import uuid
from pathlib import Path
from .common import (WorkflowError, biological_guard, fasta, work, results, sample,
                     read_json, write_json, sha256, table, now)
from .inputs import prepare, annotation_rows
from .formats import canonical_library, audit_tetrimmer, export_branch, rm_out, trf_dat, dust_fasta, union
from .runtime import (run, stage_cache, finish_stage, release_lock, stage_copy,
                      check_frozen, rm_parallel_jobs)
from .branches import graph, required_tools, stage_tools, stage_branch, options, BRANCHES
from .environments import environment_command
from .registry import TOOL_PROBES

STAGES = ("edta", "tetrimmer", "rm_edta", "rm_refined", "tracks", "export")


def command(c, name):
    if name not in c["tools"]:
        raise WorkflowError("Tool configuration missing: " + name)
    return c["tools"][name]["command"]


def verify_version(c, name, text):
    expected = c["tools"][name]["expected_version"]
    if expected in text:
        return
    # Official tag/package 2.3.0 prints v2.3. Require package metadata for its patch level.
    if name == "edta" and expected == "2.3.0" and re.search(r"EDTA.*\bv2\.3\b", text):
        if c.get("fixture_only"):
            return
        argv = command(c, name)
        if "-p" in argv:
            prefix = Path(argv[argv.index("-p")+1])
            for meta in (prefix / "conda-meta").glob("edta-*.json"):
                m = read_json(meta)
                if m.get("name") == "edta" and m.get("version") == expected:
                    return
        raise WorkflowError("EDTA prints v2.3; exact 2.3.0 must also be verified from Conda package metadata")
    raise WorkflowError(f"Expected {name} {expected} not found in version output")


def _doctor_attempt(c, output, dependency_check=False):
    """Probe interfaces cheaply. EDTA's deeper dependency check is server-only."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    checks = []
    probes = TOOL_PROBES
    for name, (args, allowed) in probes.items():
        if name not in required_tools(c):
            continue
        try:
            t = c["tools"][name]
            text = run(command(c, name) + args, output, output / (name + ".version.log"), 120, allowed)
            verify_version(c, name, text)
            if name == "tetrimmer":
                h = run(command(c, name) + ["--help"], output, output / "tetrimmer.help.log", 120)
                if not all(x in h for x in ("--input_file", "--pfam_dir", "--continue_analysis", "--num_threads")):
                    raise WorkflowError("TEtrimmer interface differs from audited version")
            check = dict(tool=name, status="pass", expected_version=t["expected_version"])
            if name == "hite" and t.get("image_identity"):
                check["image_identity"] = t["image_identity"]
            checks.append(check)
        except (OSError, WorkflowError, KeyError) as e:
            checks.append(dict(tool=name, status="fail", error=str(e)))
    if dependency_check:
        if c["execution"]["mode"] != "server":
            raise WorkflowError("EDTA dependency checks belong on the server")
        if "edta" in required_tools(c):
            try:
                text = run(command(c, "edta") + ["--check_dependencies"], output,
                           output / "edta.dependencies.log", 600)
                if "All passed!" not in text or "ERROR" in text.upper():
                    raise WorkflowError("Inspect EDTA dependency log for missing/error reports")
                checks.append(dict(tool="edta_dependencies", status="pass"))
            except (OSError, WorkflowError) as e:
                checks.append(dict(tool="edta_dependencies", status="fail", error=str(e)))
        if not c.get("fixture_only"):
            # Help/version probes never reach TIR-Learner's pandas row indexing.
            if "edta" in required_tools(c):
                try:
                    argv = command(c, "edta")
                    if "-p" not in argv:
                        raise WorkflowError("TIR-Learner pandas probe needs the documented micromamba command prefix")
                    probe = Path(__file__).with_name("tirlearner_probe.py").resolve()
                    text = run(environment_command(c, "edta") + ["python", str(probe)], output,
                               output / "edta_tirlearner_pandas.log", 120)
                    evidence = json.loads(text)
                    if evidence.get("status") != "pass":
                        raise WorkflowError("TIR-Learner pandas indexing check did not pass")
                    checks.append(dict(tool="edta_tirlearner_pandas", **evidence))
                except (OSError, WorkflowError, json.JSONDecodeError) as e:
                    checks.append(dict(tool="edta_tirlearner_pandas", status="fail", error=str(e)))
            if "tetrimmer" in required_tools(c):
                try:
                    from .teaid import probe_teaid
                    evidence = probe_teaid(c, output / "teaid_protein_probe")
                    checks.append(dict(tool="teaid_protein_database", **evidence))
                except (OSError, WorkflowError) as e:
                    checks.append(dict(tool="teaid_protein_database", status="fail", error=str(e)))
            # Exercise both isolated classifiers before committing to a long discovery run.
            # One synthetic 600-bp sequence checks installation, not classification accuracy.
            for provider in ("edta", "tetrimmer"):
                if provider not in required_tools(c):
                    continue
                try:
                    argv = command(c, provider)
                    if "-p" not in argv:
                        raise WorkflowError("Classifier smoke check needs the documented micromamba command prefix")
                    cls = environment_command(c, provider) + ["RepeatClassifier"]
                    dest = output / (provider + "_classifier_probe")
                    dest.mkdir(exist_ok=True)
                    rng = random.Random(27)
                    dna = "".join(rng.choices("ACGT", k=600))
                    probe = ">teflowProbe synthetic installation check\n" + dna + "\n"
                    if provider == "tetrimmer":
                        # Match TEtrimmer 1.7.2 boundarycrop.py: bare header + Dummy.
                        probe = ">teflowProbe\n" + dna + "\n>Dummy\nT\n"
                    (dest / "probe.fa").write_text(probe, encoding="ascii")
                    h = run(cls + ["-help"], dest, dest / "help.log", 120, (0, 1))
                    if "2.0.9" not in h:
                        raise WorkflowError("RepeatClassifier must match the pinned RepeatModeler 2.0.9")
                    text = run(cls + ["-consensi", "probe.fa", "-threads", "1"], dest, dest / "run.log", 900)
                    records = list(fasta(dest / "probe.fa.classified"))
                    if not any(n.split("#", 1)[0] == "teflowProbe" and s.upper() == dna for n, s in records):
                        raise WorkflowError("Classifier did not preserve the probe sequence ID")
                    if "does not appear to be complete" in text or "Could not determine FamDB" in text:
                        raise WorkflowError("Classifier reference library is incomplete; inspect probe log")
                    checks.append(dict(tool=provider + "_classifier_backend", status="pass"))
                except (OSError, WorkflowError) as e:
                    checks.append(dict(tool=provider + "_classifier_backend", status="fail", error=str(e)))
            for provider in ("heliano", "hite"):
                if provider not in required_tools(c):
                    continue
                try:
                    argv = command(c, provider)
                    probe_cmd = c["tools"][provider].get("probe_command")
                    if not probe_cmd:
                        if "-p" not in argv:
                            raise WorkflowError("Provide probe_command for non-micromamba upstream installation")
                        probe_cmd = environment_command(c, provider) + ["python", str(Path(__file__).with_name("upstream_probe.py")), provider]
                    probe_text = run(probe_cmd, output, output / (provider + ".dependencies.log"), 600, cpu_limit=1)
                    # Imported scientific packages may print warnings before the final JSON line.
                    evidence = json.loads(probe_text.strip().splitlines()[-1])
                    if evidence.get("status") != "pass":
                        raise WorkflowError("Upstream dependency execution did not pass")
                    checks.append(dict(tool=provider + "_dependencies", **evidence))
                except (OSError, WorkflowError, json.JSONDecodeError) as e:
                    failure = dict(tool=provider + "_dependencies", status="fail", error=str(e))
                    # Preserve a probe's structured cause in doctor.json as well as its log.
                    log = output / (provider + ".dependencies.log")
                    if log.is_file():
                        for line in reversed(log.read_text(encoding="utf-8", errors="replace").splitlines()):
                            try:
                                detail = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            if isinstance(detail, dict) and detail.get("status") == "fail":
                                failure["probe_error"] = detail.get("error", "Unspecified probe failure")
                                break
                    checks.append(failure)
    result = dict(created=now(), checks=checks, status="pass" if all(r["status"] == "pass" for r in checks) else "fail",
                  fixture_only=bool(c.get("fixture_only")), dependencies_checked=dependency_check,
                  scope="CLI/version probes; dependency execution is a separate check; not a genome benchmark")
    write_json(output / "doctor.json", result)
    if result["status"] != "pass":
        raise WorkflowError("Environment checks failed; inspect " + str(output / "doctor.json"))
    return result


def doctor(c, output, dependency_check=False):
    """Keep every attempt; only a passing attempt becomes an authoritative receipt."""
    output = Path(output)
    attempt = output / "attempts" / uuid.uuid4().hex
    attempt.mkdir(parents=True)
    result = _doctor_attempt(c, attempt, dependency_check)
    canonical = output / "doctor.json"
    if not canonical.exists() or read_json(canonical).get("status") != "pass":
        if canonical.exists():
            shutil.copyfile(canonical, output / ("previous_failed." + uuid.uuid4().hex + ".json"))
        write_json(canonical, dict(result, attempt=str(attempt)))
    return result


def dependency_inputs(c, sid, stage):
    base = work(c, sid)
    inputs = [check_frozen(c), base / "prepared" / "manifest.json", base / "prepared" / "genome.fa",
              Path(c["work_root"]) / c["run_id"] / "doctor" / "doctor.json"]
    deps = graph(c)
    for d in deps[stage]:
        manifest = base / d / "complete.json"
        m = read_json(manifest)
        for p, h in m["outputs"].items():
            if not Path(p).is_file() or sha256(p) != h:
                raise WorkflowError("Dependency output changed: " + p)
        inputs.append(manifest)
    p = base / "prepared"
    for name, expected in read_json(p / "manifest.json")["outputs"].items():
        if sha256(p / name) != expected:
            raise WorkflowError("Prepared reference changed: " + name)
    for k in ("reference_library", "reference_te", "promoters_bed"):
        if sample(c, sid).get(k):
            inputs.append(Path(sample(c, sid)[k]))
    if stage.startswith("qc_"):
        for k in ("host_proteins", "te_proteins"):
            if c.get("qc", {}).get(k) and c["qc"][k] != "derived":
                inputs.append(Path(c["qc"][k]))
    return inputs


def restore_gff(source, target, prepared):
    m = read_json(prepared / "manifest.json")
    ids = {s["alias"]: s for s in m["sequences"] if s["included"]}
    count = 0
    with open(source, encoding="utf-8") as src, open(target, "w", encoding="utf-8", newline="\n") as out:
        out.write("##gff-version 3\n")
        for raw in src:
            if raw.startswith("#") or not raw.strip():
                continue
            v = raw.rstrip("\r\n").split("\t")
            if len(v) != 9 or v[0] not in ids or not 1 <= int(v[3]) <= int(v[4]) <= ids[v[0]]["length"]:
                raise WorkflowError("EDTA GFF does not match staged genome")
            v[0] = ids[v[0]]["original_id"]
            out.write("\t".join(v) + "\n")
            count += 1
    return count


def overlap_bp(a, b):
    a, b, i, j, total = union(a), union(b), 0, 0, 0
    while i < len(a) and j < len(b):
        c, x, y = a[i]; d, u, v = b[j]
        if c == d:
            total += max(0, min(y, v) - max(x, u))
        if c < d or (c == d and y <= v):
            i += 1
        else:
            j += 1
    return total


def read_bed(path):
    with open(path, encoding="utf-8") as f:
        return [(v[0], int(v[1]), int(v[2])) for line in f if (v := line.split())]


def export_sample(c, sid, base, folder):
    out = results(c, sid)
    out.mkdir(parents=True, exist_ok=True)
    metrics = []
    for branch, libstage, rmstage in (("edta", "edta", "rm_edta"), ("refined", "tetrimmer", "rm_refined")):
        dest = out / branch
        q = export_branch(base / "prepared", base / libstage / "library.fa", base / rmstage / "genome.fa.out",
                          dest, branch, base / "tracks" / "tandem.dat", base / "tracks" / "dust.fa",
                          c.get('exports', {}).get('softmask_policies'))
        shutil.copyfile(base / libstage / "library.fa", dest / "library.fa")
        shutil.copyfile(base / libstage / "library.fa.provenance.tsv", dest / "family_provenance.tsv")
        q["fixture_only"] = bool(c.get("fixture_only"))
        ann = sample(c, sid).get("annotation")
        if ann:
            cds = [(ch, a-1, b) for ch, kind, a, b, _, _, _ in annotation_rows(ann) if kind == "CDS"]
            q["repeat_mask_CDS_overlap_bp"] = overlap_bp(read_bed(dest / "repeat.mask.bed"), cds)
            q["CDS_overlap_interpretation"] = "Audit flag only: TE genes and domesticated TE-derived genes may overlap"
        write_json(dest / "qc.json", q)
        metrics.append(q)
    native = out / "edta_native"
    native.mkdir(exist_ok=True)
    for kind in ("intact", "TEanno"):
        restore_gff(base / "edta" / ("genome.fa.mod.EDTA." + kind + ".gff3"), native / (kind + ".gff3"), base / "prepared")
    for filename in ("teflow_review.tsv", "teflow_parent_map.tsv", "teflow_audit.json", "summary.txt", "Sequence_name_mapping.txt"):
        p = base / "tetrimmer" / "upstream" / filename
        if p.exists():
            (out / "curation").mkdir(exist_ok=True)
            shutil.copyfile(p, out / "curation" / filename)
    for f in ("manifest.json", "seqids.tsv"):
        shutil.copyfile(base / "prepared" / f, out / ("input_" + f))
    a, b = [read_bed(out / branch / "te.mask.bed") for branch in ("edta", "refined")]
    shared = overlap_bp(a, b)
    total = sum(y-x for _, x, y in union(a+b))
    comparison = dict(te_mask_shared_bp=shared, te_mask_union_bp=total,
                      te_mask_jaccard=shared/total if total else None,
                      interpretation="Coverage comparison is not an accuracy estimate or an automatic branch selector",
                      selected_branch=None, biological_review="pending", fixture_only=bool(c.get("fixture_only")))
    write_json(out / "comparison.json", comparison)
    table(out / "comparison.tsv", [dict(branch=q["branch"], fragments=q["fragments"],
          families_with_hits=q["family_ids_with_hits"], te_union_bp=q["union_bp"]["te"],
          repeat_mask_bp=q["repeat_mask_bp"], unknown_bp=q["union_bp"]["unknown"]) for q in metrics],
          ["branch", "fragments", "families_with_hits", "te_union_bp", "repeat_mask_bp", "unknown_bp"])
    report = "<meta charset='utf-8'><title>TE workflow audit</title><h1>TE workflow audit: " + html.escape(sid) + "</h1>"
    report += "<p>" + ("SYNTHETIC INTERFACE FIXTURE — NOT BIOLOGICAL RESULTS" if c.get("fixture_only") else "Completed computation; biological review pending. No branch selected automatically.") + "</p>"
    report += "<pre>" + html.escape(json.dumps(dict(comparison=comparison, branches=metrics), indent=2)) + "</pre>"
    (out / "index.html").write_text(report, encoding="utf-8")
    outputs = sorted(p for p in out.rglob("*") if p.is_file() and p.name != "manifest.json")
    write_json(out / "manifest.json", dict(run_id=c["run_id"], sample=sid, created=now(), config=c,
               fixture_only=bool(c.get("fixture_only")), outputs={str(p.relative_to(out)): sha256(p) for p in outputs},
               source_stages={name: sha256(base / name / "complete.json") for name in STAGES if name != "export"},
               status="computed_awaiting_review", selected_branch=None,
               catalog_curation="pending", downstream_masking_policy="not_selected"))
    return outputs + [out / "manifest.json"], comparison


def execute(c, sid, stage, cores=None, resume=False):
    from .resources import stage_context, stage_resources
    biological_guard(c)
    if stage not in graph(c):
        raise WorkflowError('Unknown stage: ' + stage)
    cores = stage_resources(c,stage)['threads'] if cores is None else cores
    with stage_context(c,sid,stage,cores):
        return _execute(c,sid,stage,cores,resume)


def _execute(c, sid, stage, cores=None, resume=False):
    biological_guard(c)
    if stage not in graph(c):
        raise WorkflowError("Unknown stage: " + stage)
    cores = c["execution"]["threads"] if cores is None else cores
    if not 1 <= cores <= c["execution"]["threads"]:
        raise WorkflowError("Allocated cores exceed the frozen budget")
    base, folder = work(c, sid), work(c, sid) / stage
    inputs = dependency_inputs(c, sid, stage)
    if read_json(inputs[3])["status"] != "pass":
        raise WorkflowError("A passing doctor report is required")
    key = stage_key(c, stage, cores, sid)
    cached, req = stage_cache(folder, key, inputs, resume)
    if cached:
        return cached
    try:
        prep = base / "prepared"
        genome = prep / "genome.fa"
        lengths = {n: len(s) for n, s in fasta(genome)}
        details = {}
        timeout = c["execution"].get("stage_timeout_seconds")
        def call(tool, args, name="run"):
            return run(command(c, tool) + [str(x) for x in args], folder, folder / (name + ".log"), timeout, cpu_limit=cores)
        if stage == "edta":
            stage_copy(genome, folder / "genome.fa")
            args = ["--genome", "genome.fa", "--species", "others", "--step", "all", "--threads", cores,
                    "--overwrite", "0", "--sensitive", "1", "--anno", "1", "--evaluate", "0", "--force", "0",
                    "--wholeelement", "0", "--maxdiv", c["parameters"]["max_divergence"], "--debug", "1"]
            if (prep / "host.cds.fa").exists():
                stage_copy(prep / "host.cds.fa", folder / "host.cds.fa")
                args += ["--cds", "host.cds.fa"]
            call("edta", args)
            rawlib = folder / "genome.fa.mod.EDTA.TElib.fa"
            if not list(fasta(rawlib)):
                raise WorkflowError("EDTA produced no candidate library; no rice fallback allowed")
            # Confirm EDTA did not change sequence content or IDs unexpectedly.
            expected_mod = {n: "".join(b if b in "ACGT" else "N" for b in s.upper()) for n, s in fasta(genome)}
            if (folder / "genome.fa.mod").exists() and dict(fasta(folder / "genome.fa.mod")) != expected_mod:
                raise WorkflowError("EDTA .mod sequence differs; coordinate restoration needs inspection")
            for kind in ("intact", "TEanno"):
                p = folder / ("genome.fa.mod.EDTA." + kind + ".gff3")
                restore_gff(p, folder / (kind + ".checked.gff3"), prep)
            details["families"] = len(canonical_library(rawlib, folder / "library.fa", "E", "EDTA-2.3.0"))
            outputs = [folder / "library.fa", folder / "library.fa.provenance.tsv", rawlib] + [folder / ("genome.fa.mod.EDTA." + k + ".gff3") for k in ("intact", "TEanno")]
        elif stage == "tetrimmer":
            workers = rm_parallel_jobs(cores)
            upstream = folder / "upstream"
            stage_copy(genome, folder / "genome.fa")
            args = ["--input_file", base / "edta" / "library.fa", "--genome_file", folder / "genome.fa",
                    "--output_dir", upstream, "--num_threads", workers, "--classify_all",
                    "--pfam_dir", c["databases"]["pfam_dir"]]
            if resume and (upstream / "summary.txt").exists():
                args.append("--continue_analysis")
            call("tetrimmer", args)
            details = audit_tetrimmer(upstream, base / "edta" / "library.fa")
            details["worker_processes"] = workers
            canonical_library(upstream / "TEtrimmer_consensus_merged.fasta", folder / "library.fa", "T", "TEtrimmer-1.7.2")
            outputs = [folder / "library.fa", folder / "library.fa.provenance.tsv"] + [upstream / n for n in ("summary.txt", "TEtrimmer_consensus_merged.fasta", "teflow_review.tsv", "teflow_parent_map.tsv", "teflow_audit.json")]
        elif stage.startswith("rm_"):
            src = base / BRANCHES[stage_branch(stage)][0] / "library.fa"
            libids = {n.split("#", 1)[0]:len(seq) for n, seq in fasta(src, allow_empty=True)}
            stage_copy(genome, folder / "genome.fa")
            stage_copy(src, folder / "library.fa")
            if libids:
                call("repeatmasker", ["-e", "rmblast", "-pa", rm_parallel_jobs(cores), "-s", "-nolow", "-no_is",
                                     "-div", c["parameters"]["max_divergence"], "-gff", "-a", "-lib", "library.fa", "-dir", ".", "genome.fa"])
            else:
                (folder / "genome.fa.out").write_text("There were no repetitive sequences: audited refined library is empty.\n", encoding="ascii")
            hits = rm_out(folder / "genome.fa.out", lengths, libids, libids)
            details = dict(fragments=len(hits), rmblast_parallel_jobs=rm_parallel_jobs(cores), empty_library=not libids)
            details['consensus_length_mismatches'] = sum(r['consensus_coordinate_status'] == 'length_mismatch' for r in hits)
            details['consensus_out_of_bounds'] = sum(r['consensus_coordinate_status'] == 'out_of_bounds' for r in hits)
            outputs = [folder / "genome.fa.out"]
            alignment = folder / "genome.fa.align"
            if hits and (not alignment.is_file() or not alignment.stat().st_size):
                raise WorkflowError("RepeatMasker produced hits but requested alignment is missing: " + str(alignment))
            if alignment.is_file() and alignment.stat().st_size:
                outputs.append(alignment)
                details["alignment_status"] = "recorded_with_sha256"
            else:
                details["alignment_status"] = "no_hits_no_alignment_required"
        elif stage == "tracks":
            stage_copy(genome, folder / "genome.fa")
            # TRF is a single-process job; -d emits the full, named sequence .dat format.
            call("trf", ["genome.fa", "2", "7", "7", "80", "10", "50", "500", "-d", "-h"], "trf")
            src = folder / "genome.fa.2.7.7.80.10.50.500.dat"
            shutil.copyfile(src, folder / "tandem.dat")
            details["tandem_intervals"] = len(trf_dat(folder / "tandem.dat", lengths))
            call("dustmasker", ["-in", "genome.fa", "-out", "dust.fa", "-outfmt", "fasta", "-level", "20", "-window", "64", "-linker", "1"], "dustmasker")
            details["dust_intervals"] = len(dust_fasta(folder / "dust.fa", genome))
            outputs = [folder / "tandem.dat", folder / "dust.fa"]
        elif c["schema_version"] == 2:
            from .v2stages import execute_extended
            outputs, details = execute_extended(c, sid, base, folder, stage, cores, call, resume)
        else:
            outputs, details = export_sample(c, sid, base, folder)
        outputs += sorted(folder.glob("*.log")) + sorted(folder.glob("*.command.json"))
        return finish_stage(folder, req, outputs, details)
    except BaseException as e:
        write_json(folder / "failed.json", dict(status="failed", error=str(e), time=now(), request=req))
        raise
    finally:
        release_lock(folder)


def stage_key(c, stage, cores, sid=None):
    if c["schema_version"] == 1:
        return dict(stage=stage, cores=cores, parameters=c["parameters"], tools=c["tools"])
    branch = stage_branch(stage)
    key = dict(stage=stage, cores=cores, parameters=c["parameters"],
                branch_parameters=options(c, branch),
                qc=c.get("qc", {}) if stage.startswith("qc_") else {},
                evaluation=c.get("evaluation", {}) if stage.startswith("export") else {},
                tools={k: c["tools"][k] for k in sorted(stage_tools(c, stage))})
    if stage == 'hite':
        s = sample(c, sid) if sid else c['samples'][0]
        key['sample_attributes'] = dict(taxon_group=s.get('taxon_group','plant'))
    if stage.startswith('export'):
        key['exports'] = c.get('exports', {})
    return key
