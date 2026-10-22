"""Run real Snakemake against deterministic fake tools, then assert exported contracts."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from teflow.common import write_json, read_json
from teflow.cli import VERSIONS

repo = Path(__file__).resolve().parents[1]
target = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="teflow-fixture-"))
target.mkdir(parents=True, exist_ok=True)
if any(target.iterdir()):
    raise SystemExit("Fixture output directory must be empty")
(target / "genome.fa").write_text(">OriginalChr\n" + "ACGT" * 40 + "\n>Mt\n" + "A" * 20 + "\n")
c = dict(schema_version=1, run_id="synthetic_only", fixture_only=True,
         work_root=str(target / "work"), results_root=str(target / "results"),
         execution=dict(mode="server", threads=4, mem_mb=4096), parameters=dict(max_divergence=40),
         samples=[dict(id="fixture", genome=str(target / "genome.fa"), exclude_seqids=["Mt"])],
         databases=dict(pfam_dir=str(target / "fake_pfam"), files=[]),
         tools={name: dict(command=[sys.executable, str(repo / "tests/mock_tool.py"), name], expected_version=version) for name, version in VERSIONS.items()})
cfg = target / "fixture.json"; write_json(cfg, c)
env = dict(os.environ, TEFLOW_ALLOW_PRODUCTION="1", TEFLOW_REPOSITORY=str(repo),
           PYTHONPATH=str(repo / "src") + os.pathsep + os.environ.get("PYTHONPATH", ""))
def command(args):
    subprocess.run(args, check=True, env=env)
command([sys.executable, "-m", "teflow", "freeze", "--config", str(cfg)])
command([sys.executable, "-m", "teflow", "doctor", "--config", str(cfg), "--output", str(target / "work/synthetic_only/doctor")])
smk = [sys.executable, "-m", "snakemake", "--snakefile", str(repo / "workflow/Snakefile"),
       "--directory", str(target / "work/synthetic_only"), "--cores", "4", "--resources", "io_heavy=1", "mem_mb=4096",
       "--config", "teflow_config=" + str(cfg)]
command(smk + ["--dry-run"])
command(smk)
out = target / "results/synthetic_only/fixture"
assert (out / "edta/te.mask.bed").read_text() == "OriginalChr\t0\t12\n"
assert (out / "edta/repeat.mask.bed").read_text() == "OriginalChr\t0\t12\nOriginalChr\t19\t31\n"
assert read_json(out / "manifest.json")["fixture_only"] is True
assert read_json(out / "comparison.json")["selected_branch"] is None
command(smk)  # The completed DAG must be resumable without recomputation.
command([sys.executable, "-m", "teflow", "freeze", "--config", str(cfg)])
command([sys.executable, "-m", "teflow", "pack-feedback", "--config", str(cfg), "--output", str(target / "feedback.tar.gz")])
# A completed Snakemake target is insufficient if an exported artifact was altered.
mask = out / "edta/te.mask.bed"
original = mask.read_text()
mask.write_text("OriginalChr\t0\t13\n")
tamper = subprocess.run([sys.executable, "-m", "teflow", "freeze", "--config", str(cfg)], env=env, capture_output=True, text=True)
assert tamper.returncode != 0 and "Completed output changed" in tamper.stderr
mask.write_text(original)
write_json(target / "validation.json", dict(status="pass", scope="Synthetic adapters + actual Snakemake DAG, not upstream biology", output=str(out)))
print("PASS: actual Snakemake / synthetic upstream interfaces / exported coordinate and masking contracts")
