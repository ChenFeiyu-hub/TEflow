"""Generic genome-only workflow, no annotation, RNA, promoters or protein database."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from teflow.common import read_json, write_json
from teflow.cli import VERSIONS

repo = Path(__file__).resolve().parents[1]
root = Path(tempfile.mkdtemp(prefix="teflow-generic-genome-"))
genome = root / "genome.fa"; genome.write_text(">OriginalChr\n" + "ACGT"*40 + "\n")
c = dict(schema_version=2, run_id="generic", fixture_only=True, work_root=str(root / "work"), results_root=str(root / "results"),
         samples=[dict(id="arbitrary_plant", genome=str(genome), exclude_seqids=[])], branches=dict(edta=dict(enabled=True)),
         execution=dict(mode="server", threads=4, mem_mb=4096), parameters=dict(max_divergence=40), databases=dict(files=[]),
         evaluation=dict(promoter_analysis=False), qc=dict(host_proteins=None, te_proteins=None, pfam=False),
         tools={k: dict(command=[sys.executable, str(repo / "tests/mock_tool.py"), k], expected_version=VERSIONS[k])
                for k in ("edta", "repeatmasker", "trf", "dustmasker")})
cfg = root / "config.json"; write_json(cfg, c)
env = dict(os.environ, PYTHONPATH=str(repo / "src"), TEFLOW_REPOSITORY=str(repo), TEFLOW_ALLOW_PRODUCTION="1",
           PATH=str(Path(sys.executable).parent)+os.pathsep+os.environ.get("PATH", ""))
with (root / "commands.log").open("w") as log:
    def command(args):
        subprocess.run(list(map(str, args)), env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
    for action in ("freeze", "doctor"):
        command([sys.executable, "-m", "teflow", action, "--config", cfg] +
                (["--output", root / "work/generic/doctor"] if action == "doctor" else []))
    command([sys.executable, "-m", "snakemake", "--snakefile", repo / "workflow/Snakefile", "--directory", root / "work/generic",
             "--cores", "4", "--resources", "io_heavy=1", "mem_mb=4096", "--config", "teflow_config=" + str(cfg)])
out = root / "results/generic/arbitrary_plant"
assert (out / "edta/te_fragments.gff3").is_file()
assert (out / "edta/genome.softmasked.fa").is_file()
assert not (out / "edta/promoters.tsv").exists()
assert not (out / "edta/promoter_opportunities.tsv").exists()
assert read_json(out / "edta/evaluation.json")["gene_context"] == "not_provided"
receipt = read_json(root / "work/generic/arbitrary_plant/rm_edta/complete.json")
assert any(name.endswith("genome.fa.align") for name in receipt["outputs"])
assert read_json(out / "manifest.json")["selected_branch"] is None
write_json(root / "validation.json", dict(status="pass", arbitrary_sample_id=True, annotation_required=False,
           promoter_outputs_present=False, alignment_registered=True, scope="Actual scheduler, synthetic upstream tools"))
print("PASS: genome-only generic workflow and registered alignment", root)
