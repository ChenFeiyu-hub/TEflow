"""Offline TE-Aid protein database preflight; no implicit downloads."""
from pathlib import Path
import json
import shutil
import tempfile
import re
from .common import WorkflowError, sha256
from .runtime import run
from .environments import environment_command


def database_prefix(c):
    argv = c["tools"]["tetrimmer"]["command"]
    if "-p" not in argv:
        raise WorkflowError("TE-Aid check requires the documented micromamba environment prefix")
    env = Path(argv[argv.index("-p") + 1])
    return env / "share/teflow-vendor/TEtrimmer-1.7.2/tetrimmer/TE-Aid-master/db/RepeatPeps.lib"


def database_files(prefix):
    paths = [Path(str(prefix) + ext) for ext in ("", ".phr", ".pin", ".psq")]
    if any(not p.is_file() or not p.stat().st_size for p in paths):
        raise WorkflowError("TE-Aid RepeatPeps protein library/index missing or empty: " + str(prefix))
    return sorted(p for p in prefix.parent.glob(prefix.name + "*") if p.is_file())


def first_protein(path):
    pieces = []
    with Path(path).open(encoding="ascii") as f:
        for line in f:
            if line.startswith(">"):
                if pieces:
                    break
            elif line.strip():
                pieces.append(line.strip())
    seq = "".join(pieces).upper().rstrip("*")
    if len(seq) < 20 or not re.fullmatch(r"[A-Z*]+", seq):
        raise WorkflowError("Invalid RepeatPeps protein FASTA: " + str(path))
    return seq[:500]


def probe_teaid(c, output, prefix=None):
    prefix = Path(prefix) if prefix is not None else database_prefix(c)
    assets = database_files(prefix)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    argv = environment_command(c, "tetrimmer")
    run(argv + ["blastdbcmd", "-db", str(prefix), "-dbtype", "prot", "-info"],
        output, output / "database_info.log", 120)
    query = output / "protein_probe.fa"
    query.write_text(">teflowProteinProbe\n" + first_protein(prefix) + "\n", encoding="ascii")
    hits = run(argv + ["blastp", "-query", str(query.resolve()), "-db", str(prefix),
                      "-num_threads", "1", "-seg", "no", "-outfmt", "6"],
               output, output / "protein_search.log", 120)
    if not any(line.startswith("teflowProteinProbe\t") for line in hits.splitlines()):
        raise WorkflowError("TE-Aid protein database opens but self-sequence BLAST probe has no hit")
    return dict(status="pass", database=str(prefix), files={str(p): sha256(p) for p in assets},
                scope="Local protein DB opens and matches a library protein; no TE accuracy claim")


def installed_repeatpeps(c):
    """Prefer the same RepeatMasker installation used by TEtrimmer. Never download master."""
    for provider in ("tetrimmer", "repeatmasker", "edta"):
        argv = c["tools"][provider]["command"]
        env = Path(argv[argv.index("-p") + 1])
        for meta in sorted((env / "conda-meta").glob("repeatmasker-*.json")):
            record = json.loads(meta.read_text())
            if record.get("name") != "repeatmasker":
                continue
            for rel in record.get("files", []):
                p = env / rel
                if p.name == "RepeatPeps.lib" and p.is_file() and p.stat().st_size:
                    first_protein(p)
                    return p.resolve()
    raise WorkflowError("No installed RepeatMasker RepeatPeps.lib found; supply --repeatpeps with a verified local protein library")


def prepare_database(c, source, logdir):
    """Build and smoke-test in staging, preserve previous DB, then publish. No tool source edits."""
    source, logdir = Path(source).resolve(), Path(logdir).resolve()
    first_protein(source)
    target = database_prefix(c)
    parent = target.parent.parent.resolve()
    if not (parent / "TE-Aid").is_file():
        raise WorkflowError("Expected pinned TE-Aid installation missing: " + str(parent))
    if target.parent.is_symlink():
        raise WorkflowError("Refusing to replace a symlinked TE-Aid DB directory")
    envargv = environment_command(c, "tetrimmer")
    env = Path(envargv[envargv.index("-p") + 1])
    lock = json.loads((env / "share/teflow-vendor/sources.lock.json").read_text())
    if any(Path(rel).name.startswith("RepeatPeps.lib") for rel in lock.get("files", {})):
        raise WorkflowError("RepeatPeps is part of frozen upstream source; inspect before replacing")
    logdir.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="db.teflow-staging-", dir=parent))
    if target.parent.exists():
        shutil.copytree(target.parent, staging, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("RepeatPeps.lib*"))
    staged = staging / "RepeatPeps.lib"
    shutil.copyfile(source, staged)
    run(envargv + ["makeblastdb", "-in", str(staged), "-out", str(staged),
                   "-dbtype", "prot", "-blastdb_version", "4"], logdir, logdir / "makeblastdb.log", 600)
    probe_teaid(c, logdir / "staged_probe", staged)
    previous = None
    if target.parent.exists():
        previous = parent / ("db.before-" + staging.name)
        target.parent.rename(previous)
    staging.rename(target.parent)
    result = probe_teaid(c, logdir / "published_probe")
    result.update(source=str(source), source_sha256=sha256(source),
                  previous_database=str(previous) if previous else None)
    from .common import write_json
    write_json(logdir / "teaid_database_install.json", result)
    return result
