"""Failure classification and task-ownership contracts, requiring no Linux service."""
import copy
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from teflow_runtime.evidence import classify, counters, logout_evidence
from teflow_runtime.systemd import Resources, identity_matches, stop_owned, submit, feedback
from teflow_runtime.login import parse_login, login_state
from teflow_runtime.limits import address_limit, MIB
from teflow_runtime.acceptance import logout_start, resolve_attempt_file


class ClassificationTests(unittest.TestCase):
    def setUp(self):
        self.state = dict(Result="success", ExecMainStatus="0", SubState="exited")
        self.worker = dict(status="complete", child_returncode=0)

    def test_child_oom_overrides_successful_wrapper(self):
        self.assertEqual(classify(self.state, [{"memory.events": "oom 1\noom_kill 1\n"}], self.worker), "OOM_CONFIRMED")

    def test_oom_result_survives_missing_cgroup(self):
        self.assertEqual(classify(dict(self.state, Result="oom-kill"), [{"memory.events": None}]), "OOM_CONFIRMED")

    def test_exit_137_is_not_oom_evidence(self):
        self.assertEqual(classify(dict(self.state, ExecMainStatus="137"), [{"memory.events": None}]), "TOOL_ERROR")

    def test_child_signal_rejects_successful_parent(self):
        self.assertEqual(classify(self.state, [{"memory.events": "oom_kill 0"}], dict(self.worker, child_returncode=-9)), "CHILD_SIGNAL")

    def test_child_error_rejects_successful_parent(self):
        self.assertEqual(classify(self.state, [], dict(self.worker, child_returncode=2)), "TOOL_ERROR")

    def test_timeout_and_oom_outrank_later_cancel(self):
        self.assertEqual(classify(dict(self.state, Result="timeout"), [], cancelled=True), "TIMEOUT")
        self.assertEqual(classify(self.state, [{"memory.events": "oom_kill 1"}], cancelled=True), "OOM_CONFIRMED")

    def test_missing_receipt_is_not_success(self):
        self.assertEqual(classify(self.state, [], None), "OUTPUT_INVALID")

    def test_receipt_before_parent_exit_is_not_success(self):
        self.assertEqual(classify(dict(self.state, SubState="running"), [], self.worker), "UNKNOWN")

    def test_missing_metrics_are_unknown(self):
        self.assertIsNone(counters(None))
        self.assertEqual(counters("oom_kill 0"), {"oom_kill": 0})


class LogoutTests(unittest.TestCase):
    @staticmethod
    def records():
        return [dict(pid=123, start_ticks="45", boot_id="same-boot", monotonic_seconds=t,
                     session_count=1 if t == 0 else 0) for t in range(0, 76, 5)]

    def test_verified_zero_session_gap(self):
        result = logout_evidence(self.records())
        self.assertTrue(result["proven"])
        self.assertEqual(result["longest_zero_session_seconds"], 70)

    def test_linger_or_one_closed_terminal_is_insufficient(self):
        rows = self.records()
        for row in rows:
            row["session_count"] = 1
        self.assertFalse(logout_evidence(rows)["proven"])

    def test_requires_initial_logged_in_session(self):
        self.assertFalse(logout_evidence(self.records()[1:])["proven"])

    def test_unknown_breaks_continuity(self):
        rows = self.records()
        rows[8]["session_count"] = None
        self.assertFalse(logout_evidence(rows)["proven"])

    def test_sampling_gap_cannot_be_counted_as_survival(self):
        rows = self.records()[:3] + self.records()[10:]
        self.assertFalse(logout_evidence(rows)["proven"])

    def test_pid_reuse_or_host_restart_rejected(self):
        for key, value in (("pid", 124), ("start_ticks", "99"), ("boot_id", "new-boot")):
            rows = self.records()
            rows[-1][key] = value
            result = logout_evidence(rows)
            self.assertFalse(result["proven"])
            self.assertEqual(result["reason"], "worker_identity_changed")

    def test_monotonic_clock_reversal_breaks_continuity(self):
        rows = self.records()
        rows[8]["monotonic_seconds"] = 1
        self.assertFalse(logout_evidence(rows)["proven"])


class OwnershipTests(unittest.TestCase):
    def setUp(self):
        self.handle = dict(unit="teflow-rt-example.service", description="owned", invocation_id="original", status="submitted")
        self.props = dict(Id=self.handle["unit"], Description="owned", Transient="yes", InvocationID="original", LoadState="loaded")

    def test_wrong_invocation_never_signals_service(self):
        state = dict(properties=dict(self.props, InvocationID="replacement"))
        with patch("teflow_runtime.systemd.info", return_value=state), patch("teflow_runtime.systemd.call") as command:
            result = stop_owned(self.handle)
            self.assertFalse(result["confirmed"])
            command.assert_not_called()

    def test_same_name_nontransient_service_not_owned(self):
        self.assertFalse(identity_matches(self.handle, dict(self.props, Transient="no")))

    def test_previous_attempt_cannot_be_resubmitted_even_after_disappearance(self):
        with patch("teflow_runtime.systemd.validate_handle"), patch("teflow_runtime.systemd.call") as command:
            with self.assertRaisesRegex(RuntimeError, "already been submitted"):
                submit(self.handle, ["unused"])
            command.assert_not_called()

    def test_unknown_backend_never_launches(self):
        handle = dict(self.handle, status="prepared", directory="unused")
        with patch("teflow_runtime.systemd.validate_handle"), patch("teflow_runtime.systemd.info", return_value=dict(properties={})), patch("teflow_runtime.systemd.call") as command:
            with self.assertRaisesRegex(RuntimeError, "backend state unknown"):
                submit(handle, ["unused"])
            command.assert_not_called()

    def test_invalid_resource_requests_rejected(self):
        for spec in (Resources((0, 0), 128, 1), Resources((0,), 0, 1), Resources((0,), 128, 1, swap_bytes=-1), Resources((True,), 128, 1)):
            with self.assertRaises(ValueError):
                spec.validate()

    def test_feedback_excludes_payload_and_symlinks(self):
        import tarfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "evidence"
            root.mkdir()
            (root / "summary.json").write_text('{"status":"test"}')
            (root / "genome.fa").write_text(">excluded\nACGT\n")
            archive = feedback(root)
            with tarfile.open(archive) as tar:
                self.assertEqual(tar.getnames(), ["summary.json"])
            self.assertFalse(Path(archive + ".sha256").exists())


class LoginCompatibilityTests(unittest.TestCase):
    def test_successful_but_empty_command_is_unknown(self):
        state = parse_login(dict(returncode=0, stdout="", stderr=""))
        self.assertEqual(state["status"], "LOGIN_STATE_UNAVAILABLE")
        self.assertIsNone(state["linger"])
        self.assertIsNone(state["session_count"])

    def test_server_four_session_output(self):
        state = parse_login(dict(returncode=0, stdout="Sessions=212 211 185 69\nLinger=yes\n"))
        self.assertEqual((state["status"], state["linger"], state["session_count"]), ("LOGIN_STATE_READ", "yes", 4))

    def test_explicit_empty_sessions_are_zero(self):
        state = parse_login(dict(returncode=0, stdout="Sessions=\nLinger=yes\n"))
        self.assertEqual(state["session_count"], 0)

    def test_missing_failed_or_duplicate_properties_are_not_zero(self):
        for result in (dict(returncode=0, stdout="Linger=yes\n"), dict(returncode=1, stdout="Linger=yes\nSessions=\n"),
                       dict(returncode=0, stdout="Linger=yes\nLinger=no\nSessions=\n")):
            self.assertEqual(parse_login(result)["status"], "LOGIN_STATE_UNAVAILABLE")
            self.assertIsNone(parse_login(result)["session_count"])

    def test_legacy_loginctl_requires_separate_property_arguments(self):
        def legacy_query(argv, **kwargs):
            requested = [argv[i + 1] for i, value in enumerate(argv[:-1]) if value == "-p"]
            props = {"Linger": "yes", "Sessions": "212 211 185 69"}
            return dict(returncode=0, stdout="".join(key + "=" + props[key] + "\n" for key in requested if key in props))
        with patch("teflow_runtime.login.os.getuid", return_value=1002, create=True), patch("teflow_runtime.login.call", side_effect=legacy_query):
            self.assertEqual(login_state()["session_count"], 4)

    def test_unreadable_linger_does_not_claim_disabled_or_launch(self):
        state = parse_login(dict(returncode=0, stdout=""))
        output = io.StringIO()
        with patch("teflow_runtime.acceptance.preflight", return_value={}), patch("teflow_runtime.acceptance.login_state", return_value=state), \
                patch("teflow_runtime.acceptance.new_attempt") as launch, contextlib.redirect_stdout(output):
            self.assertEqual(logout_start("unused", 600), 2)
            launch.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())["status"], "LOGIN_STATE_UNAVAILABLE")

    def test_known_disabled_linger_is_reported_separately(self):
        state = parse_login(dict(returncode=0, stdout="Linger=no\nSessions=1\n"))
        output = io.StringIO()
        with patch("teflow_runtime.acceptance.preflight", return_value={}), patch("teflow_runtime.acceptance.login_state", return_value=state), contextlib.redirect_stdout(output):
            self.assertEqual(logout_start("unused", 600), 2)
        self.assertEqual(json.loads(output.getvalue())["status"], "NEEDS_LINGER")

    def test_attempt_receipt_is_bound_to_original_invocation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            handle = dict(attempt_id="a" * 32, unit="teflow-rt-owned.service", invocation_id="b" * 32)
            (root / "handle.json").write_text(json.dumps(handle))
            pointer = root / "pointer.json"
            pointer.write_text(json.dumps(dict(handle, schema_version=1, kind="logout", attempt=str(root))))
            self.assertEqual(resolve_attempt_file(pointer), str(root.resolve()))
            (root / "handle.json").write_text(json.dumps(dict(handle, invocation_id="c" * 32)))
            with self.assertRaisesRegex(RuntimeError, "identity mismatch"):
                resolve_attempt_file(pointer)

    def test_missing_receipt_refuses_followup(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError, "No successful logout-start"):
                resolve_attempt_file(Path(tmp) / "never_started.json")


class AddressBudgetTests(unittest.TestCase):
    def test_high_virtual_baseline_gets_finite_additional_space(self):
        self.assertEqual(address_limit(400 * MIB, -1, -1, 224 * MIB), 656 * MIB)

    def test_existing_soft_and_hard_limits_are_preserved(self):
        self.assertEqual(address_limit(20 * MIB, 150 * MIB, 200 * MIB, 64 * MIB), 150 * MIB)
        self.assertEqual(address_limit(20 * MIB, -1, 200 * MIB, 64 * MIB), 200 * MIB)

    def test_insufficient_inherited_address_space_is_explicit_failure(self):
        with self.assertRaisesRegex(RuntimeError, "RLIMIT_AS_HEADROOM_TOO_SMALL"):
            address_limit(400 * MIB, 450 * MIB, -1, 224 * MIB)


@unittest.skipUnless(sys.platform == "linux", "Linux virtual-address reservation regression")
class VirtualMemoryRegressionTests(unittest.TestCase):
    def test_old_fixed_limit_fails_while_new_incremental_limit_allocates(self):
        import os
        import subprocess
        program = '''
import json, mmap, resource, sys
from pathlib import Path
from teflow_runtime.limits import address_limit, MIB
reserved = mmap.mmap(-1, 384*MIB, flags=mmap.MAP_PRIVATE|mmap.MAP_ANONYMOUS, prot=0)
vm = next(int(row.split()[1])*1024 for row in Path('/proc/self/status').read_text().splitlines() if row.startswith('VmSize:'))
soft, hard = resource.getrlimit(resource.RLIMIT_AS)
limit = 256*MIB if sys.argv[1] == 'old' else address_limit(vm, soft, hard, 64*MIB)
resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
try:
    block = bytearray(32*MIB)
    for n in range(0, len(block), 4096): block[n] = 1
    print('ALLOCATED_32_MIB')
except MemoryError:
    print('MemoryError')
'''
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
        for mode, expected in (("old", "MemoryError"), ("new", "ALLOCATED_32_MIB")):
            result = subprocess.run([sys.executable, "-c", program, mode], capture_output=True, text=True, env=env, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), expected)


if __name__ == "__main__":
    unittest.main()
