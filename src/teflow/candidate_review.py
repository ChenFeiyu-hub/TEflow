"""Independent, bounded candidate review of completed annotations.

Never freezes, migrates, edits or reruns the source annotation workflow.
All scientific outputs live in a new review directory. Decisions are separate
from evidence and are never inferred from CDS/protein overlap alone.
"""
import csv
import json
import shutil
import tarfile
from collections import Counter, defaultdict
from pathlib import Path
from . import __version__
from .common import (WorkflowError, digest, fasta, fasta_write_record, now, read_json,
                     sample, sha256, source_fingerprint, table, work, write_json)
from .branches import BRANCHES, enabled
from .evaluation import bp, tsv
from .formats import rm_out, bed_write, union
from .library_qc import check_proteins, host_proteins
from .migration import verify_receipt
from .repeat_alignments import Genome, iter_alignments, link_final, project_spans, read_library
from .review_context import native_loci, locus_context
from .runtime import config_fingerprint, run

ALIGN_FIELDS = ["alignment_id", "line", "query_alias", "seqid", "start", "end", "strand", "family_id", "classification",
                "score", "divergence", "repeat_start", "repeat_end", "repeat_left", "source_match_id", "upstream_group",
                "columns", "query_gap_columns", "repeat_gap_columns"]
LINK_FIELDS = ["fragment_id", "seqid", "start", "end", "strand", "final_family", "upstream_group", "status", "covered_bp",
               "uncovered_bp", "raw_families", "alignment_ids"]
DECISION_FIELDS = ["family_id", "biological_status", "catalog_action", "masking_action", "reviewer", "reviewed_at", "evidence", "reason"]
HSP_FIELDS = ["qseqid", "sseqid", "pident", "length", "evalue", "bitscore", "qstart", "qend", "sstart", "send", "qframe", "btop", "qlen", "slen"]


def from_workflow(c, sid, branch):
    if branch not in enabled(c): raise WorkflowError("Review branch is not enabled")
    root = work(c, sid); s = sample(c, sid)
    origin_path = root.parent / "run_manifest.json"; origin = read_json(origin_path)
    if origin["fingerprint"] != digest(origin["material"]) or origin["material"]["config_sha256"] != config_fingerprint(c):
        raise WorkflowError("Source run/config fingerprint mismatch")
    for key, expected in origin["material"]["inputs"][sid].items():
        if sha256(s[key]) != expected: raise WorkflowError("Source input changed: " + key)
    libstage, rmstage, _ = BRANCHES[branch]
    libdir, rmdir = root / libstage, root / rmstage
    receipts = [libdir / "complete.json", rmdir / "complete.json"]
    verify_receipt(libdir); verify_receipt(rmdir)
    prep = root / "prepared"; manifest = read_json(prep / "manifest.json")
    for rel, expected in manifest["outputs"].items():
        p = (prep / rel).resolve()
        if not p.is_relative_to(prep.resolve()) or sha256(p) != expected:
            raise WorkflowError("Prepared reference changed/outside source directory")
    from .alignment_artifacts import locate_alignment
    auxiliary = locate_alignment(rmdir)
    if not auxiliary["path"]:
        raise WorkflowError("No original alignment auxiliary found; inspect original execution directory without rerunning annotation")
    paths = dict(genome=s["genome"], library=libdir / "library.fa", rm_out=rmdir / "genome.fa.out",
                 rm_align=auxiliary["path"], prepared_manifest=prep / "manifest.json",
                 source_config=c["_config_path"], source_run_manifest=origin_path)
    if s.get("annotation"): paths["annotation"] = s["annotation"]
    proteins = c.get("qc", {}).get("host_proteins")
    if proteins and proteins != "derived": paths["host_proteins"] = proteins
    elif (prep / "host.cds.fa").exists(): paths["host_cds"] = prep / "host.cds.fa"
    if (prep / "host.cds.fa.mapping.tsv").exists(): paths["host_cds_mapping"] = prep / "host.cds.fa.mapping.tsv"
    if branch in ("heliano", "edta_plus_heliano"):
        hd = root / "heliano"
        verify_receipt(hd); receipts.append(hd / "complete.json")
        for name, rel in (("native_sites", "native_sites.tsv"), ("native_parents", "library.parents.tsv")):
            paths[name] = hd / rel
        if branch == "edta_plus_heliano": paths["combined_parents"] = libdir / "library.parents.tsv"
    qc = root / ("qc_" + branch)
    if (qc / "host.blastx.tsv").is_file():
        verify_receipt(qc); receipts.append(qc / "complete.json")
        paths["previous_host_hits"] = qc / "host.blastx.tsv"
    for i, p in enumerate(dict.fromkeys(receipts)): paths[f"source_receipt_{i}"] = p
    tool = c.get("tools", {}).get("diamond", {})
    return paths, dict(origin="verified_completed_workflow", run_id=c["run_id"], sample=sid, branch=branch,
                       source_fingerprint=origin["fingerprint"], alignment_source=auxiliary,
                       fixture_only=bool(c.get("fixture_only"))), tool


def hash_inputs(paths):
    result = {}
    for key, value in paths.items():
        path = Path(value).resolve()
        if not path.is_file(): raise WorkflowError("Missing review input: " + str(path))
        result[key] = dict(path=str(path), sha256=sha256(path), bytes=path.stat().st_size)
    return result


def verify_inputs(inputs):
    for r in inputs.values():
        if not Path(r["path"]).is_file() or sha256(r["path"]) != r["sha256"]:
            raise WorkflowError("Review input changed: " + r["path"])


def prepare_review(paths, output, families, provenance=None, tool=None, max_loci=10, flank=500, evalue=1e-5):
    output = Path(output).resolve()
    if output.exists(): raise WorkflowError("Review destination already exists; use a new directory")
    if not 1 <= max_loci <= 100 or not 0 <= flank <= 10000 or not 0 < evalue <= 1:
        raise WorkflowError("Invalid bounded-review parameters")
    paths = dict(paths, family_selection=families)
    inputs = hash_inputs(paths)
    paths = {k: v["path"] for k, v in inputs.items()}
    selected = [line.strip() for line in Path(families).read_text(encoding="utf-8-sig").splitlines()
                if line.strip() and not line.lstrip().startswith("#")]
    if not selected or len(selected) != len(set(selected)):
        raise WorkflowError("Family list must contain unique IDs, one per line")
    library, names = read_library(paths["library"])
    if set(selected) - library.keys(): raise WorkflowError("Unknown selected families: " + ", ".join(sorted(set(selected)-library.keys())))
    genome = Genome(paths["genome"])
    aliases = {k: k for k in genome.lengths}
    if paths.get("prepared_manifest"):
        aliases = {}
        for r in read_json(paths["prepared_manifest"])["sequences"]:
            if not r["included"]: continue
            if genome.lengths.get(r["original_id"]) != r["length"]:
                raise WorkflowError("Prepared seqid lengths differ from supplied genome")
            aliases[r["alias"]] = r["original_id"]
    output.mkdir(parents=True)
    try:
        blocks, metrics = [], Counter()
        with (output / "alignment_inventory.tsv").open("w", encoding="utf-8", newline="") as handle, \
             (output / "selected_alignments.jsonl").open("w", encoding="utf-8", newline="\n") as raw:
            writer = csv.DictWriter(handle, ALIGN_FIELDS, delimiter="\t", extrasaction="ignore", lineterminator="\n")
            writer.writeheader()
            for block in iter_alignments(paths["rm_align"], genome, library, aliases):
                writer.writerow(block)
                metrics["verified_raw_blocks"] += 1; metrics["verified_alignment_columns"] += block["columns"]
                if block["family_id"] in selected:
                    raw.write(json.dumps(block, separators=(",", ":")) + "\n")
                    metrics["selected_raw_blocks"] += 1
                blocks.append({k: v for k, v in block.items() if k not in ("qseq", "rseq")})
        records = rm_out(paths["rm_out"], {k: genome.lengths[v] for k, v in aliases.items()}, set(library))
        for r in records: r["seqid"] = aliases[r["seqid"]]
        links = list(link_final(records, blocks))
        table(output / "final_to_raw.tsv", links, LINK_FIELDS)
        table(output / "selected_final_to_raw.tsv", [r for r in links if r["final_family"] in selected or
              set(r["raw_families"].split(";")) & set(selected)], LINK_FIELDS)
        metrics.update({"final_link_" + k: v for k, v in Counter(r["status"] for r in links).items()})
        with (output / "candidates.fa").open("w", encoding="ascii") as handle:
            for fid in selected: fasta_write_record(handle, names[fid], library[fid])
        if paths.get("host_cds_mapping"):
            shutil.copyfile(paths["host_cds_mapping"], output / "protein_reference_mapping.tsv")
        if paths.get("previous_host_hits"):
            with open(paths["previous_host_hits"], encoding="utf-8") as old, (output / "previous_host_hits.tsv").open("w", encoding="utf-8") as dest:
                for line in old:
                    if line.split("\t", 1)[0].split("#", 1)[0] in selected: dest.write(line)
        loci = native_loci(paths, selected, library, genome, aliases)
        for fid in selected:
            ranked = sorted((b for b in blocks if b["family_id"] == fid),
                            key=lambda b: (-(b["repeat_end"]-b["repeat_start"])/len(library[fid]), -b["score"], b["alignment_id"]))
            picked = []
            for b in ranked:
                if any(x["seqid"] == b["seqid"] and x["start"] < b["end"] and x["end"] > b["start"]
                       for x in loci + picked if x["family_id"] == fid): continue
                picked.append(dict(family_id=fid, locus_id=f"raw{len(loci)+len(picked)+1:05d}", source="raw_alignment_fragment",
                                   seqid=b["seqid"], start=b["start"], end=b["end"], strand=b["strand"],
                                   alignment_id=b["alignment_id"], native_id="", parent_family_id="",
                                   sequence_evidence="verified_raw_alignment_not_full_insertion"))
                if len(picked) >= max_loci: break
            loci.extend(picked)
        context = locus_context(loci, genome, paths.get("annotation"), output, flank)
        table(output / "decisions.template.tsv", [dict(family_id=fid, biological_status="unreviewed",
              catalog_action="pending", masking_action="pending", reviewer="", reviewed_at="", evidence="", reason="")
              for fid in selected], DECISION_FIELDS)
        verify_inputs(inputs)
        summary = dict(metrics=metrics, context=context, selected_families=len(selected), automatic_acceptance=False,
                       locus_sampling="native representative plus nonoverlapping raw fragments ranked by library-span coverage, then score",
                       interpretation="Descriptive evidence; raw fragments are not verified insertions; CDS overlap is not a false-positive label")
        write_json(output / "evidence_summary.json", summary)
        material = dict(version=__version__, source_code=source_fingerprint(), inputs=inputs, families=selected,
                        provenance=provenance or dict(origin="explicit_files_hash_locked_at_review"),
                        parameters=dict(max_additional_loci_per_family=max_loci, flank=flank, evalue=evalue,
                                        diamond_target_limit=0, diamond_hsp_limit=0, genetic_code=1),
                        diamond=tool or dict(command=["diamond"], expected_version=None))
        products = {str(p.relative_to(output)).replace("\\", "/"): sha256(p) for p in sorted(output.rglob("*")) if p.is_file()}
        write_json(output / "review.json", dict(status="prepared", created=now(), material=material, fingerprint=digest(material), outputs=products))
        return dict(status="prepared", directory=str(output), summary=summary, next="review-plan; review-run for bounded protein QC only")
    except BaseException as exc:
        write_json(output / "prepare_failed.json", dict(error=str(exc), created=now(), action="Use a new directory after correcting inputs"))
        raise


def verify_review(root, require_inputs=True):
    root = Path(root).resolve(); record = read_json(root / "review.json")
    if record.get("status") != "prepared" or record["fingerprint"] != digest(record["material"]):
        raise WorkflowError("Invalid review receipt")
    for name, expected in record["outputs"].items():
        path = (root / name).resolve()
        if not path.is_relative_to(root) or not path.is_file() or sha256(path) != expected:
            raise WorkflowError("Review evidence changed: " + name)
    if require_inputs: verify_inputs(record["material"]["inputs"])
    return root, record


def review_plan(root, threads=8):
    root, record = verify_review(root)
    if not 1 <= threads <= 32: raise WorkflowError("Bounded review threads must be 1..32")
    m = record["material"]; inputs = m["inputs"]; folder = root / "protein_qc"
    if not any(k in inputs for k in ("host_proteins", "host_cds")):
        raise WorkflowError("Protein QC requires a supplied protein FASTA or translatable nuclear CDS; evidence preparation is still usable")
    protein = inputs["host_proteins"]["path"] if "host_proteins" in inputs else str(folder / "host.protein.fa")
    command = m["diamond"].get("command")
    if not isinstance(command, list) or not command or any(not isinstance(x, str) or not x for x in command):
        raise WorkflowError("Invalid DIAMOND command argv")
    db = str(folder / "host.db")
    commands = [command + ["version"], command + ["makedb", "--in", protein, "--db", db, "--threads", str(threads)],
                command + ["blastx", "--query", str(root / "candidates.fa"), "--db", db, "--out", str(folder / "host.expanded.tsv"),
                           "--threads", str(threads), "--evalue", str(m["parameters"]["evalue"]), "--max-target-seqs", "0",
                           "--max-hsps", "0", "--query-gencode", "1", "--outfmt", "6"] + HSP_FIELDS]
    return dict(status="planned", computation_launched=False, commands=commands, threads=threads,
                translated_CDS="host_proteins" not in inputs, genetic_code=1,
                source_review_fingerprint=record["fingerprint"], output_directory=str(folder),
                scope="Selected family sequences only; no genome TE discovery or RepeatMasker execution")


def executable_inventory(command):
    paths = set()
    executable = shutil.which(command[0])
    if executable: paths.add(Path(executable).resolve())
    paths.update(Path(x).resolve() for x in command if Path(x).is_file())
    if "-p" in command:
        prefix = Path(command[command.index("-p")+1])
        paths.update(prefix.glob("conda-meta/*.json"))
        binary = prefix / "bin/diamond"
        if binary.is_file(): paths.add(binary.resolve())
    return {str(p): sha256(p) for p in sorted(paths)}


def parse_hsps(path, candidates, threshold):
    """Validate coordinates and BTOP consumption before using HSP envelopes."""
    import math
    import re
    rows, spans, targets = [], defaultdict(list), defaultdict(set)
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        v = line.split("\t")
        if len(v) != len(HSP_FIELDS): raise WorkflowError(f"Expanded HSP column mismatch at line {n}")
        r = dict(zip(HSP_FIELDS, v)); fid = r["qseqid"].split("#", 1)[0]
        try:
            for k in ("qstart", "qend", "sstart", "send", "qframe", "qlen", "slen", "length"): r[k] = int(r[k])
            for k in ("pident", "evalue", "bitscore"): r[k] = float(r[k])
            if not all(math.isfinite(r[k]) for k in ("pident", "evalue", "bitscore")): raise ValueError("non-finite value")
            a, b = sorted([r["qstart"], r["qend"]]); frame = r["qframe"]
            if (fid not in candidates or r["qlen"] != len(candidates[fid]) or not 1 <= a <= b <= r["qlen"] or
                    not 1 <= r["sstart"] <= r["send"] <= r["slen"] or frame not in (-3, -2, -1, 1, 2, 3) or
                    (r["qend"] >= r["qstart"]) != (frame > 0) or not 0 <= r["evalue"] <= threshold or
                    not 0 <= r["pident"] <= 100 or r["bitscore"] < 0): raise ValueError("coordinate/score range")
            expected_frame = (r["qstart"]-1) % 3+1 if frame > 0 else -((r["qlen"]-r["qstart"]) % 3+1)
            if frame != expected_frame: raise ValueError("query frame phase")
            tokens = re.findall(r"\d+|[A-Z*\-][A-Z*\-]", r["btop"])
            if not tokens or "".join(tokens) != r["btop"]: raise ValueError("BTOP dialect")
            nq = ns = nc = 0
            for token in tokens:
                if token.isdigit(): nq += int(token); ns += int(token); nc += int(token)
                else:
                    if token == "--": raise ValueError("BTOP double gap")
                    nq += token[0] != "-"; ns += token[1] != "-"; nc += 1
            if 3*nq != b-a+1 or ns != r["send"]-r["sstart"]+1 or nc != r["length"]:
                raise ValueError("BTOP coordinate consumption")
        except (KeyError, ValueError) as exc:
            raise WorkflowError(f"Invalid expanded HSP line {n}: {exc}") from exc
        r.update(family_id=fid, start=a-1, end=b)
        rows.append(r); spans[fid].append((fid, a-1, b)); targets[fid].add(r["sseqid"])
    return rows, {k: union(v) for k, v in spans.items()}, targets


def run_review(root, threads=8, timeout=21600):
    plan = review_plan(root, threads); root = Path(root).resolve(); record = read_json(root / "review.json")
    if source_fingerprint() != record["material"]["source_code"]:
        raise WorkflowError("Review implementation changed after preparation; prepare a new review with this version")
    if timeout <= 0: raise WorkflowError("Timeout must be positive")
    folder = Path(plan["output_directory"])
    if folder.exists(): raise WorkflowError("Protein QC directory exists; preserve it and use a new review directory")
    folder.mkdir()
    try:
        inputs = record["material"]["inputs"]
        if plan["translated_CDS"]: host_proteins(inputs["host_cds"]["path"], folder / "host.protein.fa")
        protein = Path(plan["commands"][1][plan["commands"][1].index("--in")+1])
        protein_count = check_proteins(protein)
        inv = executable_inventory(record["material"]["diamond"]["command"])
        for i, command in enumerate(plan["commands"]):
            text = run(command, folder, folder / (["version", "makedb", "blastx"][i]+".log"), timeout, cpu_limit=threads)
            if i == 0:
                expected = record["material"]["diamond"].get("expected_version")
                if expected:
                    import re
                    if not re.search(r"(?<![\d.])" + re.escape(expected) + r"(?![\d.])", text):
                        raise WorkflowError("DIAMOND version differs from prepared expectation")
        if inv != executable_inventory(record["material"]["diamond"]["command"]):
            raise WorkflowError("DIAMOND installation changed during QC")
        verify_inputs(inputs)
        candidates, _ = read_library(root / "candidates.fa")
        rows, spans, targets = parse_hsps(folder / "host.expanded.tsv", candidates, record["material"]["parameters"]["evalue"])
        table(folder / "hsps.tsv", rows, ["family_id", "start", "end"] + HSP_FIELDS)
        table(folder / "family_protein_evidence.tsv", [dict(family_id=fid, length=len(seq), reported_targets=len(targets.get(fid, [])),
              reported_HSPs=sum(r["family_id"] == fid for r in rows), reported_span_union_bp=bp(spans.get(fid, [])),
              evidence_status="reported_similarity" if fid in spans else "no_reported_hit_not_negative_truth")
              for fid, seq in candidates.items()], ["family_id", "length", "reported_targets", "reported_HSPs", "reported_span_union_bp", "evidence_status"])
        if (root / "previous_host_hits.tsv").exists():
            previous, oldtargets = defaultdict(list), defaultdict(set)
            with (root / "previous_host_hits.tsv").open(encoding="utf-8") as old:
                for line in old:
                    v = line.rstrip().split("\t")
                    if len(v) != 8: raise WorkflowError("Unrecognized previous top-5 HSP fields")
                    fid = v[0].split("#", 1)[0]; a, b = sorted([int(v[6]), int(v[7])])
                    if fid not in candidates or not 1 <= a <= b <= len(candidates[fid]):
                        raise WorkflowError("Previous protein span is outside selected library")
                    previous[fid].append((fid, a-1, b)); oldtargets[fid].add(v[1])
            table(folder / "previous_vs_expanded.tsv", [dict(family_id=fid, previous_reported_targets=len(oldtargets[fid]),
                  expanded_reported_targets=len(targets.get(fid, [])), previous_span_union_bp=bp(previous[fid]),
                  expanded_span_union_bp=bp(spans.get(fid, [])), new_target_ids=";".join(sorted(targets.get(fid, set())-oldtargets[fid])),
                  note="Different search/reporting settings; differences are not a false-positive rate or guaranteed superset")
                  for fid in candidates], ["family_id", "previous_reported_targets", "expanded_reported_targets",
                  "previous_span_union_bp", "expanded_span_union_bp", "new_target_ids", "note"])
        projection = []; paired = []; insertions = []
        with (root / "selected_alignments.jsonl").open(encoding="utf-8") as handle:
            for line in handle:
                block = json.loads(line); fid = block["family_id"]
                p, ins = project_spans(block, [(a, b) for _, a, b in spans.get(fid, [])])
                paired.extend(p); insertions.extend(ins)
                projection.append(dict(alignment_id=block["alignment_id"], raw_family=fid, seqid=block["seqid"],
                                       start=block["start"], end=block["end"], paired_reported_protein_span_bp=bp(p), query_insertion_bp=bp(ins),
                                       outside_reported_spans_paired_bp=block["end"]-block["start"]-bp(p)-bp(ins)))
        table(folder / "raw_alignment_projection.tsv", projection, ["alignment_id", "raw_family", "seqid", "start", "end",
              "paired_reported_protein_span_bp", "query_insertion_bp", "outside_reported_spans_paired_bp"])
        bed_write(folder / "selected_raw_protein_span_support.bed", paired)
        bed_write(folder / "selected_raw_query_insertions.bed", insertions)
        material = dict(review_fingerprint=record["fingerprint"], plan=plan, source_code=source_fingerprint(),
                        executables=inv, protein_sha256=sha256(protein), proteins=protein_count)
        outputs = {str(p.relative_to(folder)): sha256(p) for p in sorted(folder.iterdir()) if p.is_file()}
        complete = dict(status="complete", created=now(), material=material, fingerprint=digest(material), outputs=outputs,
                        summary=dict(families=len(candidates), reported_HSPs=len(rows), automatic_decisions=False,
                                     scope="Reported nucleotide envelopes projected through raw alignments; not adjudicated final masks or FPR"))
        write_json(folder / "complete.json", complete)
        return dict(status="complete", directory=str(folder), summary=complete["summary"])
    except BaseException as exc:
        write_json(folder / "failed.json", dict(status="failed", created=now(), error=str(exc), action="Preserve logs; no automatic restart"))
        raise


def verify_local_receipt(folder, expected_review=None):
    record = read_json(folder / "complete.json")
    if record["status"] != "complete" or record["fingerprint"] != digest(record["material"]):
        raise WorkflowError("Invalid review product receipt")
    if expected_review and record["material"]["review_fingerprint"] != expected_review:
        raise WorkflowError("Review product belongs to another review")
    for name, expected in record["outputs"].items():
        p = (folder / name).resolve()
        if not p.is_relative_to(folder.resolve()) or not p.is_file() or sha256(p) != expected:
            raise WorkflowError("Review product changed: " + name)
    return record


def export_decisions(root, decisions, output):
    root, record = verify_review(root)
    output = Path(output).resolve()
    if output.exists(): raise WorkflowError("Decision export destination exists")
    rows = tsv(decisions); expected = set(record["material"]["families"])
    if len(rows) != len(expected) or {r.get("family_id") for r in rows} != expected:
        raise WorkflowError("Decisions must contain every selected family exactly once")
    statuses = {"unreviewed", "supported_te", "gene_capture_candidate", "boundary_uncertain", "likely_host_fragment", "unresolved"}
    for row in rows:
        if set(DECISION_FIELDS) - row.keys() or row["biological_status"] not in statuses or row["catalog_action"] not in {"pending", "retain", "exclude"} or row["masking_action"] not in {"pending", "include", "exclude"}:
            raise WorkflowError("Invalid review decision fields")
        changed = row["biological_status"] != "unreviewed" or row["catalog_action"] != "pending" or row["masking_action"] != "pending"
        if changed and not all(row[k].strip() for k in ("reviewer", "reviewed_at", "evidence", "reason")):
            raise WorkflowError("A decision needs reviewer, date, evidence and reason")
        if row["masking_action"] == "include" and (row["catalog_action"] != "retain" or row["biological_status"] not in {"supported_te", "gene_capture_candidate"}):
            raise WorkflowError("Mask-library inclusion requires explicit retained TE/gene-capture evidence")
    seqs, names = read_library(root / "candidates.fa")
    output.mkdir(parents=True)
    counts = {}
    for action, value, name in (("catalog_action", "retain", "catalog.fa"), ("masking_action", "include", "mask_library.fa")):
        selected = [r["family_id"] for r in rows if r[action] == value]; counts[name] = len(selected)
        with (output / name).open("w", encoding="ascii") as f:
            for fid in selected: fasta_write_record(f, names[fid], seqs[fid])
    table(output / "decisions.tsv", rows, DECISION_FIELDS)
    material = dict(review_fingerprint=record["fingerprint"], source_code=source_fingerprint(), decisions_sha256=sha256(decisions))
    write_json(output / "complete.json", dict(status="complete", material=material, fingerprint=digest(material), created=now(),
               outputs={p.name: sha256(p) for p in output.iterdir() if p.is_file()}, counts=counts,
               interpretation="Selected candidate libraries only; not a whole-run replacement or genomic mask. Future remapping is explicit."))
    return dict(status="exported", directory=str(output), counts=counts, genome_mask_created=False)


def pack_review(root, output):
    root, record = verify_review(root, require_inputs=False)
    output = Path(output).resolve()
    if output.exists() or output.is_relative_to(root): raise WorkflowError("Use a new archive outside the review directory")
    qc = root / "protein_qc"
    if (qc / "complete.json").exists(): verify_local_receipt(qc, record["fingerprint"])
    selected, omitted = [], []
    for p in sorted(root.rglob("*")):
        if not p.is_file(): continue
        if p.is_symlink(): raise WorkflowError("Review package may not follow symlinks")
        rel = str(p.relative_to(root)).replace("\\", "/")
        if p.suffix == ".dmnd" or p.name == "host.protein.fa": omitted.append(rel); continue
        selected.append(p)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, "w:gz") as archive:
        for p in selected: archive.add(p, arcname="review/"+str(p.relative_to(root)).replace("\\", "/"), recursive=False)
        import io
        payload = json.dumps(dict(files={str(p.relative_to(root)).replace("\\", "/"): sha256(p) for p in selected},
                                  omitted=omitted, original_inputs_included=False), indent=2).encode()
        info = tarfile.TarInfo("bundle_manifest.json"); info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
    return dict(archive=str(output), files=len(selected), omitted=omitted)
