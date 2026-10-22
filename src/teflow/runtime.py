"""Small, auditable process runner. No shell interpolation or automatic cleanup."""
from __future__ import annotations
import os
import platform
import importlib.metadata
import shutil
import signal
import subprocess
import sys
import time
import threading
from pathlib import Path
from .common import (WorkflowError, now, sha256, digest, write_json, read_json,
                     source_fingerprint)

PFAM_FILES = ("Pfam-A.hmm", "Pfam-A.hmm.dat", "Pfam-A.hmm.h3f", "Pfam-A.hmm.h3i",
              "Pfam-A.hmm.h3m", "Pfam-A.hmm.h3p")


def process_identity(pid):
    record = dict(pid=pid, host=platform.node())
    if sys.platform.startswith("linux"):
        try:
            record["boot_id"] = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
            record["start_ticks"] = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
        except OSError:
            pass
    return record


def group_alive(record):
    """Read-only orphan detection. Never kill a PID inherited from a stale receipt."""
    if record.get("host") != platform.node():
        raise WorkflowError("Running receipt belongs to another host; explicit process review required")
    if sys.platform.startswith("linux"):
        if not record.get("boot_id") or not record.get("pgid"):
            raise WorkflowError("Cannot verify a process group without boot/PGID identity")
        if record.get("boot_id") != Path("/proc/sys/kernel/random/boot_id").read_text().strip():
            return False
        for p in Path("/proc").glob("[0-9]*/stat"):
            try:
                v = p.read_text().rsplit(")", 1)[1].split()
                if v[0] != "Z" and int(v[2]) == record.get("pgid"):
                    return True
            except (OSError, ValueError, IndexError):
                continue
        return False
    raise WorkflowError("Cannot verify stale process identity on this platform")


def run(argv, cwd, log, timeout=None, allowed=(0,), cpu_limit=None):
    """Record execution, constrain Linux CPU affinity and clean process groups on signals."""
    argv = [str(x) for x in argv]
    cwd, log = Path(cwd), Path(log)
    cwd.mkdir(parents=True, exist_ok=True)
    log.parent.mkdir(parents=True, exist_ok=True)
    receipt = dict(argv=argv, cwd=str(cwd), started=now(), status="running",
                   timeout_seconds=timeout)
    rp = str(log) + ".command.json"
    write_json(rp, receipt)
    env = dict(os.environ, OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    from .resource_pool import CURRENT
    lease = CURRENT.get()
    if lease:
        env.update(TMPDIR=str(lease.attempt/'tmp'), TEFLOW_LEASE_ID=lease.token)
    p, handlers, interrupted = None, {}, None
    cpus = lease.cpus if lease else sorted(os.sched_getaffinity(0))[:cpu_limit] if cpu_limit and hasattr(os, "sched_getaffinity") else None
    receipt["cpu_affinity"] = cpus
    def handle_signal(signum, _frame):
        nonlocal interrupted
        interrupted = signum
        raise WorkflowError(f"Command interrupted by signal {signum}; inspect {log}")
    def cleanup():
        if p is None:
            return
        if os.name == "nt":
            if p.poll() is None:
                p.kill()
        else:
            try:
                os.killpg(p.pid, signal.SIGTERM)
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    p.poll()
                    if not group_alive(receipt):
                        break
                    time.sleep(0.05)
                os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        p.wait()
    try:
        from .control import check_cancelled
        check_cancelled()
        if threading.current_thread() is threading.main_thread():
            for sig in (signal.SIGINT, signal.SIGTERM, getattr(signal, "SIGHUP", signal.SIGTERM)):
                if sig not in handlers:
                    handlers[sig] = signal.signal(sig, handle_signal)
        with log.open("w", encoding="utf-8", newline="\n") as out:
            if lease: lease.before_spawn()
            p = subprocess.Popen(argv, cwd=cwd, stdout=out, stderr=subprocess.STDOUT,
                                 env=env, start_new_session=os.name != "nt",
                                 preexec_fn=(lambda: os.sched_setaffinity(0, cpus)) if cpus and not lease else None)
            receipt.update(process_identity(p.pid), pgid=p.pid if os.name != "nt" else None)
            write_json(rp, receipt)
            if lease: lease.register(receipt)
            deadline = time.monotonic()+timeout if timeout is not None else None
            while True:
                check_cancelled()
                if deadline is not None and time.monotonic() >= deadline:
                    raise WorkflowError(f"Command interrupted/timed out; inspect {log}")
                try:
                    code = p.wait(timeout=min(0.25, max(0.001, deadline-time.monotonic())) if deadline else 0.25)
                    break
                except subprocess.TimeoutExpired:
                    continue
        receipt["returncode"] = code
        if code not in allowed:
            raise WorkflowError(f"Command exited {code}; inspect {log}")
        if sys.platform.startswith("linux") and group_alive(receipt):
            raise WorkflowError(f"Command returned with live descendants; inspect {log}")
        receipt["status"] = "complete"
        return log.read_text(encoding="utf-8", errors="replace")
    except BaseException as e:
        if lease and p is None: lease.spawn_failed()
        for sig in handlers:
            signal.signal(sig, signal.SIG_IGN)
        cleanup()
        receipt.update(status="interrupted" if interrupted else "failed", error=str(e), signal=interrupted)
        raise
    finally:
        for sig, handler in handlers.items():
            signal.signal(sig, handler)
        receipt["finished"] = now()
        write_json(rp, receipt)


def database_inventory(c):
    from .branches import required_tools
    active = required_tools(c)
    db = c.get("databases", {})
    files = db.get("files", [])
    if c["execution"]["mode"] == "server" and not c.get("fixture_only") and not files and active & {"edta", "tetrimmer", "hmmscan"}:
        raise WorkflowError("Freeze database assets with teflow lock-databases before production")
    out = []
    for r in files:
        p = Path(r["path"])
        if not p.is_file() or not p.stat().st_size:
            raise WorkflowError("Missing/empty database asset: " + str(p))
        h = sha256(p)
        if r.get("sha256") != h:
            raise WorkflowError("Database changed or lacks a SHA256 lock: " + str(p))
        out.append(dict(path=str(p), sha256=h, bytes=p.stat().st_size))
    if c["execution"]["mode"] == "server" and not c.get("fixture_only"):
        from .branches import required_tools
        active = required_tools(c)
        pfam = Path(db.get("pfam_dir", "__missing__"))
        locked = {r["path"] for r in out}
        for name in PFAM_FILES if "tetrimmer" in active or "hmmscan" in active else ():
            if str(pfam / name) not in locked:
                raise WorkflowError("Required Pfam file is not locked: " + str(pfam / name))
        from .teaid import database_prefix, database_files
        for asset in database_files(database_prefix(c)) if "tetrimmer" in active else ():
            if str(asset) not in locked:
                raise WorkflowError("TE-Aid protein database asset is not locked: " + str(asset))
        if active & {"edta", "tetrimmer"} and not any(r.get("role") == "repeat_classification" for r in files):
            raise WorkflowError("Lock the actual RepeatMasker/RepeatModeler classification database files")
    return out


def config_fingerprint(c):
    return digest({k: v for k, v in c.items() if not k.startswith("_")})


def software_inventory(c):
    """Lock requested executables and package build metadata, without reading entire environments."""
    paths = set()
    from .branches import required_tools
    for name in required_tools(c):
        tool = c["tools"][name]
        cmd = tool["command"]
        executable = shutil.which(cmd[0])
        if executable:
            paths.add(Path(executable).resolve())
        for token in cmd:
            if Path(token).is_file():
                paths.add(Path(token).resolve())
        if "-p" in cmd:
            prefix = Path(cmd[cmd.index("-p")+1])
            paths.update(prefix.glob("conda-meta/*.json"))
            if name.startswith("heliano"):
                records = [read_json(p) for p in prefix.glob("conda-meta/heliano-*.json")]
                if not records and not c.get("fixture_only"):
                    raise WorkflowError("HELIANO requires package file inventory or a configured source installation")
                for record in records:
                    for rel in record.get("files", []):
                        p = (prefix / rel).resolve()
                        if p.is_file() and p.suffix not in {".pyc", ".pyo"}:
                            paths.add(p)
            vendor = prefix / "share" / "teflow-vendor"
            if vendor.exists():
                lock = vendor / "sources.lock.json"
                if not lock.is_file():
                    raise WorkflowError("Incomplete upstream source installation: " + str(vendor))
                record = read_json(lock)
                if record.get("status") != "verified_cli" or not record.get("files"):
                    raise WorkflowError("Unverified upstream source installation: " + str(vendor))
                paths.add(lock)
                for rel, expected in record["files"].items():
                    p = (prefix / rel).resolve()
                    if not p.is_relative_to(prefix.resolve()) or not p.is_file() or sha256(p) != expected:
                        raise WorkflowError("Upstream source changed/missing: " + str(p))
                    paths.add(p)
            binary = prefix / "bin" / cmd[-1]
            if binary.is_file():
                paths.add(binary.resolve())
        if tool.get("image"):
            paths.add(Path(tool["image"]))
        if tool.get("source_root"):
            root = Path(tool["source_root"])
            if not root.is_dir():
                raise WorkflowError("Missing upstream source root: " + str(root))
            paths.update(p for p in root.rglob("*") if p.is_file() and ".git" not in p.parts and "__pycache__" not in p.parts and p.suffix not in {".pyc", ".pyo"})
    return {str(p): sha256(p) for p in sorted(paths)}


def freeze(c):
    inputs = {s["id"]: {k: sha256(s[k]) for k in ("genome", "annotation", "cds", "reference_library", "reference_te", "promoters_bed") if s.get(k)} for s in c["samples"]}
    inputs["_qc"] = {k: sha256(v) for k, v in c.get("qc", {}).items() if k in ("host_proteins", "te_proteins") and v and v != "derived"}
    try:
        snakemake_version = importlib.metadata.version("snakemake")
    except importlib.metadata.PackageNotFoundError:
        snakemake_version = None
    material = dict(config_sha256=config_fingerprint(c), source_sha256=source_fingerprint(),
                    inputs=inputs, databases=database_inventory(c), software=software_inventory(c),
                    engine=dict(python=sys.version, snakemake=snakemake_version))
    path = Path(c["work_root"]) / c["run_id"] / "run_manifest.json"
    if path.exists():
        old = read_json(path)
        if old["fingerprint"] != digest(material):
            raise WorkflowError("Inputs/config/source/database changed: choose a NEW run_id; existing run preserved")
        # Snakemake might otherwise skip an existing but manually edited artifact.
        for receipt in path.parent.glob("*/*/complete.json"):
            for output, expected in read_json(receipt)["outputs"].items():
                if not Path(output).is_file() or sha256(output) != expected:
                    raise WorkflowError("Completed output changed: " + output)
        return old
    result = dict(fingerprint=digest(material), material=material, config=c,
                  created=now(), platform=platform.platform(),
                  validation_mode="fixture_only" if c.get("fixture_only") else "production_pending",
                  limitations="Installation and workflow completion do not validate biological accuracy")
    write_json(path, result)
    return result


def check_frozen(c):
    p = Path(c["work_root"]) / c["run_id"] / "run_manifest.json"
    if not p.is_file():
        raise WorkflowError("Run teflow freeze before starting production stages")
    m = read_json(p)
    if m["material"]["config_sha256"] != config_fingerprint(c) or m["material"]["source_sha256"] != source_fingerprint():
        raise WorkflowError("Frozen configuration/source changed; use a new run_id")
    return p


def stage_cache(folder, key, inputs, resume=False):
    """Return a verified cache hit, otherwise initialize an exclusive stage lock."""
    folder = Path(folder)
    material = dict(key=key, inputs={str(p): sha256(p) for p in inputs}, source=source_fingerprint())
    fingerprint = digest(material)
    if (folder / "complete.json").exists():
        old = read_json(folder / "complete.json")
        if old["fingerprint"] != fingerprint or not all(Path(p).is_file() and sha256(p) == h for p, h in old["outputs"].items()):
            raise WorkflowError("Completed stage content changed; preserve it and choose a new run_id: " + str(folder))
        return old, None
    if (folder / "request.json").exists():
        if read_json(folder / "request.json")["fingerprint"] != fingerprint:
            raise WorkflowError("Cannot resume stage after changing inputs or parameters")
        if not resume:
            raise WorkflowError("Interrupted/failed stage exists; inspect it, then use --resume: " + str(folder))
        for p in folder.rglob("*.command.json"):
            rec = read_json(p)
            if rec.get("status") == "running" and (not rec.get("pid") or group_alive(rec)):
                raise WorkflowError("Unresolved running/orphan process receipt: " + str(p))
    elif folder.exists() and any(folder.iterdir()):
        raise WorkflowError("Unmanaged nonempty stage directory: " + str(folder))
    folder.mkdir(parents=True, exist_ok=True)
    lock = folder / ".lock"
    try:
        lock.mkdir()
    except FileExistsError as e:
        raise WorkflowError("Stage lock exists; check for a running process before removing a stale lock: " + str(lock)) from e
    write_json(lock / "owner.json", dict(process_identity(os.getpid()), started=now()))
    request = dict(fingerprint=fingerprint, material=material, started=now())
    write_json(folder / "request.json", request)
    return None, request


def finish_stage(folder, request, outputs, details):
    from .resource_pool import CURRENT
    lease = CURRENT.get()
    if lease: lease.check_quiescent()
    from .common import file_stamp
    outputs = list(outputs)
    result = dict(request, finished=now(), status="complete", details=details,
                  output_stats={str(Path(p).resolve()):file_stamp(p) for p in outputs},
                  outputs={str(Path(p).resolve()): sha256(p) for p in outputs})
    write_json(Path(folder) / "complete.json", result)
    return result


def release_lock(folder):
    lock = Path(folder) / ".lock"
    if lock.is_dir():
        (lock / "owner.json").unlink(missing_ok=True)
        lock.rmdir()


def stage_copy(source, target):
    """Independent inode: Linux reflink when supported, otherwise copy. Never hard-link."""
    import errno
    import tempfile
    from .common import file_stamp
    source, target = Path(source), Path(target)
    if target.exists():
        if sha256(source) != sha256(target):
            raise WorkflowError("Staged input changed: " + str(target))
    else:
        target.parent.mkdir(parents=True,exist_ok=True)
        before = file_stamp(source)
        fd, temp = tempfile.mkstemp(prefix='.staging-',dir=target.parent)
        os.close(fd)
        try:
            cloned = False
            if sys.platform.startswith('linux'):
                import fcntl
                try:
                    with source.open('rb') as src, open(temp,'wb') as dest:
                        fcntl.ioctl(dest.fileno(),0x40049409,src.fileno())  # Linux FICLONE
                    cloned = True
                except OSError as e:
                    if e.errno not in (errno.EXDEV,errno.EOPNOTSUPP,errno.ENOTTY,errno.EINVAL,errno.ENOSYS): raise
            if not cloned: shutil.copyfile(source,temp)
            if file_stamp(source) != before:
                raise WorkflowError('Source changed during staging: '+str(source))
            if target.exists(): raise WorkflowError('Staging target appeared concurrently: '+str(target))
            os.replace(temp,target)
        finally:
            Path(temp).unlink(missing_ok=True)


def rm_parallel_jobs(cores):
    if cores < 4:
        raise WorkflowError("RMBlast RepeatMasker requires a budget of at least 4 cores per job")
    return cores // 4
