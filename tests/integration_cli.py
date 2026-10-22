"""Exercise the public lifecycle with actual Snakemake and synthetic upstream tools.

--installed verifies that no checkout paths are used for runtime code/recipes.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import teflow
from teflow.assets import asset_root, asset_path
from teflow.cli import VERSIONS
from teflow.common import read_json, write_json, sha256, source_fingerprint

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--installed", action="store_true")
p.add_argument("--expected-fingerprint")
args = p.parse_args()
repo = Path(__file__).resolve().parents[1]
root = Path(tempfile.mkdtemp(prefix="teflow-cli-"))
env = dict(os.environ)
if args.installed:
    env.pop("TEFLOW_REPOSITORY", None)
    env.pop("PYTHONPATH", None)
    assert not Path(teflow.__file__).resolve().is_relative_to(repo), teflow.__file__
    assert asset_root().name == "_assets", asset_root()
else:
    env.update(TEFLOW_REPOSITORY=str(repo), PYTHONPATH=str(repo / "src"))
if args.expected_fingerprint:
    assert source_fingerprint() == args.expected_fingerprint, (source_fingerprint(), args.expected_fingerprint)
# A tool environment may have no teflow import path/site packages. Exercise the
# two script bootstraps under -I -S; importing only does not launch upstream tools.
bootstrap_probe = '''import importlib.util,json,runpy,sys
assert importlib.util.find_spec("teflow") is None
runpy.run_path(sys.argv[1], run_name="wrapper_import_probe")
import teflow
print(json.dumps({"module":teflow.__file__}))
'''
for script in ("run_tetrimmer_isolated.py", "prepare_teaid_database.py"):
    probe = subprocess.run([sys.executable, "-I", "-S", "-c", bootstrap_probe, str(asset_path("scripts/" + script))],
                           cwd=root, env=env, capture_output=True, text=True, check=True)
    assert Path(json.loads(probe.stdout)["module"]).resolve() == Path(teflow.__file__).resolve()
# Validate the actual HiTE bind argv with a stubbed exec, never a real container.
import runpy
from unittest.mock import patch
image = root / "fixture.sif"; image.write_text("stub, not a container")
wrapper = runpy.run_path(str(asset_path("scripts/run_hite_container.py")), run_name="hite_wrapper_probe")
with patch("sys.argv", ["wrapper", "--image", str(image), "--bind", str(root), "--", "--teflow-probe"]), \
     patch("shutil.which", return_value="apptainer"), patch("os.execvp") as execute:
    wrapper["main"]()
    argv = execute.call_args.args[1]
    probe_bind = next(value for value in argv if value.endswith(":/teflow_probe.py:ro"))
    assert Path(probe_bind.rsplit(":/teflow_probe.py:ro", 1)[0]).resolve() == Path(teflow.__file__).with_name("upstream_probe.py").resolve()
genome = root / "genome.fa"
genome.write_text(">OriginalChr\n" + "ACGT" * 40 + "\n")
cfg = root / "fixture.local.json"
log = root / "commands.log"


def command(*items, ok=0):
    proc = subprocess.run([sys.executable, "-m", "teflow", *map(str, items)], env=env,
                          cwd=root, capture_output=True, text=True)
    with log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(list(map(str, items))) + "\n" + proc.stdout + proc.stderr + "\n")
    assert proc.returncode == ok, (items, proc.returncode, str(log), proc.stderr[-4000:])
    return proc.stdout


command("init", "--root", root, "--genome", genome, "--sample-id", "generic_plant", "--run-id", "fixture",
        "--profile", "edta", "--threads", 4, "--mem-mb", 4096)
c = read_json(cfg)
c["fixture_only"] = True
c["tools"] = {name: dict(command=[sys.executable, str(repo / "tests/mock_tool.py"), name], expected_version=VERSIONS[name])
              for name in ("edta", "repeatmasker", "trf", "dustmasker")}
write_json(cfg, c)
command("plan", "--config", cfg)
assert not (root / "work").exists()
command("check", "--config", cfg)
assert not (root / "work/fixture/run_manifest.json").exists()
command("run", "--config", cfg, "--dry-run")
assert (root / "work/fixture/run_manifest.json").exists()
assert not (root / "work/fixture/generic_plant/edta").exists()
command("run", "--config", cfg, "--target-stage", "export_edta")
assert not (root / "work/fixture/generic_plant/export/complete.json").exists()
command("run", "--config", cfg)
receipt = root / "work/fixture/generic_plant/edta/complete.json"
before = sha256(receipt)
command("run", "--config", cfg, "--resume")
assert sha256(receipt) == before
status = json.loads(command("status", "--config", cfg))
assert status["status"] == "complete"
out = root / "results/fixture/generic_plant"
assert (out / "edta/te_fragments.gff3").is_file()
assert (out / "edta/genome.softmasked.fa").is_file()
assert not (out / "edta/promoters.tsv").exists()
command("pack-feedback", "--config", cfg, "--output", root / "feedback.tar.gz")
command("run", "--config", cfg, "--target-stage", "hite", ok=2)
assert len(list((root / "work/fixture/launches").glob("*.json"))) == 4
# Freeze detects output tampering before another scheduler invocation.
mask = out / "edta/te.mask.bed"
mask.write_text("OriginalChr\t0\t13\n")
command("run", "--config", cfg, ok=2)
assert len(list((root / "work/fixture/launches").glob("*.json"))) == 5
assert json.loads(command("status", "--config", cfg))["launcher"]["status"] == "failed"
write_json(root / "validation.json", dict(status="pass", installed_wheel=args.installed,
           module=str(Path(teflow.__file__).resolve()), assets=str(asset_root()), source_fingerprint=source_fingerprint(),
           verified=["isolated_wrapper_imports", "hite_probe_bind", "generic_init", "plan_read_only", "check_without_freeze", "dry_run_without_discovery",
                     "targeted_run", "full_export", "resume_cache", "status", "feedback", "invalid_target", "tamper_stop"],
           scope="Real scheduler, synthetic upstream tools; not a biological benchmark"))
print("PASS: public CLI lifecycle", root)
