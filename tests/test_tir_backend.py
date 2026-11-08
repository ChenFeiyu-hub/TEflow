import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from teflow.assets import asset_path
from teflow.cli import main
from teflow.common import WorkflowError, load_config, read_json, write_json
from teflow.edta_entry import cpu_environment, find_edta_main, require_version
from teflow.stages import stage_key
from teflow.tir_backend import configure, command, inventory_paths, selected, validate
from teflow.tir_audit import inspect_native, audit_edta_tir


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.config = dict(tools=dict(edta=dict(command=["micromamba", "run", "-p", str(self.root / "edta"), "EDTA.pl"], expected_version="2.3.0")))

    def tearDown(self):
        self.tmp.cleanup()

    def cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(map(str, args)))
        self.assertEqual(code, 0, err.getvalue())
        return out.getvalue()

    def make_project(self):
        genome = self.root / "genome.fa"
        genome.write_text(">chr1\nACGTACGT\n")
        self.cli("init", "--root", self.root, "--genome", genome, "--sample-id", "s", "--run-id", "r", "--profile", "edta")
        return self.root / "r.local.json"

    def test_new_default_and_fork_fallback_do_not_rewrite_old_config(self):
        path = self.make_project()
        before = path.read_bytes()
        c = load_config(path)
        self.assertEqual(selected(c)["backend"], "v4-cpu")
        self.assertIn("run_edta.py", " ".join(command(c)))
        target = self.root / "fallback.json"
        self.cli("fork-config", "--config", path, "--output", target, "--run-id", "fallback", "--tir-learner", "v3")
        new = load_config(target)
        self.assertEqual(selected(new)["backend"], "v3")
        self.assertEqual(command(new)[-1], "EDTA.pl")
        self.assertEqual(path.read_bytes(), before)
        self.assertNotEqual(stage_key(c, "edta", 32), stage_key(new, "edta", 32))
        self.assertFalse((self.root / "work").exists())

    def test_legacy_config_and_plain_fork_keep_v3_semantics(self):
        path = self.make_project()
        c = read_json(path)
        del c["tools"]["edta"]["tir_learner"]
        write_json(path, c)
        self.assertEqual(selected(load_config(path))["selection"], "legacy_config")
        target = self.root / "preserved.json"
        self.cli("fork-config", "--config", path, "--output", target, "--run-id", "preserved")
        self.assertNotIn("tir_learner", read_json(target)["tools"]["edta"])

    def test_custom_environment_and_version_rejection(self):
        configure(self.config, "v4-cpu", self.root / "accepted-v4")
        validate(self.config, lambda value: str(Path(value).resolve()))
        self.assertIn(str(self.root / "accepted-v4"), command(self.config))
        self.config["tools"]["edta"]["tir_learner"]["version"] = "4.09"
        with self.assertRaises(WorkflowError):
            validate(self.config, str)

    def test_same_environment_and_invalid_fallback_prefix_rejected(self):
        configure(self.config, "v4-cpu", self.root / "edta")
        with self.assertRaisesRegex(WorkflowError, "isolated"):
            validate(self.config, str)
        with self.assertRaisesRegex(WorkflowError, "only applicable"):
            configure(self.config, "v3", self.root / "edta")

    def test_cpu_environment_drops_python_contamination_preserves_runtime_ownership(self):
        env = cpu_environment(dict(PYTHONPATH="unrelated", PYTHONHOME="wrong", CUDA_VISIBLE_DEVICES="0", KERAS_BACKEND="tensorflow", TEFLOW_LEASE_ID="owned", TMPDIR="private"))
        self.assertNotIn("PYTHONPATH", env)
        self.assertNotIn("PYTHONHOME", env)
        self.assertEqual(env["CUDA_VISIBLE_DEVICES"], "")
        self.assertEqual(env["KERAS_BACKEND"], "torch")
        self.assertEqual(env["TEFLOW_LEASE_ID"], "owned")
        self.assertEqual(env["TMPDIR"], "private")

    def test_package_version_not_misleading_cli_banner(self):
        require_version({"tir-learner": {"version": "4.8"}}, "tir-learner", "4.08")
        with self.assertRaises(WorkflowError):
            require_version({"tir-learner": {"version": "4.0801"}}, "tir-learner", "4.08")

    def test_real_perl_source_selected_instead_of_basename_dispatcher(self):
        prefix = self.root / "edta"
        folder = prefix / "share/EDTA"
        (folder / "bin").mkdir(parents=True)
        (prefix / "bin").mkdir()
        (prefix / "bin/EDTA_raw.pl").write_text("#!/bin/bash\n# dispatcher\n")
        (folder / "EDTA_raw.pl").write_text("#!/usr/bin/perl\n# convert_seq_name TIR-Learner_FinalAnn --type\n")
        (folder / "EDTA.pl").write_text("#!/usr/bin/perl\n# EDTA_raw.pl check_dependencies EDTA.TElib.fa\n")
        (folder / "bin/rename_tirlearner.pl").write_text("# helper\n")
        write_json(prefix / "conda-meta/edta.json", dict(name="edta", version="2.3.0", files=["share/EDTA/EDTA_raw.pl"]))
        self.assertEqual(find_edta_main(prefix), folder / "EDTA.pl")

    def test_freeze_inventory_contains_model_source_and_dependency_metadata(self):
        prefix = self.root / "tir4"
        source = prefix / "lib/tir-learner4/app/main.py"
        source.parent.mkdir(parents=True)
        source.write_text("# upstream\n")
        model = prefix / "lib/tir-learner4/cnn0912/cnn0912.keras"
        model.parent.mkdir()
        model.write_bytes(b"synthetic model placeholder")
        write_json(prefix / "conda-meta/tir-learner.json", dict(name="tir-learner", version="4.08", files=["lib/tir-learner4/app/main.py"]))
        torch_meta = prefix / "conda-meta/pytorch.json"
        write_json(torch_meta, dict(name="pytorch", version="test", build="cpu_test"))
        configure(self.config, "v4-cpu", prefix)
        inventory = inventory_paths(self.config)
        self.assertTrue({model, source, torch_meta} <= inventory)
        model.unlink()
        with self.assertRaisesRegex(WorkflowError, "model is missing"):
            inventory_paths(self.config)


class NativeAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.fa, self.gff = self.root / "raw.fa", self.root / "raw.gff3"
        self.fa.write_text(">one\nACGT\n")
        self.row = "chr1\tModule4\tDTA\t2\t5\t.\t.\t.\tTIR:AC_GT_100_TSD:AA_AA_100-+-4\t9000\t200\t200\t200\t200\t200\n"
        self.gff.write_text(self.row)

    def tearDown(self):
        self.tmp.cleanup()

    def test_extended_scores_retained_without_calibration_claim(self):
        summary, rows = inspect_native(self.fa, self.gff, {"chr1": "NACGTN"})
        self.assertTrue(summary["sequence_span_check"])
        self.assertEqual(summary["column_counts"], {15: 1})
        self.assertEqual(rows[0]["score_DTA"], 9000)
        self.assertEqual(summary["score_calibration"], "not_established")
        self.assertEqual((rows[0]["start"], rows[0]["end"]), (1, 5))

    def test_sequence_or_coordinate_mismatch_is_not_tolerated(self):
        with self.assertRaisesRegex(WorkflowError, "genomic spans"):
            inspect_native(self.fa, self.gff, {"chr1": "NACGCN"})
        with self.assertRaisesRegex(WorkflowError, "outside"):
            inspect_native(self.fa, self.gff, {"chr1": "AC"})

    def test_bad_score_and_field_count_rejected(self):
        for bad in (self.row.replace("9000", "10001"), self.row.rstrip() + "\t7\n"):
            self.gff.write_text(bad)
            with self.assertRaises(WorkflowError):
                inspect_native(self.fa, self.gff)

    def test_duplicates_reported_not_removed_and_zero_output_supported(self):
        self.fa.write_text(">one\nACGT\n>two\nACGT\n")
        self.gff.write_text(self.row * 2)
        summary, rows = inspect_native(self.fa, self.gff, {"chr1": "NACGTN"})
        self.assertEqual(summary["duplicate_site_records"], 1)
        self.assertEqual(len(rows), 2)
        self.fa.write_text("")
        self.gff.write_text("")
        summary, _ = inspect_native(self.fa, self.gff, {"chr1": "NACGTN"})
        self.assertTrue(summary["zero_candidates"])

    def test_outputs_without_successful_actual_call_do_not_pass(self):
        with self.assertRaisesRegex(WorkflowError, "actual v4 discovery"):
            audit_edta_tir(self.root, dict(prefix="/tir4", version="4.08"), {"chr1": "ACGT"})

    def test_successful_discovery_audits_native_evidence_but_later_failure_cannot_reuse_it(self):
        native = self.root / "genome.fa.mod.EDTA.raw/TIR/TIR-Learner-Result"
        native.mkdir(parents=True)
        (native / "TIR-Learner_FinalAnn.fa").write_bytes(self.fa.read_bytes())
        (native / "TIR-Learner_FinalAnn.gff3").write_bytes(self.gff.read_bytes())
        spec = dict(prefix=str(self.root / "tir4"), version="4.08")
        attempt = self.root / ".teflow-tir/first"
        write_json(attempt / "launch.json", dict(started="2026-11-08T01:00:00Z"))
        call = dict(status="complete", returncode=0, forwarded=["-f", "genome.fa"],
                    backend="v4-cpu", version="4.08", tir_prefix=spec["prefix"])
        write_json(attempt / "calls/discovery.json", call)
        summary, outputs = audit_edta_tir(self.root, spec, {"chr1": "NACGTN"})
        self.assertEqual(summary["verified_discovery_calls"], 1)
        self.assertEqual(summary["records"], 1)
        self.assertEqual(read_json(self.root / "tir_audit.json")["score_calibration"], "not_established")
        self.assertIn(attempt / "calls/discovery.json", outputs)
        self.assertEqual((native / "TIR-Learner_FinalAnn.gff3").read_bytes(), self.gff.read_bytes())
        later = self.root / ".teflow-tir/second"
        write_json(later / "launch.json", dict(started="2026-11-08T02:00:00Z"))
        write_json(later / "calls/discovery.json", dict(call, status="failed", returncode=7))
        with self.assertRaisesRegex(WorkflowError, "current v4 discovery"):
            audit_edta_tir(self.root, spec, {"chr1": "NACGTN"})


@unittest.skipUnless(sys.platform == "linux", "Real Linux bridge subprocess contract")
class LinuxBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.old, self.new = self.root / "edta", self.root / "tir4"
        for prefix in (self.old, self.new):
            (prefix / "bin").mkdir(parents=True)
        src = self.old / "share/EDTA"
        (src / "bin").mkdir(parents=True)
        (src / "EDTA_raw.pl").write_text("#!/usr/bin/perl\n# convert_seq_name TIR-Learner_FinalAnn --type\n")
        (src / "EDTA.pl").write_text("#!/usr/bin/perl\n# EDTA_raw.pl check_dependencies EDTA.TElib.fa\n")
        (src / "bin/rename_tirlearner.pl").write_text("# helper")
        write_json(self.old / "conda-meta/edta.json", dict(name="edta", version="2.3.0", files=["share/EDTA/EDTA_raw.pl"]))
        write_json(self.new / "conda-meta/tir.json", dict(name="tir-learner", version="4.08"))
        model = self.new / "lib/tir-learner4/cnn0912/cnn0912.keras"
        model.parent.mkdir(parents=True)
        model.write_text("synthetic placeholder, not used for inference")
        self.mamba = self.root / "micromamba"
        self.script(self.mamba, "import os,sys,subprocess\na=sys.argv[1:]\nassert a[:2]==['run','-p']\ne=dict(os.environ,CONDA_PREFIX=a[2],PATH=a[2]+'/bin:'+os.environ['PATH'])\nsys.exit(subprocess.call(a[3:],env=e))\n")
        self.script(self.old / "bin/python", "import os,sys\nos.execv(" + repr(sys.executable) + ",[" + repr(sys.executable) + ",*sys.argv[1:]])\n")
        self.script(self.old / "bin/perl", "import subprocess,sys\nsys.exit(subprocess.call(['TIR-Learner',*sys.argv[2:]]))\n")
        self.script(self.old / "bin/TIR-Learner", "raise RuntimeError('v3 fallback was forbidden')\n")
        for name in ("RepeatMasker", "RepeatModeler", "blastn", "TEsorter"):
            self.script(self.old / "bin" / name, "pass\n")
        self.script(self.new / "bin/TIR-Learner", "import json,os,sys\nfrom pathlib import Path\nPath('invoked.json').write_text(json.dumps(dict(args=sys.argv[1:],prefix=os.environ['CONDA_PREFIX'],cuda=os.environ['CUDA_VISIBLE_DEVICES'],keras=os.environ['KERAS_BACKEND'],pythonpath=os.environ.get('PYTHONPATH'))))\nsys.exit(int(os.environ.get('SYNTHETIC_TIR_EXIT','0')))\n")
        self.config = dict(tools=dict(edta=dict(command=[str(self.mamba),"run","-p",str(self.old),"EDTA.pl"], expected_version="2.3.0")))
        configure(self.config, "v4-cpu", self.new)

    def script(self, path, body):
        path.write_text("#!" + sys.executable + "\n" + body)
        path.chmod(0o755)

    def tearDown(self):
        self.tmp.cleanup()

    def test_effective_command_routes_only_tir_to_isolated_cpu_prefix(self):
        env = dict(os.environ, CUDA_VISIBLE_DEVICES="0", KERAS_BACKEND="tensorflow", PYTHONPATH="unrelated")
        before = (self.old / "bin/TIR-Learner").read_bytes()
        args = ["-f", "genome.fa", "--grf_path", str(self.old / "bin"), "-t", "4"]
        result = subprocess.run(command(self.config) + args, cwd=self.root, env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        rec = read_json(self.root / "invoked.json")
        self.assertEqual(rec["args"], args)
        self.assertEqual(rec["prefix"], str(self.new))
        self.assertEqual((rec["cuda"], rec["keras"], rec["pythonpath"]), ("", "torch", None))
        calls = list((self.root / ".teflow-tir").glob("*/calls/*.json"))
        self.assertEqual(len(calls), 1)
        self.assertEqual(read_json(calls[0])["returncode"], 0)
        self.assertEqual((self.old / "bin/TIR-Learner").read_bytes(), before)

    def test_failed_v4_exit_propagates_without_fallback(self):
        result = subprocess.run(command(self.config) + ["-f", "genome.fa"], cwd=self.root,
                                env=dict(os.environ, SYNTHETIC_TIR_EXIT="7"), capture_output=True, text=True)
        self.assertEqual(result.returncode, 7, result.stderr)
        call = read_json(next((self.root / ".teflow-tir").glob("*/calls/*.json")))
        self.assertEqual(call["status"], "failed")
        with self.assertRaisesRegex(WorkflowError, "current v4 discovery"):
            audit_edta_tir(self.root, selected(self.config), {"chr1": "ACGT"})

    def test_missing_model_stops_before_dispatch(self):
        (self.new / "lib/tir-learner4/cnn0912/cnn0912.keras").unlink()
        result = subprocess.run(command(self.config) + ["-f", "genome.fa"], cwd=self.root, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / "invoked.json").exists())


if __name__ == "__main__":
    unittest.main()
