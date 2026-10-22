"""Exercise completed-stage import with actual Snakemake and synthetic upstream tools only."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from teflow.common import load_config, write_json, work, sha256
from teflow.runtime import freeze
from teflow.inputs import prepare
from teflow.stages import doctor

repo = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("recovery", repo / "scripts/recover_tetrimmer_v03.py")
recovery = importlib.util.module_from_spec(spec); spec.loader.exec_module(recovery)
old = load_config(Path(sys.argv[1]) / "fixture.json")
os.environ["TEFLOW_REPOSITORY"] = str(repo)
os.environ["TEFLOW_ALLOW_PRODUCTION"] = "1"
os.environ["PYTHONPATH"] = str(repo / "src") + os.pathsep + os.environ.get("PYTHONPATH", "")
cfg = Path(sys.argv[1]) / "fixture_recovery.json"
new = {k: copy.deepcopy(v) for k, v in old.items() if not k.startswith("_")}
new["run_id"] = "synthetic_recovery"
write_json(cfg, new)
new = load_config(cfg)
freeze(new)
root = Path(new["work_root"]) / new["run_id"]
doctor(new, root / "doctor")
prepare(new, "fixture")
for stage in ("edta", "rm_edta"):
    recovery.import_stage(old, new, "fixture", stage)
    record = json.loads((work(new, "fixture") / stage / "complete.json").read_text())
    assert record["details"]["execution"] == "imported_verified_outputs"
cmd = [sys.executable, "-m", "snakemake", "--snakefile", str(repo / "workflow/Snakefile"),
       "--directory", str(root), "--cores", "4", "--resources", "io_heavy=1", "mem_mb=4096",
       "--config", "teflow_config=" + str(cfg)]
dry = subprocess.run(cmd + ["--dry-run"], check=True, text=True, capture_output=True)
print(dry.stdout)
before = {stage: sha256(work(new,"fixture") / stage / "complete.json") for stage in ("edta","rm_edta")}
# 0.2 may rebuild disposable scheduler markers; imported scientific receipts must stay identical.
subprocess.run(cmd, check=True)
freeze(new)
assert all(sha256(work(new,"fixture") / stage / "complete.json")==h for stage,h in before.items())
assert (work(new, "fixture") / "export/complete.json").is_file()
print("PASS: historical recovery imports remain intact while scheduler markers are rebuilt")
