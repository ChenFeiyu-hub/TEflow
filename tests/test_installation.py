import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest

from teflow.common import WorkflowError
from teflow.runtime import software_inventory

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("source_installer", REPO / "scripts/install_tetrimmer_sources.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallationTests(unittest.TestCase):
    def test_checksum_failure_preserves_cached_archive(self):
        with tempfile.TemporaryDirectory() as d:
            cache = Path(d)
            p = cache / "source.tar.gz"
            p.write_bytes(b"incorrect archive")
            with self.assertRaisesRegex(ValueError, "Cached SHA256 mismatch"):
                installer.fetch({"filename": p.name, "sha256": "0" * 64}, cache)
            self.assertEqual(p.read_bytes(), b"incorrect archive")

    def test_archive_traversal_is_rejected_before_any_extraction(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            archive = root / "bad.tar.gz"
            with tarfile.open(archive, "w:gz") as tf:
                for name in ("Tool/valid.py", "Tool/../../outside.py"):
                    entry = tarfile.TarInfo(name)
                    entry.size = 4
                    tf.addfile(entry, io.BytesIO(b"data"))
            dest = root / "extract"
            with self.assertRaisesRegex(ValueError, "Unsafe"):
                installer.extract_checked(archive, dest, "Tool")
            self.assertFalse(dest.exists())

    def test_upstream_source_edit_is_detected_before_freeze(self):
        with tempfile.TemporaryDirectory() as d:
            prefix = Path(d)
            vendor = prefix / "share/teflow-vendor"
            vendor.mkdir(parents=True)
            p = vendor / "tool.py"
            p.write_bytes(b"original")
            lock = vendor / "sources.lock.json"
            lock.write_text(json.dumps({"status": "verified_cli", "files": {
                p.relative_to(prefix).as_posix(): hashlib.sha256(b"original").hexdigest()}}))
            c = {"tools": {"tetrimmer": {"command": ["uninstalled-mamba", "run", "-p", str(prefix), "TEtrimmer"]}}}
            self.assertIn(str(p.resolve()), software_inventory(c))
            p.write_bytes(b"changed")
            with self.assertRaisesRegex(WorkflowError, "source changed/missing"):
                software_inventory(c)

    @unittest.skipUnless(os.name == "posix" and shutil.which("bash"), "Linux shell contract")
    def test_selected_dry_run_never_installs_and_preserves_previous_logs(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            envroot = root / "envs"
            # Existing environment must be solved separately, never replaced.
            (envroot / "tetrimmer/conda-meta").mkdir(parents=True)
            mamba = root / "mock-mamba"
            mamba.write_text('#!/usr/bin/env python3\nimport json,os,sys\nwith open(os.environ["CAPTURE"],"a") as f: f.write(json.dumps(sys.argv[1:])+"\\n")\n')
            mamba.chmod(0o755)
            capture = root / "calls.jsonl"
            env = dict(os.environ, MICROMAMBA=str(mamba), CAPTURE=str(capture))
            args = ["bash", str(REPO / "scripts/bootstrap_server.sh"), str(envroot), "--solve-only", "--only", "tetrimmer"]
            for _ in range(2):
                subprocess.run(args, env=env, check=True, capture_output=True, text=True)
            calls = [json.loads(s) for s in capture.read_text().splitlines()]
            self.assertEqual(len(calls), 2)
            for call in calls:
                self.assertEqual(call[0], "create")
                self.assertIn("--dry-run", call)
                self.assertIn(".solve-only-", call[call.index("-p")+1])
                self.assertTrue(call[-1].endswith("tetrimmer.yml"))
            self.assertEqual(len(list((envroot / "install_logs").glob("*/tetrimmer.log"))), 2)


if __name__ == "__main__":
    unittest.main()
