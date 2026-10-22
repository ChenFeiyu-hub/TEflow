"""EXPERIMENTAL runtime acceptance; not the production TEflow execution backend."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
import uuid

from .evidence import classify, counters, logout_evidence
from .login import login_state
from .systemd import (CGROOT, Resources, call, feedback, identity_matches, info, load, new_attempt,
                      now, read, sample_group, save, still_alive, stop_owned, submit)

MIB = 1024**2
CASES = {"success": "SUCCEEDED", "child_oom": "OOM_CONFIRMED", "group_oom": "OOM_CONFIRMED",
         "child_sigkill": "CHILD_SIGNAL", "timeout": "TIMEOUT", "cancel": "CANCELLED", "reattach": "SUCCEEDED",
         "success_vmem": "SUCCEEDED", "child_oom_vmem": "OOM_CONFIRMED"}


def preflight():
    if sys.platform != "linux" or not hasattr(os, "sched_getaffinity"):
        raise RuntimeError("Execution requires Linux, cgroup v2, and an accessible systemd user manager")
    if not (CGROOT / "cgroup.controllers").is_file():
        raise RuntimeError("A cgroup v2 mount is required")
    result = call(["systemctl", "--user", "show-environment"])
    # Do not store manager environment: it may contain unrelated secrets.
    if result["returncode"] != 0:
        raise RuntimeError("systemd user manager is unavailable; no workload launched")
    available = read("/proc/meminfo")
    memory_kib = next((int(line.split()[1]) for line in (available or "").splitlines()
                       if line.startswith("MemAvailable:")), None)
    if memory_kib is None or memory_kib < 1024**2:
        raise RuntimeError("At least 1 GiB reported MemAvailable is required for this bounded acceptance")
    return dict(platform=sys.platform, python=sys.version.split()[0], uid=os.getuid(),
                cpu_ids=sorted(os.sched_getaffinity(0)), mem_available_kib=memory_kib,
                systemd=call(["systemctl", "--version"]), at=now())


def optional_json(path):
    return load(path) if Path(path).is_file() else None


def verified_state(handle):
    state = info(handle)
    if state["properties"].get("LoadState") != "not-found" and not identity_matches(handle, state["properties"]):
        raise RuntimeError("Service identity changed or is unavailable; refusing to adopt another service")
    return state


def samples_for(handle, state):
    group = state["properties"].get("ControlGroup")
    if not group:
        ready = optional_json(Path(handle["directory"]) / "worker_ready.json")
        group = ready.get("cgroup") if ready else None
        return sample_group(group, handle["unit"]) if group else None
    return sample_group(CGROOT / group.lstrip("/"), handle["unit"])


def collect_events(output, samples):
    events = list(samples)
    for name, key in (("worker_ready.json", "before"), ("child_ready.json", "before"),
                      ("worker_complete.json", "observed"), ("child_allocated.json", "observed")):
        value = optional_json(output / name)
        if value and value.get(key):
            events.append(value[key])
    return events


def cleanup(handle):
    result = stop_owned(handle)
    output = Path(handle["directory"])
    living = []
    for name in ("worker_ready.json", "child_ready.json"):
        record = optional_json(output / name)
        if record and still_alive(record["identity"]):
            living.append(record["identity"])
    result["surviving_recorded_processes"] = living
    result["confirmed"] = result["confirmed"] and not living
    save(output / "cleanup.json", result, replace=True)
    return result


def reattach(attempt):
    handle = load(Path(attempt) / "handle.json")
    state = verified_state(handle)
    props = state["properties"]
    ready = optional_json(Path(attempt) / "worker_ready.json")
    if not (ready and still_alive(ready["identity"]) and props.get("SubState") == "running"
            and props.get("MainPID") == str(ready["identity"]["pid"])):
        raise RuntimeError("Reattach requires the original live worker")
    return dict(status="REATTACHED", observer_pid=os.getpid(), worker=ready["identity"],
                unit=handle["unit"], invocation_id=props["InvocationID"], at=now())


def run_case(root, case, cpu):
    resources = Resources((cpu,), 128 * MIB, 3 if case == "timeout" else 20)
    handle = new_attempt(root, case, resources)
    output = Path(handle["directory"])
    observations = []
    state = {"properties": {}}
    cancelled = False
    reconnect = None
    identity_refusal = None
    problem = None
    cleaned = None
    try:
        state = submit(handle, [sys.executable, "-m", "teflow_runtime.payload", "--attempt", str(output), "--case", case],
                       oom_policy="continue" if case in ("child_oom", "child_oom_vmem", "child_sigkill") else "kill")
        deadline = time.monotonic() + 40
        with (output / "samples.jsonl").open("x", encoding="utf-8", buffering=1) as stream:
            while True:
                state = verified_state(handle)
                sample = samples_for(handle, state)
                if sample:
                    observations.append(sample)
                stream.write(json.dumps(dict(at=now(), properties=state["properties"], metrics=sample)) + "\n")
                ready = (output / "child_ready.json").is_file()
                if ready and case == "cancel" and state["properties"].get("SubState") == "running":
                    cancelled = True
                    break
                if ready and case == "reattach" and reconnect is None:
                    # A new interpreter reads only the persisted handle; it never submits again.
                    reconnect = call([sys.executable, "-m", "teflow_runtime.acceptance", "_reattach", "--attempt", str(output)],
                                     extra_env={"PYTHONPATH": str(Path(__file__).resolve().parent.parent)})
                    save(output / "reattach.json", reconnect)
                    forged = dict(handle, invocation_id="f" * 32 if handle["invocation_id"] != "f" * 32 else "e" * 32)
                    identity_refusal = stop_owned(forged)
                    save(output / "wrong_identity_refusal.json", identity_refusal)
                    try:
                        submit(handle, ["false"])
                    except RuntimeError as exc:
                        save(output / "duplicate_refusal.json", dict(refused=True, reason=str(exc)))
                    else:
                        raise RuntimeError("Duplicate submit was not rejected")
                if state["properties"].get("SubState") in ("exited", "failed", "dead") or state["properties"].get("LoadState") == "not-found":
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError("External acceptance watchdog elapsed")
                time.sleep(0.1)
        save(output / "final_state_before_cleanup.json", state)
    except Exception as exc:
        problem = str(exc)
    finally:
        try:
            cleaned = cleanup(handle)
        except Exception as exc:
            cleaned = dict(confirmed=False, error=str(exc))
            save(output / "cleanup.json", cleaned, replace=True)
    events = collect_events(output, observations)
    receipt = optional_json(output / "worker_complete.json")
    classification = classify(state["properties"], events, receipt, cancelled=cancelled)
    ready = optional_json(output / "worker_ready.json")
    child = optional_json(output / "child_ready.json")
    baseline = counters(ready["before"].get("memory.events")) if ready else None
    checks = dict(expected_classification=classification == CASES[case], cleanup_confirmed=cleaned["confirmed"],
                  guarded_parent=ready is not None, guarded_child=child is not None,
                  fresh_cgroup_events=baseline is not None and baseline.get("oom_kill") == 0,
                  no_controller_error=problem is None)
    if case in ("child_oom", "child_oom_vmem", "child_sigkill"):
        checks["parent_exit_zero"] = state["properties"].get("ExecMainStatus") == "0" and receipt is not None
        checks["child_killed"] = receipt is not None and receipt.get("child_returncode") == -9
    if case == "child_sigkill":
        observed = [counters(v.get("memory.events")) for v in events]
        checks["zero_observed_oom_kills"] = any(v is not None for v in observed) and all(v is None or v.get("oom_kill", 0) == 0 for v in observed)
    if case == "reattach":
        checks["fresh_observer_attached"] = reconnect is not None and reconnect["returncode"] == 0
        checks["wrong_identity_stop_refused"] = identity_refusal is not None and identity_refusal["action"] == "refused_identity_mismatch"
        checks["duplicate_launch_refused"] = (output / "duplicate_refusal.json").is_file()
    if case.endswith("_vmem"):
        memory = optional_json(output / "child_memory_before.json")
        checks["virtual_reservation_observed"] = (memory is not None and memory.get("reserved_virtual_bytes") == 384 * MIB
                                                   and (memory.get("VmSize") or 0) >= 384 * MIB)
    peaks = [int(v["memory.peak"]) for v in events if str(v.get("memory.peak", "")).isdigit()]
    report = dict(case=case, status="pass" if all(checks.values()) else "fail", expected=CASES[case],
                  classification=classification, checks=checks, error=problem, cleanup=cleaned["confirmed"],
                  child_error=optional_json(output / "child_error.json"),
                  worker_error=optional_json(output / "worker_error.json"),
                  memory_peak_bytes=max(peaks) if peaks else None, directory=str(output), at=now())
    save(output / "result.json", report)
    return report


def b2(root):
    output = Path(root).resolve() / "runtime_acceptance" / ("b2." + uuid.uuid4().hex[:12])
    output.mkdir(parents=True, exist_ok=False)
    report = dict(schema_version=1, status="fail", cases=[], scope="Finite synthetic fixtures; no TE analysis or batch scheduler certification", at=now())
    try:
        host = preflight()
        save(output / "host.json", host)
        for case in CASES:
            result = run_case(output, case, host["cpu_ids"][0])
            report["cases"].append(result)
            print(json.dumps({key: result[key] for key in ("case", "status", "classification", "memory_peak_bytes", "child_error", "worker_error")}), flush=True)
            if not result["cleanup"]:
                raise RuntimeError("Cleanup is unconfirmed; no subsequent fixture launched")
        if all(v["status"] == "pass" for v in report["cases"]):
            report["status"] = "B2_ACCEPTANCE_PASSED"
    except Exception as exc:
        report["error"] = str(exc)
    save(output / "summary.json", report)
    archive = feedback(output)
    print(json.dumps(dict(status=report["status"], output=str(output), feedback=archive), ensure_ascii=False, indent=2))
    return 0 if report["status"] == "B2_ACCEPTANCE_PASSED" else 1


def resolve_attempt_file(path):
    path = Path(path).resolve()
    if not path.is_file():
        raise RuntimeError("No successful logout-start receipt at " + str(path) + "; do not log out before startup succeeds")
    locator = load(path)
    if locator.get("kind") != "logout" or locator.get("schema_version") != 1:
        raise RuntimeError("Invalid logout attempt receipt")
    output = Path(locator["attempt"]).resolve()
    handle = load(output / "handle.json")
    if any(not locator.get(key) or locator[key] != handle.get(key) for key in ("attempt_id", "unit", "invocation_id")):
        raise RuntimeError("Logout receipt/handle identity mismatch")
    return str(output)


def logout_start(root, duration, attempt_file=None):
    locator_path = Path(attempt_file).resolve() if attempt_file else None
    if locator_path and locator_path.exists():
        raise RuntimeError("Attempt receipt already exists; inspect it with logout-check --attempt-file or use a new receipt filename")
    host = preflight()
    if not 120 <= duration <= 1800:
        raise ValueError("Duration must be 120..1800 seconds")
    login = login_state()
    if login["status"] != "LOGIN_STATE_READ":
        print(json.dumps(dict(status="LOGIN_STATE_UNAVAILABLE", launched=False, login=login,
                              action="No readable login properties; inspect the query. This does not mean linger is disabled."), indent=2))
        return 2
    if login["linger"] != "yes":
        print(json.dumps(dict(status="NEEDS_LINGER", launched=False, login=login,
                              action="Have the administrator enable linger for this account, then retry. This command changes no login settings."), indent=2))
        return 2
    if not login["session_count"]:
        raise RuntimeError("Start from a registered login session; a zero/unknown starting count cannot prove logout survival")
    handle = new_attempt(Path(root) / "runtime_acceptance", "logout", Resources((host["cpu_ids"][0],), 128 * MIB, duration + 30))
    output = Path(handle["directory"])
    save(output / "host.json", host)
    save(output / "login_before.json", login)
    try:
        submit(handle, [sys.executable, "-m", "teflow_runtime.payload", "--attempt", str(output), "--case", "logout", "--duration", str(duration)])
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if (output / "heartbeat.jsonl").is_file() and (output / "heartbeat.jsonl").stat().st_size:
                break
            if verified_state(handle)["properties"].get("SubState") != "running":
                raise RuntimeError("Heartbeat did not start; inspect worker_error.json/stderr.log")
            time.sleep(0.2)
        rows = heartbeat_rows(output)
        if not rows or not rows[0].get("session_count"):
            raise RuntimeError("No verified initial logged-in heartbeat; logout test not started")
        if locator_path:
            locator_path.parent.mkdir(parents=True, exist_ok=True)
            save(locator_path, dict(schema_version=1, kind="logout", attempt=str(output),
                 attempt_id=handle["attempt_id"], unit=handle["unit"], invocation_id=handle["invocation_id"], created_utc=now()))
    except Exception as exc:
        result = dict(status="LOGOUT_START_FAILED", error=str(exc), cleanup=cleanup(handle))
        save(output / "result.json", result)
        print(json.dumps(dict(result, feedback=feedback(output)), indent=2))
        return 1
    print(json.dumps(dict(status="LOGOUT_HEARTBEAT_STARTED", attempt=str(output), unit=handle["unit"],
                          attempt_file=str(locator_path) if locator_path else None,
                          duration_seconds=duration, instructions="Close all sessions of this account normally; stay logged out for at least 90 seconds; reconnect and run logout-check with this exact attempt path within the duration."), indent=2))
    return 0


def heartbeat_rows(output):
    path = output / "heartbeat.jsonl"
    if not path.is_file():
        return []
    raw = path.read_text(encoding="utf-8")
    # Ignore only a final partial line while the worker is appending.
    lines = raw.splitlines()
    if raw and not raw.endswith("\n"):
        lines = lines[:-1]
    return [json.loads(line) for line in lines if line.strip()]


def logout_check(attempt, cancel=False):
    output = Path(attempt).resolve()
    if not (output / "handle.json").is_file():
        raise RuntimeError("No logout handle exists at this path. Run logout-start successfully first and use its saved attempt file; do not use the example placeholder.")
    handle = load(output / "handle.json")
    state = verified_state(handle)
    login = login_state()
    rows = heartbeat_rows(output)
    evidence = logout_evidence(rows)
    ready = optional_json(output / "worker_ready.json")
    same_live = (ready is not None and still_alive(ready["identity"]) and identity_matches(handle, state["properties"])
                 and state["properties"].get("SubState") == "running")
    proven = bool(evidence["proven"] and same_live and login["session_count"] and login["linger"] == "yes")
    report = dict(status="B3_LOGOUT_SURVIVAL_PASSED" if proven else ("CANCELLED" if cancel else "B3_NOT_PROVEN"),
                  evidence=evidence, same_live_worker=same_live, login_after=login, state=state, at=now(),
                  scope="One bounded user-service heartbeat across an observed zero-session interval; not a days-long TE workload")
    if proven or cancel or not same_live:
        report["cleanup"] = cleanup(handle)
        if not report["cleanup"]["confirmed"]:
            report["status"] = "CLEANUP_UNCONFIRMED"
    report_path = output / ("logout_check." + uuid.uuid4().hex[:8] + ".json")
    save(report_path, report)
    print(json.dumps(dict(status=report["status"], report=str(report_path), feedback=feedback(output),
                          evidence=evidence, action="If not proven and still running, keep this attempt and repeat after a real logout interval; --cancel stops only this owned service."), indent=2))
    return 0 if report["status"] in ("B3_LOGOUT_SURVIVAL_PASSED", "CANCELLED") else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    suite = commands.add_parser("b2", help="Sequential bounded OOM/failure/cleanup/reattach fixtures")
    suite.add_argument("--root", required=True)
    start = commands.add_parser("logout-start", help="Start a bounded heartbeat after checking linger")
    start.add_argument("--root", required=True)
    start.add_argument("--duration", type=int, default=600)
    start.add_argument("--attempt-file", help="Write the successful attempt identity here for use after reconnecting; refuses overwrite")
    check = commands.add_parser("logout-check", help="Check genuine logout evidence and clean up a passed test")
    target = check.add_mutually_exclusive_group(required=True)
    target.add_argument("--attempt")
    target.add_argument("--attempt-file", help="Read the identity receipt written by logout-start")
    check.add_argument("--cancel", action="store_true")
    commands.add_parser("login-status", help="Read login/linger state without launching or modifying anything")
    attach = commands.add_parser("_reattach", help="Internal read-only reattachment probe")
    attach.add_argument("--attempt", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "b2":
            return b2(args.root)
        if args.command == "logout-start":
            return logout_start(args.root, args.duration, args.attempt_file)
        if args.command == "logout-check":
            return logout_check(resolve_attempt_file(args.attempt_file) if args.attempt_file else args.attempt, args.cancel)
        if args.command == "login-status":
            login = login_state(detailed=True)
            print(json.dumps(login, indent=2))
            return 0 if login["status"] == "LOGIN_STATE_READ" else 2
        print(json.dumps(reattach(args.attempt)))
        return 0
    except Exception as exc:
        print(json.dumps(dict(status="ERROR", error=str(exc))), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
