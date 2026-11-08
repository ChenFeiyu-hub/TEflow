"""Run unchanged EDTA with an attempt-local TIR-Learner v4 CPU bridge.

No dependency on experiment harnesses and no edits to either installed tool.
All children stay in the process group managed by TEflow's runtime.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import uuid
from .common import WorkflowError, now, read_json, write_json


def package_records(prefix):
    records = {}
    for path in sorted((Path(prefix) / "conda-meta").glob("*.json")):
        item = read_json(path)
        if item["name"] in records:
            raise WorkflowError("Duplicate package metadata: " + item["name"])
        records[item["name"]] = item
    if not records:
        raise WorkflowError("Missing Conda package metadata: " + str(prefix))
    return records


def require_version(records, name, version):
    normalize = lambda x: tuple(int(t) if t.isdigit() else t for t in str(x).split("."))
    if normalize(records.get(name, {}).get("version")) != normalize(version):
        raise WorkflowError("Expected " + name + "=" + version + "; found " + str(records.get(name, {}).get("version")))


def model_path(prefix):
    return Path(prefix) / "lib/tir-learner4/cnn0912/cnn0912.keras"


def cpu_environment(parent=None):
    env = dict(os.environ if parent is None else parent)
    for key in ("PYTHONPATH", "PYTHONHOME"):
        env.pop(key, None)
    env.update(CUDA_VISIBLE_DEVICES="", KERAS_BACKEND="torch", PYTHONNOUSERSITE="1",
               PYTHONDONTWRITEBYTECODE="1", OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1",
               MKL_NUM_THREADS="1", NUMEXPR_NUM_THREADS="1")
    return env


def find_edta_main(prefix):
    prefix = Path(prefix).resolve()
    records = package_records(prefix)
    require_version(records, "edta", "2.3.0")
    candidates = {prefix / "share/EDTA/EDTA_raw.pl", prefix / "bin/EDTA_raw.pl"}
    candidates.update(prefix / rel for rel in records["edta"].get("files", []) if Path(rel).name == "EDTA_raw.pl")
    found = set()
    for path in candidates:
        source = path.resolve()
        if not source.is_relative_to(prefix) or source.name != "EDTA_raw.pl" or not source.is_file():
            continue
        body = source.read_text(encoding="utf-8")
        main = source.parent / "EDTA.pl"
        if (re.search(r"^#![^\n]*\bperl\b", body) and all(t in body for t in ("convert_seq_name", "TIR-Learner_FinalAnn", "--type"))
                and (source.parent / "bin/rename_tirlearner.pl").is_file() and main.is_file()):
            text = main.read_text(encoding="utf-8")
            if re.search(r"^#![^\n]*\bperl\b", text) and all(t in text for t in ("EDTA_raw.pl", "check_dependencies", "EDTA.TElib.fa")):
                found.add(main.resolve())
    if len(found) != 1:
        raise WorkflowError("Cannot uniquely locate the real EDTA 2.3.0 Perl source and adjacent helpers")
    return found.pop()


def probe(backend, prefix):
    prefix = Path(prefix).resolve()
    if Path(os.environ.get("CONDA_PREFIX", "")).resolve() != prefix:
        raise WorkflowError("TIR probe is not running inside the requested environment")
    records = package_records(prefix)
    version = "4.08" if backend == "v4-cpu" else "3.0.7"
    require_version(records, "tir-learner", version)
    if backend == "v3":
        from .tirlearner_probe import probe as pandas_probe
        result = pandas_probe()
        return dict(result, backend=backend, version=version, prefix=str(prefix))
    os.environ.update(cpu_environment())
    # PYTHONPATH/HOME have already influenced startup; remove their environment
    # values as well so any native children cannot inherit them.
    os.environ.pop("PYTHONPATH", None)
    os.environ.pop("PYTHONHOME", None)
    import numpy as np
    import torch
    import keras
    if torch.version.cuda is not None or torch.cuda.is_available() or keras.backend.backend() != "torch":
        raise WorkflowError("Expected CPU-only PyTorch and the Keras torch backend")
    torch.set_num_threads(1)
    path = model_path(prefix)
    model = keras.models.load_model(path)
    if tuple(model.input_shape[1:]) != (400, 5):
        raise WorkflowError("Unexpected v4 model input dimensions")
    x = np.eye(5, dtype=np.float32)[np.arange(800).reshape(2, 400) % 5]
    y = np.asarray(model.predict(x, verbose=0))
    devices = sorted({str(weight.value.device) for weight in model.weights})
    if y.shape != (2, 6) or not np.isfinite(y).all() or not devices or any(not s.startswith("cpu") for s in devices):
        raise WorkflowError("Invalid v4 inference output or non-CPU model tensors")
    return dict(status="pass", backend=backend, version=version, prefix=str(prefix), model_path=str(path),
                model_input_shape=list(model.input_shape), output_shape=list(y.shape), tensor_devices=devices,
                torch=torch.__version__, keras=keras.__version__, numpy=np.__version__, torch_cuda_build=torch.version.cuda,
                scope="Packaged model CPU inference on artificial inputs; no biological accuracy claim")


def bridge(config, forwarded):
    spec = read_json(config)
    # An absolute executable prevents a failed PATH switch from recursing into
    # this shim or silently running the EDTA environment's v3 executable.
    executable = Path(spec["tir_prefix"]) / "bin/TIR-Learner"
    argv = [spec["micromamba"], "run", "-p", spec["tir_prefix"], str(executable), *forwarded]
    entry = Path(spec["calls"]) / (uuid.uuid4().hex + ".json")
    record = dict(started=now(), argv=argv, forwarded=forwarded, cwd=os.getcwd(),
                  backend="v4-cpu", version="4.08", tir_prefix=spec["tir_prefix"],
                  wrapper_pid=os.getpid(), scoring="unchanged_upstream", status="running")
    write_json(entry, record)
    try:
        code = subprocess.call(argv, env=cpu_environment())
        record.update(status="complete" if code == 0 else "failed", returncode=code, finished=now())
        write_json(entry, record)
        return code if code >= 0 else 128 - code
    except BaseException as exc:
        write_json(entry, dict(record, status="failed", error=type(exc).__name__ + ": " + str(exc), finished=now()))
        raise


def launch(edta_prefix, tir_prefix, micromamba, forwarded):
    edta_prefix, tir_prefix = Path(edta_prefix).resolve(), Path(tir_prefix).resolve()
    if edta_prefix == tir_prefix or Path(os.environ.get("CONDA_PREFIX", "")).resolve() != edta_prefix:
        raise WorkflowError("EDTA must run in its own unchanged environment")
    main = find_edta_main(edta_prefix)
    records = package_records(tir_prefix)
    require_version(records, "tir-learner", "4.08")
    if not (tir_prefix / "bin/TIR-Learner").is_file() or not model_path(tir_prefix).is_file():
        raise WorkflowError("v4 executable/model missing; v3 fallback is explicit, never automatic")
    mamba = shutil.which(micromamba)
    if not mamba:
        raise WorkflowError("micromamba executable not found")
    directory = Path.cwd() / ".teflow-tir" / uuid.uuid4().hex
    directory.mkdir(parents=True)
    config = directory / "bridge.json"
    write_json(config, dict(micromamba=mamba, tir_prefix=str(tir_prefix), calls=str(directory / "calls")))
    shim = directory / "TIR-Learner"
    from .assets import asset_path
    wrapper = asset_path("scripts/run_edta.py")
    shim.write_text("#!/bin/sh\nexec " + " ".join(shlex.quote(str(x)) for x in (sys.executable, wrapper, "bridge", "--config", config)) + ' -- "$@"\n', encoding="utf-8", newline="\n")
    shim.chmod(0o755)
    os.environ["PATH"] = str(directory) + os.pathsep + os.environ["PATH"]
    os.environ.update({k: v for k, v in cpu_environment().items() if k in ("CUDA_VISIBLE_DEVICES", "KERAS_BACKEND", "PYTHONNOUSERSITE", "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")})
    resolved = {name: shutil.which(name) for name in ("perl", "TIR-Learner", "RepeatMasker", "RepeatModeler", "blastn", "TEsorter")}
    if not all(resolved.values()) or Path(resolved["TIR-Learner"]).resolve() != shim.resolve():
        raise WorkflowError("EDTA dependencies or attempt-local TIR entry are not resolved correctly")
    for name in ("perl", "RepeatMasker", "RepeatModeler", "blastn", "TEsorter"):
        if not Path(resolved[name]).resolve().is_relative_to(edta_prefix):
            raise WorkflowError("Unexpected external EDTA dependency: " + name)
    argv = [resolved["perl"], str(main), *forwarded]
    write_json(directory / "launch.json", dict(started=now(), backend="v4-cpu", version="4.08",
               edta_prefix=str(edta_prefix), tir_prefix=str(tir_prefix), resolved_tools=resolved, argv=argv,
               fallback="disabled", production_environment_modified=False))
    os.execv(resolved["perl"], argv)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="action", required=True)
    p = subs.add_parser("launch")
    for key in ("edta-prefix", "tir-prefix", "micromamba"):
        p.add_argument("--" + key, required=True)
    p.add_argument("forwarded", nargs=argparse.REMAINDER)
    p = subs.add_parser("bridge")
    p.add_argument("--config", required=True)
    p.add_argument("forwarded", nargs=argparse.REMAINDER)
    p = subs.add_parser("probe")
    p.add_argument("--backend", choices=("v3", "v4-cpu"), required=True)
    p.add_argument("--prefix", required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == "probe":
            print(json.dumps(probe(args.backend, args.prefix)))
            return 0
        forwarded = args.forwarded[1:] if args.forwarded[:1] == ["--"] else args.forwarded
        if args.action == "bridge":
            return bridge(args.config, forwarded)
        launch(args.edta_prefix, args.tir_prefix, args.micromamba, forwarded)
        return 0
    except (WorkflowError, OSError, ValueError, ImportError) as exc:
        print(json.dumps(dict(status="fail", error=type(exc).__name__ + ": " + str(exc))), file=sys.stderr)
        return 2
