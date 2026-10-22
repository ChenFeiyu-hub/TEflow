import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from teflow.common import WorkflowError, digest, sha256

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("recovery", REPO / "scripts/recover_tetrimmer_v03.py")
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_recovery_rejects_tampered_or_external_completed_outputs(self):
        folder = self.root / "stage"
        folder.mkdir()
        output = folder / "library.fa"
        output.write_text(">a\nACGT\n")
        material = {"key": {}, "inputs": {}, "source": "fixture"}
        r = dict(status="complete", material=material, fingerprint=digest(material), outputs={str(output): sha256(output)})
        (folder / "complete.json").write_text(json.dumps(r))
        recovery.verify_completed(folder)
        output.write_text("changed")
        with self.assertRaisesRegex(WorkflowError, "missing/changed"):
            recovery.verify_completed(folder)
        external = self.root / "outside"; external.write_text("data")
        r["outputs"] = {str(external): sha256(external)}
        (folder / "complete.json").write_text(json.dumps(r))
        with self.assertRaisesRegex(WorkflowError, "out-of-scope"):
            recovery.verify_completed(folder)
