"""Finite synthetic subprocesses for runtime acceptance; never executes TE tools."""
from __future__ import annotations

import argparse
import json
import mmap
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import time
import traceback

from .systemd import CGROOT, code_digest, load, now, process_identity, read, sample_group, save, call
from .limits import address_limit
from .login import login_state

MIB = 1024**2


def guard(handle):
    if handle["source_digest"] != code_digest():
        raise RuntimeError("Acceptance source changed after the attempt was prepared")
    paths = [v[3:] for v in Path("/proc/self/cgroup").read_text().splitlines() if v.startswith("0::")]
    if len(paths) != 1 or ".." in Path(paths[0]).parts or Path(paths[0]).name != handle["unit"]:
        raise RuntimeError("Payload is outside the uniquely named attempt cgroup")
    group = CGROOT / paths[0].lstrip("/")
    values = sample_group(group, handle["unit"])
    r = handle["resources"]
    if not 64 * MIB <= r["memory_bytes"] <= 256 * MIB or r["swap_bytes"] != 0:
        raise RuntimeError("Acceptance payload exceeds its fixed safety envelope")
    if values["memory.max"] != str(r["memory_bytes"]) or values["memory.swap.max"] != "0":
        raise RuntimeError("Actual memory/swap limits differ; workload not started")
    if sorted(os.sched_getaffinity(0)) != sorted(r["cpu_ids"]):
        raise RuntimeError("CPU affinity differs; workload not started")
    expected_group = "1" if handle["oom_policy"] == "kill" else "0"
    if values["memory.oom.group"] != expected_group:
        raise RuntimeError("OOM group policy differs; workload not started")
    return group, values


def session_count():
    return login_state()["session_count"]


def process_memory():
    fields = dict(row.split(":", 1) for row in (read("/proc/self/status") or "").splitlines() if ":" in row)
    data = {name: int(fields[name].split()[0]) * 1024 if name in fields else None
            for name in ("VmSize", "VmPeak", "VmRSS", "VmData")}
    data["rlimit_as"] = list(resource.getrlimit(resource.RLIMIT_AS))
    return data


def heartbeat(handle, group, duration):
    output = Path(handle["directory"])
    identity = process_identity()
    start = time.monotonic()
    with (output / "heartbeat.jsonl").open("x", encoding="utf-8", buffering=1) as stream:
        while time.monotonic() - start < duration:
            row = dict(identity, at=now(), monotonic_seconds=time.monotonic(), session_count=session_count(),
                       memory_current=read(group / "memory.current"))
            stream.write(json.dumps(row) + "\n")
            stream.flush()
            time.sleep(5)
    save(output / "worker_complete.json", dict(status="complete", finished_utc=now(), identity=identity,
                                               reason="bounded_heartbeat_duration_elapsed"))
    return 0


def child(handle, case, hold):
    group, before = guard(handle)
    output = Path(handle["directory"])
    reserved = None
    if case.endswith("_vmem"):
        # Test-only inaccessible virtual reservation. It is never touched and adds
        # no 384 MiB resident allocation; the checked 128 MiB cgroup still applies.
        reserved = mmap.mmap(-1, 384 * MIB, flags=mmap.MAP_PRIVATE | mmap.MAP_ANONYMOUS, prot=0)
        case = case.removesuffix("_vmem")
    memory = process_memory()
    save(output / "child_memory_before.json", dict(memory, reserved_virtual_bytes=384 * MIB if reserved else 0))
    count = 48 if case in ("child_oom", "group_oom") else (8 if case in ("success", "reattach") else 0)
    # RLIMIT_AS includes already mapped libraries/arenas, unlike cgroup resident
    # memory. Budget finite additional space and preserve any stricter inherited limit.
    soft, hard = resource.getrlimit(resource.RLIMIT_AS)
    limit = address_limit(memory["VmSize"], soft, hard, required_extra=(count * 4 + 32) * MIB)
    resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    if case in ("child_oom", "group_oom"):
        Path("/proc/self/oom_score_adj").write_text("1000")  # Own child only; prefer it as the OOM victim.
    save(output / "child_ready.json", dict(identity=process_identity(), cgroup=str(group), before=before,
                                           affinity=sorted(os.sched_getaffinity(0)), memory=process_memory(),
                                           address_allowance_bytes=256 * MIB))
    if case == "child_sigkill":
        os.kill(os.getpid(), signal.SIGKILL)
    blocks = []
    try:
        for _ in range(count):
            block = bytearray(4 * MIB)
            for offset in range(0, len(block), 4096):
                block[offset] = 1
            blocks.append(block)
            time.sleep(0.05)
        save(output / "child_allocated.json", dict(bytes=sum(map(len, blocks)), observed=sample_group(group, handle["unit"])))
        time.sleep(hold)
    finally:
        blocks.clear()
        if reserved is not None:
            reserved.close()
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--attempt", required=True)
    p.add_argument("--case", choices=["success", "child_oom", "group_oom", "child_sigkill", "timeout", "cancel", "reattach", "success_vmem", "child_oom_vmem", "logout"], required=True)
    p.add_argument("--child", action="store_true")
    p.add_argument("--duration", type=int, default=600)
    args = p.parse_args(argv)
    handle = load(Path(args.attempt) / "handle.json")
    output = Path(handle["directory"])
    process = None
    try:
        group, before = guard(handle)
        hold = 20 if args.case in ("timeout", "cancel") else (4 if args.case == "reattach" else 0.5)
        if args.child:
            return child(handle, args.case, hold)
        save(output / "worker_ready.json", dict(identity=process_identity(), cgroup=str(group), before=before,
                                                affinity=sorted(os.sched_getaffinity(0)), case=args.case))
        print("PAYLOAD_READY " + args.case, flush=True)
        if args.case == "logout":
            if not 120 <= args.duration <= 1800:
                raise RuntimeError("Logout duration must be 120..1800 seconds")
            return heartbeat(handle, group, args.duration)
        with (output / "child.stdout.log").open("x", encoding="utf-8") as stdout, (output / "child.stderr.log").open("x", encoding="utf-8") as stderr:
            process = subprocess.Popen([sys.executable, "-m", "teflow_runtime.payload", "--attempt", str(output),
                                        "--case", args.case, "--child"], stdout=stdout, stderr=stderr)
            result = process.wait(timeout=25)
        # Deliberately emulate a wrapper returning 0 despite a failed child. The
        # external classifier must still reject the result when OOM/child failure occurred.
        save(output / "worker_complete.json", dict(status="complete", child_returncode=result,
             observed=sample_group(group, handle["unit"]), finished_utc=now(), fixture_parent_returncode=0))
        print("PAYLOAD_FINISHED child_returncode=" + str(result), flush=True)
        return 0
    except Exception as exc:
        name = "child_error.json" if args.child else "worker_error.json"
        save(output / name, dict(status="failed", exception_type=type(exc).__name__, error=str(exc) or repr(exc),
                                traceback=traceback.format_exc(limit=8), memory=process_memory(), at=now()))
        print(type(exc).__name__ + ": " + (str(exc) or repr(exc)), file=sys.stderr, flush=True)
        return 2
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)


if __name__ == "__main__":
    raise SystemExit(main())
