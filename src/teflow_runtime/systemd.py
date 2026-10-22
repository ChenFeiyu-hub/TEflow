"""Small Linux user-service backend used by bounded acceptance experiments.

No TE imports, sudo, unit installation, linger changes, or process-name signals.
Do not treat this experimental interface as the production batch executor yet.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import time
import uuid

PREFIX = "teflow-rt-"
CGROOT = Path("/sys/fs/cgroup")
METRICS = ("memory.current", "memory.peak", "memory.max", "memory.swap.current", "memory.swap.max",
           "memory.events", "memory.oom.group", "memory.stat", "memory.pressure", "cpu.stat",
           "cpu.max", "cpuset.cpus.effective", "pids.current", "pids.max", "io.stat")


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def code_digest():
    h = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        h.update(path.name.encode() + b"\0" + path.read_bytes() + b"\0")
    return h.hexdigest()


def read(path):
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return None


def save(path, obj, replace=False):
    path = Path(path)
    if path.exists() and not replace:
        raise FileExistsError(path)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".partial")
    with temp.open("x", encoding="utf-8", newline="\n") as out:
        json.dump(obj, out, ensure_ascii=False, indent=2)
        out.write("\n")
    os.replace(temp, path)


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def call(argv, timeout=10, extra_env=None):
    try:
        p = subprocess.run([str(v) for v in argv], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout,
                           env=dict(os.environ, SYSTEMD_PAGER="cat", SYSTEMD_COLORS="0", **(extra_env or {})))
        return dict(argv=[str(v) for v in argv], returncode=p.returncode, stdout=p.stdout, stderr=p.stderr)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return dict(argv=[str(v) for v in argv], returncode=None, error=str(exc))


@dataclass(frozen=True)
class Resources:
    cpu_ids: tuple[int, ...]
    memory_bytes: int
    runtime_seconds: int
    swap_bytes: int = 0
    tasks_max: int = 16

    def validate(self):
        if not self.cpu_ids or len(set(self.cpu_ids)) != len(self.cpu_ids) or any(type(c) is not int or c < 0 for c in self.cpu_ids):
            raise ValueError("CPU IDs must be unique nonnegative integers")
        for value in (self.memory_bytes, self.runtime_seconds, self.tasks_max):
            if type(value) is not int or value <= 0:
                raise ValueError("Resource limits must be positive integers")
        if type(self.swap_bytes) is not int or self.swap_bytes < 0:
            raise ValueError("Swap limit must be an explicit nonnegative byte count")
        if hasattr(os, "sched_getaffinity") and not set(self.cpu_ids) <= os.sched_getaffinity(0):
            raise ValueError("Requested CPUs are outside the caller's affinity")


def new_attempt(root, label, resources):
    resources.validate()
    if not re.fullmatch(r"[a-z0-9_-]+", label):
        raise ValueError("Invalid label")
    token = uuid.uuid4().hex
    output = Path(root).resolve() / (label + "." + token[:12])
    output.mkdir(parents=True, exist_ok=False)
    (output / "tmp").mkdir()
    handle = dict(schema_version=1, attempt_id=token, unit=PREFIX + token + ".service",
                  description="TEflow runtime acceptance " + token, directory=str(output),
                  host=os.uname().nodename, boot_id=read("/proc/sys/kernel/random/boot_id"),
                  resources=asdict(resources), created_utc=now(), invocation_id=None,
                  source_digest=code_digest(), status="prepared")
    save(output / "handle.json", handle)
    return handle


def validate_handle(handle):
    token = handle.get("attempt_id", "")
    if not re.fullmatch(r"[0-9a-f]{32}", token) or handle.get("unit") != PREFIX + token + ".service":
        raise ValueError("Invalid attempt/unit identity")
    if handle.get("description") != "TEflow runtime acceptance " + token:
        raise ValueError("Invalid description identity")
    if handle.get("host") != os.uname().nodename or handle.get("boot_id") != read("/proc/sys/kernel/random/boot_id"):
        raise ValueError("Handle belongs to a different host or boot; reconcile without signalling")


def info(handle):
    validate_handle(handle)
    keys = ["Id", "Description", "Transient", "InvocationID", "LoadState", "ActiveState", "SubState",
            "ControlGroup", "Result", "ExecMainCode", "ExecMainStatus", "MemoryMax", "MemorySwapMax", "MainPID"]
    result = call(["systemctl", "--user", "show", handle["unit"], "--no-pager", "--property=" + ",".join(keys)])
    result["properties"] = dict(line.split("=", 1) for line in result.get("stdout", "").splitlines() if "=" in line)
    return result


def identity_matches(handle, properties):
    return (properties.get("Id") == handle.get("unit") and properties.get("Description") == handle.get("description")
            and properties.get("Transient") == "yes" and (not handle.get("invocation_id") or
            properties.get("InvocationID") == handle["invocation_id"]))


def sample_group(path, expected_unit):
    path = Path(path)
    if not path.is_absolute() or path.name != expected_unit or ".." in path.parts:
        raise ValueError("Untrusted cgroup path")
    path.resolve().relative_to(CGROOT.resolve())
    return dict(at=now(), **{name: read(path / name) for name in METRICS})


def submit(handle, argv, oom_policy="kill"):
    validate_handle(handle)
    if handle.get("status") != "prepared":
        raise RuntimeError("Attempt has already been submitted or is uncertain; create a new attempt instead")
    if oom_policy not in ("continue", "kill"):
        raise ValueError("Unsupported acceptance OOM policy")
    output = Path(handle["directory"])
    before = info(handle)
    if before["properties"].get("LoadState") != "not-found":
        raise RuntimeError("Attempt already submitted or backend state unknown; refusing duplicate launch")
    resources = Resources(**dict(handle["resources"], cpu_ids=tuple(handle["resources"]["cpu_ids"])))
    resources.validate()
    handle.update(status="submitting", oom_policy=oom_policy, argv=[str(v) for v in argv])
    save(output / "handle.json", handle, replace=True)
    escaped = lambda p: str(p).replace("%", "%%")
    properties = ["Type=exec", "RemainAfterExit=yes", "MemoryAccounting=yes", f"MemoryMax={resources.memory_bytes}",
                  f"MemorySwapMax={resources.swap_bytes}", "CPUAffinity=" + " ".join(map(str, resources.cpu_ids)),
                  f"TasksMax={resources.tasks_max}", f"RuntimeMaxSec={resources.runtime_seconds}s", "TimeoutStartSec=15s",
                  "TimeoutStopSec=3s", "KillMode=control-group", "Restart=no", "OOMPolicy=" + oom_policy,
                  "WorkingDirectory=" + escaped(output), "StandardOutput=append:" + escaped(output / "stdout.log"),
                  "StandardError=append:" + escaped(output / "stderr.log")]
    source = str(Path(__file__).resolve().parent.parent)
    cmd = ["systemd-run", "--user", "--no-ask-password", "--unit=" + handle["unit"],
           "--description=" + handle["description"], "--setenv=PYTHONPATH=" + source,
           "--setenv=TMPDIR=" + str(output / "tmp"), "--setenv=PYTHONUNBUFFERED=1",
           "--setenv=OMP_NUM_THREADS=1", "--setenv=OPENBLAS_NUM_THREADS=1"]
    cmd.extend("--property=" + item for item in properties)
    cmd.extend(map(str, argv))
    result = call(cmd, timeout=20)
    save(output / "submission.json", result)
    state = info(handle)
    save(output / "submitted_state.json", state)
    if identity_matches(handle, state["properties"]):
        handle["invocation_id"] = state["properties"].get("InvocationID")
        handle["status"] = "submitted"
        save(output / "handle.json", handle, replace=True)
    if result["returncode"] != 0:
        raise RuntimeError("Service submission failed; inspect submission.json and stderr.log")
    if not handle["invocation_id"]:
        raise RuntimeError("Submitted service identity is not verified")
    return state


def stop_owned(handle):
    state = info(handle)
    if state["properties"].get("LoadState") == "not-found":
        return dict(confirmed=True, state=state, action="already_absent")
    if not identity_matches(handle, state["properties"]):
        return dict(confirmed=False, state=state, action="refused_identity_mismatch")
    stopped = call(["systemctl", "--user", "stop", handle["unit"]], timeout=15)
    after = info(handle)
    props = after["properties"]
    terminal = props.get("LoadState") == "not-found" or props.get("ActiveState") in ("failed", "inactive")
    # A surviving worker/child identity is checked separately by the acceptance suite.
    reset = None
    if terminal and props.get("LoadState") != "not-found" and identity_matches(handle, props):
        reset = call(["systemctl", "--user", "reset-failed", handle["unit"]])
    return dict(confirmed=terminal, action="stopped_owned_unit", stop=stopped, state=after, reset=reset)


def process_identity(pid=None):
    pid = os.getpid() if pid is None else pid
    raw = read(f"/proc/{pid}/stat")
    return dict(pid=pid, start_ticks=raw.rsplit(")", 1)[1].split()[19] if raw else None,
                boot_id=read("/proc/sys/kernel/random/boot_id"))


def still_alive(record):
    if record.get("boot_id") != read("/proc/sys/kernel/random/boot_id"):
        return False
    raw = read(f"/proc/{record.get('pid')}/stat")
    if raw is None:
        return False
    fields = raw.rsplit(")", 1)[1].split()
    return fields[0] != "Z" and fields[19] == str(record.get("start_ticks"))


def feedback(directory):
    """Snapshot small runtime evidence; never follow symlinks or include payload data."""
    root = Path(directory).resolve()
    archive = root.with_name(root.name + "." + uuid.uuid4().hex[:8] + ".feedback.tar.gz")
    with tarfile.open(archive, "x:gz") as tar:
        total = 0
        for path in sorted(root.rglob("*")):
            if path.is_symlink() or not path.is_file() or path.suffix not in (".json", ".jsonl", ".log"):
                continue
            path.resolve().relative_to(root)
            size = path.stat().st_size
            if size > 16 * 1024**2 or total + size > 64 * 1024**2:
                raise RuntimeError("Unexpectedly large diagnostic file; refusing unbounded archive")
            data = path.read_bytes()
            total += len(data)
            entry = tarfile.TarInfo(path.relative_to(root).as_posix())
            entry.size, entry.mode = len(data), 0o600
            tar.addfile(entry, io.BytesIO(data))
    return str(archive)
