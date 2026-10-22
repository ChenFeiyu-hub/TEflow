"""Create a new run for the verified Zenodo image, preserving the old run unchanged."""
import argparse
import copy
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from teflow.common import WorkflowError, ID, write_json, load_config
from teflow.hite_image import inspect_image


def prepare(config, output, run_id, image=None, repo=REPO):
    config, output, repo = Path(config).resolve(), Path(output).resolve(), Path(repo).resolve()
    old = load_config(config)
    if old["schema_version"] != 2 or not old.get("branches", {}).get("hite", {}).get("enabled"):
        raise WorkflowError("Use the existing schema-2 comparison configuration with HiTE enabled")
    if not ID.fullmatch(run_id) or run_id == old["run_id"] or output.exists():
        raise WorkflowError("A new run_id and a new configuration output are required")
    for name in ("work_root", "results_root"):
        if (Path(old[name]) / run_id).exists():
            raise WorkflowError("New run directory already exists: " + str(Path(old[name]) / run_id))
    source = Path(image or old["tools"]["hite"].get("image", "")).resolve()
    print("Verifying the complete HiTE SIF checksum; no download or installation...", file=sys.stderr, flush=True)
    identity = inspect_image(source, require_known=True)
    c = {k: copy.deepcopy(v) for k, v in old.items() if not k.startswith("_")}
    c["run_id"] = run_id
    hite = c["tools"]["hite"]
    cmd = hite["command"]
    indices = [i for i, token in enumerate(cmd) if Path(token).name == "run_hite_container.py"]
    if len(indices) != 1 or cmd.count("--image") != 1 or cmd.count("--bind") != 1 or cmd[-1] != "--":
        raise WorkflowError("Expected the audited HiTE container wrapper command; refusing an ambiguous rewrite")
    wrapper = repo / "scripts/run_hite_container.py"
    if not wrapper.is_file() or not (repo / "src/teflow/upstream_probe.py").is_file():
        raise WorkflowError("New repository is incomplete")
    cmd[indices[0]] = str(wrapper)
    cmd[cmd.index("--image") + 1] = str(source)
    hite.update(command=cmd, probe_command=cmd + ["--teflow-probe"], image=str(source),
                expected_version=identity["reported_version"], image_identity=identity)
    c["description"] = (str(c.get("description", "")) + " | HiTE recheck from " + old["run_id"] +
                        "; Zenodo image release 3.3.3, CLI 3.3.2; see image_identity. Old run preserved.").strip(" |")
    write_json(output, c)
    load_config(output)
    return dict(config=str(output), run_id=run_id, old_config_preserved=str(config),
                image_identity=identity, computation_launched=False,
                next="Set TEFLOW_REPOSITORY/PYTHONPATH to this repository; run doctor --dependencies before freeze")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for key in ("config", "output", "run-id"):
        p.add_argument("--" + key, required=True)
    p.add_argument("--image")
    args = p.parse_args()
    try:
        result = prepare(args.config, args.output, args.run_id, args.image)
        print(json.dumps(result, indent=2))
    except (OSError, WorkflowError, json.JSONDecodeError) as e:
        p.exit(2, "HiTE recheck stopped: " + str(e) + "\n")


if __name__ == "__main__":
    main()
