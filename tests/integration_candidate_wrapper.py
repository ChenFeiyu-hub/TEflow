"""Server handoff script using completed, hash-locked synthetic upstream results."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from teflow.common import digest, load_config, read_json, sha256, write_json
from teflow.runtime import config_fingerprint
from teflow.cli import VERSIONS

repo = Path(__file__).resolve().parents[1]
root = Path(tempfile.mkdtemp(prefix="teflow-candidate-wrapper-"))
genome = root / "genome.fa"; genome.write_text(">chr\nATGGCTGTTCAGACGTTT\n")
protein = root / "host.faa"; protein.write_text(">g1\nMAVQ\n")
selection = root / "families.txt"; selection.write_text("F1\n")
c = dict(schema_version=2, run_id="old", fixture_only=True, work_root=str(root / "work"), results_root=str(root / "results"),
         samples=[dict(id="demo", genome=str(genome), exclude_seqids=[])], branches=dict(edta=dict(enabled=True)),
         execution=dict(mode="server", threads=4, mem_mb=4096), parameters=dict(max_divergence=40), databases=dict(files=[]),
         evaluation=dict(promoter_analysis=False), qc=dict(host_proteins=str(protein), te_proteins=None, pfam=False),
         tools={k: dict(command=[sys.executable, str(repo / "tests/mock_tool.py"), k], expected_version=VERSIONS[k])
                for k in ("edta", "repeatmasker", "trf", "dustmasker")})
c["tools"]["diamond"] = dict(command=[sys.executable, str(repo / "tests/mock_tool.py"), "diamond"], expected_version="2.1.11")
cfg = root / "old.json"; write_json(cfg, c); c = load_config(cfg)
base = root / "work/old/demo"; prep = base / "prepared"; prep.mkdir(parents=True)
(prep / "genome.fa").write_bytes(genome.read_bytes())
write_json(prep / "manifest.json", dict(sequences=[dict(alias="chr", original_id="chr", length=18, included=True)],
           outputs={"genome.fa": sha256(prep / "genome.fa")}))
for stage, files in (("edta", {"library.fa": ">F1#DNA/hAT\nATGGCTGTTCAG\n"}),
                     ("rm_edta", {"genome.fa.out": "SW score\n100 0 0 0 chr 1 12 (6) + F1 DNA/hAT 1 12 (0) 1\n",
                                  "genome.fa.align": "100 0 0 0 chr 1 12 (6) F1#DNA/hAT 1 12 (0) raw1 1\nchr 1 ATGGCTGTTCAG 12\nF1#DNA 1 ATGGCTGTTCAG 12\n"})):
    folder = base / stage; folder.mkdir()
    for name, text in files.items(): (folder / name).write_text(text)
    material = dict(source="old_synthetic_fixture_not_current_source_fingerprint")
    write_json(folder / "complete.json", dict(status="complete", material=material, fingerprint=digest(material),
               outputs={str(folder / name): sha256(folder / name) for name in files}))
material = dict(config_sha256=config_fingerprint(c), inputs={"demo": {"genome": sha256(genome)}})
write_json(base.parent / "run_manifest.json", dict(material=material, fingerprint=digest(material)))
before = {str(p): sha256(p) for p in base.rglob("*") if p.is_file()}
review = root / "review"
env = dict(os.environ, PYTHONPATH=str(repo / "src"), TEFLOW_REPOSITORY=str(repo), PYTHON_BIN=sys.executable,
           TEFLOW_REVIEW_SAMPLE="demo", TEFLOW_REVIEW_BRANCH="edta")
args = ["bash", str(repo / "scripts/run_candidate_review.sh"), str(cfg), str(review), str(selection), "1"]
result = subprocess.run(args, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
(root / "run.log").write_text(result.stdout)
assert result.returncode == 0, result.stdout
assert "CANDIDATE_REVIEW_COMPLETED" in result.stdout
assert not Path(str(review)+".feedback.tar.gz.sha256").exists()
assert read_json(review / "protein_qc/complete.json")["summary"]["reported_HSPs"] == 0
assert all(sha256(p) == h for p, h in before.items())
again = subprocess.run(args, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
assert again.returncode != 0 and "already exists" in again.stdout
write_json(root / "validation.json", dict(status="pass", old_results_unchanged=True, existing_review_refused=True,
           scope="Actual bash/CLI handoff; synthetic upstream receipts and DIAMOND executable"))
print("PASS: candidate server wrapper, immutable old results, no overwrite", root)
