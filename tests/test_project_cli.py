import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from teflow import __version__
from teflow.assets import asset_root, asset_path, recipe_files
from teflow.cli import main
from teflow.common import WorkflowError, load_config, read_json, sha256, source_fingerprint, write_json
from teflow.environments import environment_command
from teflow.launcher import scheduler_command, validate_launch, launch


class ProjectCLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.genome = self.root / "my genome.fa"
        self.genome.write_text(">chr1\nACGTACGTACGT\n")

    def tearDown(self):
        self.temp.cleanup()

    def cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(map(str, args)))
        return code, out.getvalue(), err.getvalue()

    def init(self, *args):
        return self.cli("init", "--root", self.root, "--genome", self.genome, "--sample-id", "new_plant",
                        "--run-id", "test01", *args)

    def config(self):
        code, _, err = self.init("--profile", "edta")
        self.assertEqual(code, 0, err)
        return load_config(self.root / "test01.local.json")

    def test_generic_genome_no_annotation_no_promoters(self):
        c = self.config()
        self.assertEqual(c["samples"][0]["id"], "new_plant")
        self.assertNotIn("annotation", c["samples"][0])
        self.assertFalse(c["evaluation"]["promoter_analysis"])
        self.assertNotIn("tetrimmer", c["tools"])
        self.assertFalse((self.root / "work").exists())

    def test_baseline_is_default_and_wrapper_has_explicit_bash(self):
        self.assertEqual(self.init()[0], 0)
        c = load_config(self.root / "test01.local.json")
        self.assertEqual(c["tools"]["tetrimmer"]["command"][-2], "bash")
        self.assertEqual(environment_command(c, "tetrimmer")[-1], str(self.root / "envs/tetrimmer"))
        self.assertTrue(c["branches"]["edta_tetrimmer"]["enabled"])
        self.assertFalse(c["branches"]["heliano"]["enabled"])

    def test_invalid_config_never_published(self):
        cases = [("--protein-qc",), ("--threads", "1"), ("--branch", "heliano"),
                 ("--branch", "edta", "--branch", "edta"), ("--profile", "arabidopsis-compare")]
        for args in cases:
            self.assertEqual(self.init(*args)[0], 2, args)
            self.assertFalse((self.root / "test01.local.json").exists())

    def test_explicit_heliano_requires_edta_and_does_not_enable_hite(self):
        self.assertEqual(self.init("--branch", "edta", "--branch", "heliano")[0], 0)
        c = load_config(self.root / "test01.local.json")
        self.assertIn("heliano", c["tools"])
        self.assertNotIn("hite", c["tools"])

    def test_new_config_refuses_existing_run_or_file(self):
        c = self.config()
        before = sha256(c["_config_path"])
        self.assertEqual(self.init()[0], 2)
        self.assertEqual(sha256(c["_config_path"]), before)
        (self.root / "work/existing").mkdir(parents=True)
        self.assertEqual(self.init("--run-id", "existing")[0], 2)
        self.assertFalse((self.root / "existing.local.json").exists())

    def test_fork_preserves_scientific_settings_and_old_config(self):
        self.assertEqual(self.init()[0], 0)
        old = self.root / "test01.local.json"
        c = read_json(old)
        c["evaluation"]["promoter_analysis"] = True
        c["parameters"]["max_divergence"] = 31
        c["tools"]["tetrimmer"]["command"][-2:] = [str(self.root / "old/scripts/run_tetrimmer_isolated.sh")]
        write_json(old, c)
        before = sha256(old)
        output = self.root / "new.local.json"
        code, _, err = self.cli("fork-config", "--config", old, "--output", output, "--run-id", "new")
        self.assertEqual(code, 0, err)
        new = read_json(output)
        for key in ("branches", "parameters", "qc", "evaluation", "samples", "databases", "execution"):
            self.assertEqual(new[key], c[key])
        self.assertEqual(new["tools"]["tetrimmer"]["command"][-2], "bash")
        self.assertEqual(sha256(old), before)
        self.assertFalse((self.root / "work").exists())
        self.assertFalse(read_json(str(output) + ".fork.json")["outputs_imported"])

    def test_fork_refuses_existing_sidecar_without_creating_config(self):
        c = self.config()
        out = self.root / "other.json"
        Path(str(out) + ".fork.json").write_text("preserved")
        self.assertEqual(self.cli("fork-config", "--config", c["_config_path"], "--output", out, "--run-id", "other")[0], 2)
        self.assertFalse(out.exists())

    def test_assets_reject_escape_and_override_is_explicit(self):
        root = asset_root()
        self.assertTrue(asset_path("workflow/Snakefile").is_file())
        for bad in ("../pyproject.toml", str(self.genome), "workflow/../../outside"):
            with self.assertRaises(WorkflowError):
                asset_path(bad)
        with patch.dict(os.environ, {"TEFLOW_REPOSITORY": str(root)}):
            self.assertEqual(len(source_fingerprint()), 64)
            self.assertEqual(recipe_files()["workflow/Snakefile"], root / "workflow/Snakefile")
        with patch.dict(os.environ, {"TEFLOW_REPOSITORY": str(self.root)}):
            with self.assertRaises(WorkflowError):
                asset_root()

    def test_scheduler_arguments_keep_resource_and_target_contract(self):
        c = self.config()
        command = scheduler_command(c, resume=True, target="export_edta")
        self.assertIn("resume=1", command)
        self.assertEqual(command.index('resume=1'),command.index('--config')+2)
        self.assertIn("--rerun-incomplete", command)
        self.assertIn("io_heavy=1", command)
        self.assertEqual(command[-2], "--")
        self.assertTrue(command[-1].endswith("export_edta.done"))
        self.assertIn("--dry-run", scheduler_command(c, dry_run=True))
        with self.assertRaises(WorkflowError):
            scheduler_command(c, dry_run=True, resume=True)

    def test_invalid_target_and_slurm_budgets_stop_before_freeze(self):
        c = self.config()
        with self.assertRaisesRegex(WorkflowError, "not enabled"):
            validate_launch(c, "hite", {})
        for env in ({"SLURM_CPUS_PER_TASK": "1"}, {"SLURM_MEM_PER_NODE": "4096"},
                    {"SLURM_CPUS_PER_TASK": "32", "SLURM_MEM_PER_CPU": "2000"}, {"SLURM_CPUS_PER_TASK": "bad"}):
            with self.assertRaises(WorkflowError):
                validate_launch(c, environ=env)
        validate_launch(c, environ={"SLURM_CPUS_PER_TASK": "32", "SLURM_MEM_PER_NODE": "131072"})
        args = argparse.Namespace(config=c["_config_path"], target_stage="hite", dry_run=False, resume=False)
        with patch("teflow.launcher.freeze") as frozen:
            with self.assertRaises(WorkflowError):
                launch(args)
            frozen.assert_not_called()

    def test_check_records_failure_and_does_not_freeze(self):
        c = self.config()
        with patch("teflow.launcher.doctor", side_effect=WorkflowError("probe failed")):
            code, _, err = self.cli("check", "--config", c["_config_path"], "--versions-only")
        self.assertEqual(code, 2)
        report = next((self.root / "work/test01/checks").glob("*/check.json"))
        self.assertEqual(read_json(report)["status"], "fail")
        self.assertIn(str(report), err)
        self.assertFalse((self.root / "work/test01/run_manifest.json").exists())

    def test_capabilities_report_evidence_scope(self):
        code, out, _ = self.cli("capabilities")
        info = json.loads(out)
        self.assertEqual((code, info["teflow_version"]), (0, __version__))
        self.assertFalse(info["branches"]["heliano"]["independent"])
        self.assertEqual(info["branches"]["reference_only"]["validation"], "fixture_only")
        self.assertFalse(info["automatic_branch_selection"])

    def test_failed_probe_and_dispatch_failure_are_recorded(self):
        c = self.config()
        args = argparse.Namespace(config=c["_config_path"], target_stage=None, dry_run=False, resume=False)
        with patch("teflow.launcher.sys.platform", "linux"), patch("teflow.launcher.importlib.util.find_spec", return_value=object()), \
             patch('teflow.launcher.acquire_controller',return_value=os.open(os.devnull,os.O_RDONLY)), \
             patch("teflow.launcher.freeze", return_value={"fingerprint": "test"}), \
             patch("teflow.launcher.doctor", side_effect=WorkflowError("bad dependency")), \
             patch("teflow.launcher.subprocess.Popen") as execute:
            with self.assertRaisesRegex(WorkflowError, "bad dependency"):
                launch(args)
            execute.assert_not_called()
        with patch("teflow.launcher.sys.platform", "linux"), patch("teflow.launcher.importlib.util.find_spec", return_value=object()), \
             patch('teflow.launcher.acquire_controller',return_value=os.open(os.devnull,os.O_RDONLY)), \
             patch("teflow.launcher.freeze", return_value={"fingerprint": "test"}), patch("teflow.launcher.doctor"), \
             patch("teflow.launcher.subprocess.Popen", side_effect=OSError("dispatch failed")) as execute, \
             contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaisesRegex(OSError, "dispatch failed"):
                launch(args)
            self.assertEqual(execute.call_args.kwargs["env"]["OPENBLAS_NUM_THREADS"], "1")
        receipts = list((self.root / "work/test01/launches").glob("*.json"))
        self.assertEqual(len(receipts), 2)
        self.assertTrue(all(read_json(p)["status"] == "failed" for p in receipts))
        self.assertNotIn('TEFLOW_CANCEL_FILE', os.environ)


if __name__ == "__main__":
    unittest.main()
