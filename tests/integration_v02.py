"""Real scheduler and synthetic adapters: migration, independent exports and integrity."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from teflow.common import read_json, write_json, sha256
from teflow.cli import VERSIONS, OPTIONAL_VERSIONS
from teflow.branches import BRANCHES
from teflow.evaluation import tsv

repo = Path(__file__).resolve().parents[1]
target = Path(sys.argv[1]).resolve() if len(sys.argv)>1 else Path(tempfile.mkdtemp(prefix="teflow-v02-"))
target.mkdir(exist_ok=True, parents=True)
if any(target.iterdir()): raise SystemExit("Use an empty fixture directory")
env = dict(os.environ, TEFLOW_REPOSITORY=str(repo),TEFLOW_ALLOW_PRODUCTION="1",PYTHONPATH=str(repo / "src"),PATH=str(Path(sys.executable).parent)+os.pathsep+os.environ.get("PATH",""))
log = target / "commands.log"
def command(args, expect=0, contains=None):
    r = subprocess.run(list(map(str,args)),env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    with log.open("a") as f: f.write(repr(list(map(str,args))) + "\n" + r.stdout + "\n")
    if (r.returncode != 0) != (expect != 0) or (contains and contains not in r.stdout):
        raise AssertionError("Command contract failed: " + repr(args) + "\n" + r.stdout[-7000:])
    return r
def cli(cfg, *args, **kw):
    return command([sys.executable,"-m","teflow",args[0],"--config",cfg,*args[1:]],**kw)

genome = target / "genome.fa"
# >1 MB physical FASTA exercises Snakemake's mtime fallback, while biological size is tiny.
genome.write_text(">OriginalChr\n" + "ACGT"*40 + "\n>Mt\n" + "A"*20 + "\n" + "\n"*1100000)
old = dict(schema_version=1,run_id="old",fixture_only=True,work_root=str(target / "work"),results_root=str(target / "results"),
           execution=dict(mode="server",threads=4,mem_mb=4096), parameters=dict(max_divergence=40),
           samples=[dict(id="fixture",genome=str(genome),exclude_seqids=["Mt"])],
           databases=dict(pfam_dir=str(target / "fake_pfam"),files=[]),
           tools={k:dict(command=[sys.executable,str(repo / "tests/mock_tool.py"),k],expected_version=v) for k,v in VERSIONS.items()})
oldcfg = target / "old.json"; write_json(oldcfg,old)
cli(oldcfg,"freeze"); cli(oldcfg,"doctor","--output",target / "work/old/doctor")
cli(oldcfg,"prepare","--sample","fixture")
for stage in ("edta","rm_edta"): cli(oldcfg,"stage","--sample","fixture","--name",stage)
old_receipt = sha256(target / "work/old/fixture/edta/complete.json")

prom = target / "promoters.bed"; prom.write_text("OriginalChr\t0\t100\tg1\t0\t+\nOriginalChr\t100\t160\tg2\t0\t-\n")
ref = target / "te_reference.gff3"; ref.write_text("OriginalChr\tcurated\ttransposable_element\t1\t16\t.\t+\t.\tID=r1;Classification=DNA/hAT\n")
reflib = target / "reference.fa"; reflib.write_text(">curated1#DNA/hAT\nACGTACGTACGT\n")
host = target / "host.faa"; host.write_text(">host\nMAGVQRS\n")
new = copy.deepcopy(old)
new.update(schema_version=2,run_id="new",branches={b:dict(enabled=True) for b in BRANCHES},
           qc=dict(host_proteins=str(host),te_proteins=None,pfam=True),evaluation=dict(widths=[4,6,20]))
new["tools"].update({k:dict(command=[sys.executable,str(repo / "tests/mock_tool.py"),k],expected_version=v) for k,v in OPTIONAL_VERSIONS.items()})
new["samples"][0].update(promoters_bed=str(prom),reference_te=str(ref),reference_library=str(reflib))
cfg = target / "new.json"; write_json(cfg,new)
cli(cfg,"freeze"); cli(cfg,"doctor","--output",target / "work/new/doctor","--dependencies")
for stage in ("edta","rm_edta"):
    cli(cfg,"import-stage","--source-config",oldcfg,"--sample","fixture","--name",stage)
cli(cfg,"import-stage","--source-config",oldcfg,"--sample","fixture","--name","tetrimmer",expect=2,contains="only completed EDTA")
assert sha256(target / "work/old/fixture/edta/complete.json") == old_receipt

base = target / "work/new/fixture"; out = target / "results/new/fixture"
smk = [sys.executable,"-m","snakemake","--snakefile",repo / "workflow/Snakefile","--directory",target / "work/new", "--cores","4","--resources","io_heavy=1","mem_mb=4096","--config","teflow_config="+str(cfg)]
command(smk+["--dry-run"])
# Branch export can finish without waiting for HiTE or TEtrimmer.
command(smk+["--",str(base / ".dag/export_edta.done")])
assert (out / "edta/manifest.json").exists() and not (out / "manifest.json").exists()
assert not (base / "hite").exists()
command(smk)
assert read_json(out / "manifest.json")["branches"] == list(BRANCHES)
assert read_json(out / "comparison.json")["selected_branch"] is None
assert read_json(out / "heliano/evaluation.json")["reference"]["completeness"] == "not_assumed"
assert tsv(out / "hite/classification_inventory.tsv")[0]["tier"] == "te"
assert (out / "heliano/native_sites.tsv").read_text().splitlines()[1].startswith("OriginalChr\t64\t88\t")
assert len(tsv(out / "edta_plus_heliano/parents.tsv")) == 3
assert len(tsv(out / "reference_plus_edta/parents.tsv")) == 3
assert read_json(out / "edta/library_qc/qc.json")["evidence"]["host_protein"] == "executed"
assert read_json(out / "edta/library_qc/qc.json")["evidence"]["pfam"] == "executed_standard_code_six_frames"
assert len(tsv(out / "edta/promoter_opportunities.tsv")) == 10
authoritative = {str(p):sha256(p) for p in base.glob("*/complete.json")}
manifest_hash = sha256(base / "prepared/manifest.json")
command(smk)
# Force scheduler bookkeeping reconstruction, retaining immutable scientific receipts.
(base / ".dag/prepared.done").unlink()
os.utime(genome,None)
command(smk)
assert sha256(base / "prepared/manifest.json") == manifest_hash
assert all(sha256(p)==h for p,h in authoritative.items())
# Same-size input mutation must fail before scheduling, then restoration resumes cleanly.
original = genome.read_bytes()
genome.write_bytes(original.replace(b"ACGT",b"TCGT",1))
cli(cfg,'freeze',expect=1,contains="Inputs/config/source/database changed")
genome.write_bytes(original)
mask = out / "edta/te.mask.bed"; content = mask.read_bytes(); mask.write_bytes(b"OriginalChr\t0\t13\n")
cli(cfg,'freeze',expect=1,contains="Completed output changed")
mask.write_bytes(content)
cli(cfg,"freeze"); cli(cfg,"status"); cli(cfg,"pack-feedback","--output",target / "feedback.tar.gz")
command(["bash",repo / "scripts/run_server.sh",cfg,"--dry-run","--target-stage","export_heliano"])
command(["bash",repo / "scripts/run_server.sh",cfg,"--target-stage","invalid"],expect=2,contains="not enabled")
write_json(target / "validation.json",dict(status="pass",scope="Real Snakemake; seven synthetic upstream branches; no biological accuracy claim",
    checks=["schema1_EDTA_RM_import","reject_TTE_import","standalone_EDTA_export","seven_branch_DAG","protein_Pfam_QC_contracts",
            "native_coordinate_restoration","exact_alias_assembly","reference_agreement","promoter_opportunities","completed_resume",
            "large_unchanged_input_touch","scheduler_marker_reconstruction","changed_input_refused","changed_export_refused","feedback_archive","server_target_preflight"],
    branches=list(BRANCHES),genome_physical_bytes=len(original)))
print("PASS: v0.2 migration, seven branches, independent exports, coordinate/QC/evaluation contracts, immutable resume")
