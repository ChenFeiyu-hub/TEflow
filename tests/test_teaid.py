import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from teflow.common import WorkflowError, digest, sha256
from teflow.teaid import database_prefix, probe_teaid, installed_repeatpeps, prepare_database

class TeaIdTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.c = {"tools": {n: {"command": ["mamba", "run", "-p", str(self.root / n), "tool"]}
                            for n in ("tetrimmer", "edta", "repeatmasker")}}

    def tearDown(self):
        self.tmp.cleanup()

    def assets(self):
        p = database_prefix(self.c)
        p.parent.mkdir(parents=True)
        p.write_text(">protein\n" + "MAYK" * 30 + "\n")
        for ext in (".phr", ".pin", ".psq"):
            Path(str(p) + ext).write_text("index fixture")
        return p

    def test_missing_and_unusable_protein_database_fail(self):
        with self.assertRaisesRegex(WorkflowError, "missing or empty"):
            probe_teaid(self.c, self.root / "probe")
        self.assets()
        with patch("teflow.teaid.run", return_value=""):
            with self.assertRaisesRegex(WorkflowError, "no hit"):
                probe_teaid(self.c, self.root / "probe")

    def test_real_commands_use_protein_type_and_one_thread(self):
        self.assets()
        with patch("teflow.teaid.run", side_effect=["protein db", "teflowProteinProbe\tsubject\t100\n"]) as run:
            self.assertEqual(probe_teaid(self.c, self.root / "probe")["status"], "pass")
        self.assertIn("prot", run.call_args_list[0].args[0])
        self.assertIn("blastp", run.call_args_list[1].args[0])
        argv = run.call_args_list[1].args[0]
        self.assertEqual(argv[argv.index("-num_threads")+1], "1")

    def test_installed_library_is_resolved_from_package_metadata(self):
        env = self.root / "tetrimmer"
        meta = env / "conda-meta"
        meta.mkdir(parents=True)
        rel = "share/RepeatMasker/Libraries/RepeatPeps.lib"
        library = env / rel
        library.parent.mkdir(parents=True)
        library.write_text(">protein\n" + "MAKT" * 30 + "\n")
        (meta / "repeatmasker-4.2.4-build.json").write_text(json.dumps({"name": "repeatmasker", "files": [rel]}))
        self.assertEqual(installed_repeatpeps(self.c), library.resolve())

    def test_database_build_failure_preserves_previous_database(self):
        p = self.assets()
        (p.parent.parent / "TE-Aid").write_text("upstream")
        vendor = self.root / "tetrimmer/share/teflow-vendor"
        (vendor / "sources.lock.json").write_text(json.dumps({"files": {}}))
        source = self.root / "RepeatPeps.lib"
        source.write_text(">new\n" + "MLKY" * 30 + "\n")
        before = sha256(p)
        with patch("teflow.teaid.run", side_effect=WorkflowError("makeblastdb failed")):
            with self.assertRaises(WorkflowError):
                prepare_database(self.c, source, self.root / "install")
        self.assertEqual(sha256(p), before)
