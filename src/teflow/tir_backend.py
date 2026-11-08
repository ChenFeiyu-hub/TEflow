"""Explicit EDTA TIR backends; old configurations retain their v3 meaning."""
from pathlib import Path
from .common import WorkflowError, read_json
from .assets import asset_path
from .environments import environment_command

BACKENDS = {"v4-cpu": "4.08", "v3": "3.0.7"}
DEFAULT_BACKEND = "v4-cpu"


def selected(c):
    spec = c.get("tools", {}).get("edta", {}).get("tir_learner")
    if spec is None:
        return dict(backend="v3", version=BACKENDS["v3"], selection="legacy_config")
    return dict(spec, selection="explicit_config")


def validate(c, resolve):
    tool = c.get("tools", {}).get("edta", {})
    spec = tool.get("tir_learner")
    if spec is None:
        return
    if (not isinstance(spec, dict) or set(spec) - {"backend", "version", "prefix"}
            or spec.get("backend") not in BACKENDS):
        raise WorkflowError("edta.tir_learner requires backend v4-cpu or v3")
    backend = spec["backend"]
    if spec.get("version") != BACKENDS[backend]:
        raise WorkflowError("Unsupported TIR version for " + backend + "; expected " + BACKENDS[backend])
    if backend == "v3":
        if "prefix" in spec:
            raise WorkflowError("v3 uses the EDTA environment; do not supply a separate TIR prefix")
        return
    if not isinstance(spec.get("prefix"), str) or not spec["prefix"]:
        raise WorkflowError("v4-cpu requires its isolated environment prefix")
    spec["prefix"] = resolve(spec["prefix"])
    argv = tool["command"]
    envcmd = environment_command(c, "edta")
    if argv != envcmd + ["EDTA.pl"] or tool.get("expected_version") != "2.3.0":
        raise WorkflowError("v4-cpu currently supports the pinned micromamba -p EDTA.pl 2.3.0 adapter")
    if Path(envcmd[-1]).resolve() == Path(spec["prefix"]).resolve():
        raise WorkflowError("v4-cpu must be isolated from the EDTA/v3 environment")


def configure(c, backend=DEFAULT_BACKEND, prefix=None, env_root=None):
    if "edta" not in c["tools"]:
        if prefix or backend != DEFAULT_BACKEND:
            raise WorkflowError("A TIR backend requires an enabled EDTA tool")
        return
    if backend not in BACKENDS:
        raise WorkflowError("Unknown TIR backend: " + str(backend))
    if backend == "v3" and prefix:
        raise WorkflowError("--tir-env is only applicable to v4-cpu")
    spec = dict(backend=backend, version=BACKENDS[backend])
    if backend == "v4-cpu":
        if prefix is None:
            parent = Path(env_root) if env_root else Path(environment_command(c, "edta")[-1]).parent
            prefix = parent / "tirlearner4-cpu"
        spec["prefix"] = str(Path(prefix).expanduser().resolve())
    c["tools"]["edta"]["tir_learner"] = spec


def command(c):
    spec = selected(c)
    if spec["backend"] == "v3":
        return c["tools"]["edta"]["command"]
    envcmd = environment_command(c, "edta")
    return envcmd + ["python", "-I", str(asset_path("scripts/run_edta.py")), "launch",
                     "--edta-prefix", envcmd[-1], "--tir-prefix", spec["prefix"],
                     "--micromamba", envcmd[0], "--"]


def probe_command(c):
    spec = selected(c)
    envcmd = environment_command(c, "edta")
    prefix = spec.get("prefix", envcmd[-1])
    return envcmd[:-1] + [prefix, "python", "-I", str(asset_path("scripts/run_edta.py")),
                         "probe", "--backend", spec["backend"], "--prefix", prefix]


def inventory_paths(c):
    """Include the active v4 model/code as well as solved dependency metadata."""
    if selected(c)["backend"] != "v4-cpu":
        return set()
    from .edta_entry import package_records, require_version, model_path
    prefix = Path(selected(c)["prefix"]).resolve()
    records = package_records(prefix)
    require_version(records, "tir-learner", "4.08")
    model = model_path(prefix)
    if not model.is_file():
        raise WorkflowError("v4 model is missing: " + str(model))
    paths = set(prefix.glob("conda-meta/*.json")) | {model, asset_path("scripts/run_edta.py")}
    for rel in records["tir-learner"].get("files", []):
        path = (prefix / rel).resolve()
        if not path.is_relative_to(prefix):
            raise WorkflowError("TIR package file escapes its environment: " + rel)
        if path.is_file() and path.suffix not in {".pyc", ".pyo"}:
            paths.add(path)
    return paths


def add_options(parser, default=None):
    parser.add_argument("--tir-learner", choices=tuple(BACKENDS), default=default,
                        help="EDTA TIR backend: new projects default to v4-cpu; forks preserve selection unless specified")
    parser.add_argument("--tir-env", help="Existing isolated v4 CPU environment; default ENV_ROOT/tirlearner4-cpu")
