"""Real Snakemake, synthetic reviewed case, and a TEtrimmer command that cannot rerun.

Case constants are replaced only inside this test process. The production CLI
offers no case override and rejects fixture runs.
"""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

from teflow.common import write_json, read_json, load_config, sha256, source_fingerprint
from teflow.cli import VERSIONS
from teflow.migration import import_stage
from teflow.teaid_recovery import validate_reviewed_outputs, import_reviewed_tetrimmer

repo = Path(__file__).resolve().parents[1]
target = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="reviewed-import-test-"))
target.mkdir(exist_ok=True, parents=True)
if any(target.iterdir()):
    raise SystemExit("Use an empty integration fixture directory")
os.environ.update(TEFLOW_REPOSITORY=str(repo), TEFLOW_ALLOW_PRODUCTION="1", PYTHONPATH=str(repo / "src"))
env = dict(os.environ, PATH=str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", ""))


def command(args):
    r = subprocess.run(list(map(str, args)), env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    with (target / "commands.log").open("a") as f:
        f.write(repr(list(map(str, args))) + "\n" + r.stdout + "\n")
    if r.returncode:
        raise AssertionError(r.stdout[-7000:])
    return r.stdout


def cli(config, *args):
    return command([sys.executable, "-m", "teflow", args[0], "--config", config, *args[1:]])


genome = target / "genome.fa"; genome.write_text(">OriginalChr\n" + "ACGT" * 40 + "\n")
old = dict(schema_version=2, run_id="old", fixture_only=True, work_root=str(target / "work"),
           results_root=str(target / "results"), execution=dict(mode="server", threads=4, mem_mb=4096),
           parameters=dict(max_divergence=40), samples=[dict(id="fixture", genome=str(genome))],
           branches={"edta":{"enabled":True}, "edta_tetrimmer":{"enabled":True}},
           databases=dict(pfam_dir=str(target / "fake_pfam"), files=[]),
           tools={k:dict(command=[sys.executable, str(repo / "tests/mock_tool.py"), k], expected_version=v) for k,v in VERSIONS.items()})
oldpath = target / "old.json"; write_json(oldpath, old)
cli(oldpath, "freeze"); cli(oldpath, "doctor", "--output", target / "work/old/doctor")
cli(oldpath, "prepare", "--sample", "fixture")
for stage in ("edta", "rm_edta"):
    cli(oldpath, "stage", "--sample", "fixture", "--name", stage)
source = target / "work/old/fixture/tetrimmer"; upstream = source / "upstream"
upstream.mkdir(parents=True)
(upstream / "summary.txt").write_text("input_name,output_name,status,evaluation,low_copy\nE0000001,E0000001,processed,Good,False\nE0000002,E0000002,skipped,NaN,False\n")
(upstream / "TEtrimmer_consensus_merged.fasta").write_text(">E0000001#DNA/hAT\nACGTACGTACGT\n")
(upstream / "proof.fa").write_text(">sequence\nACGTACGTACGT\n")
error = upstream / "error_file.txt"; error.write_text("rm: cannot remove 'header': No such file or directory\n")
(source / "run.log").write_text("synthetic producer completed\n")
write_json(source / "run.log.command.json",dict(status="complete",returncode=0,argv=["synthetic-original-producer"]))
write_json(source / "failed.json",dict(status="failed",error="synthetic cleanup quarantine"))
write_json(source / "request.json",dict(fixture_only=True))
files = {p.relative_to(source).as_posix():sha256(p) for p in source.rglob("*") if p.is_file()}
case = dict(case_id="synthetic_review_case", sample="fixture", files=files, regenerated_audit_files=[],
            input_library_sha256=sha256(target / "work/old/fixture/edta/library.fa"),
            error_files=[dict(path="error_file.txt",bytes=error.stat().st_size,sha256=sha256(error))],
            affected_msa="upstream/proof.fa",affected_id="E0000001",sequence_count=1,consensus_length=12,consensus_threshold=.7,
            expected_counts=dict(input_families=2,terminal_inputs=2,retained_families=1),
            expected_origins={"refined_consensus":1},review_scope="synthetic contract only",orf_tables="fixture only",
            source_sha256=source_fingerprint(),future_execution="synthetic command deliberately refuses computation")
forbid = target / "forbid_tetrimmer.py"
forbid.write_text("import sys\nif any(x in sys.argv for x in ['--help','--version']):\n print('tetrimmer 1.7.2 --input_file --pfam_dir --continue_analysis --num_threads')\nelse:\n raise SystemExit('ERROR: imported TEtrimmer was scheduled again')\n")
new = copy.deepcopy(old); new["run_id"] = "new"
new["tools"]["tetrimmer"]["command"] = [sys.executable, str(forbid)]
newpath = target / "new.json"; write_json(newpath,new)
cli(newpath,"doctor","--output",target / "work/new/doctor"); cli(newpath,"freeze")
oc, nc = load_config(oldpath), load_config(newpath)
for stage in ("edta","rm_edta"):
    import_stage(oc,nc,"fixture",stage)
with patch("teflow.teaid_recovery.CASE",case), patch("teflow.reviewed_teaid_case.CASE",case):
    review=validate_reviewed_outputs(source,target / "work/old/fixture/edta/library.fa")
    record=import_reviewed_tetrimmer(oc,nc,review)
assert record["computation_rerun"] is False
base=target / "work/new/fixture"
assert read_json(base / "tetrimmer/complete.json")["details"]["status"]=="complete_with_reviewed_warning"
assert (base / "tetrimmer/source_evidence/failed.json").exists()
before={str(p):sha256(p) for p in base.rglob("*") if p.is_file() and "/tetrimmer/" in str(p)}
smk=[sys.executable,"-m","snakemake","--snakefile",repo / "workflow/Snakefile","--directory",target / "work/new",
     "--cores","4","--resources","io_heavy=1","mem_mb=4096","--config","teflow_config="+str(newpath)]
target_marker=base / ".dag/export_edta_tetrimmer.done"
dry=command(smk+["--dry-run","--",target_marker])
assert "stage=tetrimmer" not in dry
# Exercise the actual server entry point as well: another successful doctor
# attempt must preserve the canonical receipt used by the imported stages.
server_dry=command(["bash",repo / "scripts/run_server.sh",newpath,"--dry-run","--target-stage","export_edta_tetrimmer"])
assert "stage=tetrimmer" not in server_dry
command(smk+["--",target_marker])
assert (base / "rm_refined/complete.json").exists()
assert (target / "results/new/fixture/edta_tetrimmer/manifest.json").exists()
assert all(sha256(p)==h for p,h in before.items())
assert all(sha256(source / p)==h for p,h in files.items())
command(smk+["--",target_marker])
cli(newpath,"pack-feedback","--output",target / "feedback.tar.gz")
write_json(target / "validation.json",dict(status="pass",scope="Real Snakemake with synthetic upstream outputs",
    checks=["reviewed_import_preserves_original_failure","known_error_retained_in_new_receipt","new_actual_producer_provenance",
            "no_tetrimmer_rescheduling","server_entrypoint_dry_run","downstream_repeatmasker_qc_export","unchanged_completed_resume","feedback_pack"]))
print("PASS: reviewed import, immutable old evidence, downstream ET completion, no TEtrimmer rerun")
