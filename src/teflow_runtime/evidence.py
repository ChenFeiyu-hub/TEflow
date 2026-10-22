"""Pure, portable evidence interpretation; no process control or TE imports."""
from __future__ import annotations


def counters(text):
    if text is None:
        return None
    result = {}
    for line in text.splitlines():
        fields = line.split()
        if len(fields) == 2:
            try:
                result[fields[0]] = int(fields[1])
            except ValueError:
                pass
    return result


def classify(properties, event_samples, worker=None, cancelled=False):
    """OOM evidence outranks a successful parent exit or a later cancellation.

    Samples must belong to one freshly created, identity-verified cgroup. A missing
    event file is unknown, not an observed zero; exit 137 alone never proves OOM.
    """
    event_values = [counters(s.get("memory.events")) for s in event_samples]
    observed = [value for value in event_values if value is not None]
    oom_kills = max((v.get("oom_kill", 0) for v in observed), default=None)
    if properties.get("Result") == "oom-kill" or (oom_kills is not None and oom_kills > 0):
        return "OOM_CONFIRMED"
    if properties.get("Result") == "timeout":
        return "TIMEOUT"
    if cancelled:
        return "CANCELLED"
    if worker and worker.get("child_returncode", 0) < 0:
        return "CHILD_SIGNAL"
    if worker and worker.get("child_returncode", 0) != 0:
        return "TOOL_ERROR"
    if properties.get("Result") not in (None, "", "success") or properties.get("ExecMainStatus") not in (None, "0"):
        return "TOOL_ERROR"
    if worker is None or worker.get("status") != "complete":
        return "OUTPUT_INVALID"
    if properties.get("SubState") != "exited" or properties.get("ExecMainStatus") != "0":
        return "UNKNOWN"
    return "SUCCEEDED"


def logout_evidence(records, minimum_gap=60, max_sampling_gap=15):
    """Require known sessions before, then a continuous, observed zero-session gap.

    Unknown samples break continuity. Host reboot, a new worker or an excessively
    long sampling gap cannot be counted as proof of surviving logout.
    """
    started_logged_in = False
    identity = None
    beginning = previous = None
    longest = 0.0
    for row in records:
        key = (row.get("boot_id"), row.get("pid"), row.get("start_ticks"))
        clock = row.get("monotonic_seconds")
        count = row.get("session_count")
        if None in key or not isinstance(clock, (float, int)):
            beginning = previous = None
            continue
        if identity is None:
            identity = key
        if key != identity:
            return dict(proven=False, reason="worker_identity_changed", longest_zero_session_seconds=longest)
        if previous is not None and (clock <= previous or clock - previous > max_sampling_gap):
            beginning = None
        previous = clock
        if count is None:
            beginning = None
        elif count > 0:
            started_logged_in = True
            beginning = None
        elif count == 0 and started_logged_in:
            if beginning is None:
                beginning = clock
            longest = max(longest, clock - beginning)
    proven = started_logged_in and longest >= minimum_gap
    return dict(proven=proven, reason="observed_zero_session_interval" if proven else "no_sufficient_verified_logout_interval",
                longest_zero_session_seconds=longest, saw_logged_in_session=started_logged_in)
