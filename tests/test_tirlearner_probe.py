"""Regression: a working EDTA CLI must not hide a failed pandas runtime probe."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from teflow.common import WorkflowError
from teflow.stages import doctor


class TirLearnerDoctorTests(unittest.TestCase):
    def exercise(self, fail_probe, fail_teaid=False, v4=False, explicit_v3=False):
        versions = {"edta": "2.3.0", "tetrimmer": "1.7.2", "repeatmasker": "4.2.4",
                    "trf": "4.10.0", "dustmasker": "2.17.0"}
        commands = {"edta": "EDTA.pl", "tetrimmer": "TEtrimmer", "repeatmasker": "RepeatMasker",
                    "trf": "trf", "dustmasker": "dustmasker"}
        c = dict(execution=dict(mode="server"), tools={
            name: dict(command=["micromamba", "run", "-p", "/test/envs/" + name, commands[name]],
                       expected_version=version) for name, version in versions.items()})
        if v4:
            c["tools"]["edta"]["tir_learner"] = dict(backend="v4-cpu", version="4.08", prefix="/test/envs/tir4")
        elif explicit_v3:
            c["tools"]["edta"]["tir_learner"] = dict(backend="v3", version="3.0.7")
        calls = []

        def fake_run(argv, cwd, log, *args):
            calls.append(argv)
            if "probe" in argv and "--backend" in argv:
                if fail_probe:
                    raise WorkflowError("CPU model inference failed")
                return json.dumps(dict(status="pass", backend="v4-cpu" if v4 else "v3", version="4.08" if v4 else "3.0.7"))
            if Path(argv[-1]).name == "tirlearner_probe.py":
                self.assertEqual(argv[3:5], ["/test/envs/edta", "python"])
                if fail_probe:
                    raise WorkflowError("Command exited 1; pandas 3 indexing failed")
                return json.dumps(dict(status="pass", pandas="2.3.3", rows=3))
            if "--check_dependencies" in argv:
                return "All passed!"
            if "RepeatClassifier" in argv:
                if "-help" in argv:
                    return "RepeatClassifier 2.0.9 -consensi"
                original = (Path(cwd) / "probe.fa").read_text().splitlines()
                (Path(cwd) / "probe.fa.classified").write_text(">teflowProbe#Unknown\n" + original[1] + "\n")
                return "classification complete"
            return " ".join(versions.values()) + " --input_file --pfam_dir --continue_analysis --num_threads"

        with tempfile.TemporaryDirectory() as d, patch("teflow.stages.run", side_effect=fake_run), patch("teflow.teaid.probe_teaid", return_value={"status": "pass"}, side_effect=WorkflowError("RepeatPeps missing") if fail_teaid else None):
            if fail_probe or fail_teaid:
                with self.assertRaises(WorkflowError):
                    doctor(c, d, dependency_check=True)
            else:
                doctor(c, d, dependency_check=True)
            attempts = list((Path(d) / "attempts").glob("*/doctor.json"))
            self.assertEqual(len(attempts), 1)
            result = json.loads(attempts[0].read_text())
            self.assertEqual((Path(d) / "doctor.json").exists(), not (fail_probe or fail_teaid))
        return result, calls

    def test_indexing_failure_is_recorded_even_when_all_other_probes_pass(self):
        result, calls = self.exercise(True)
        self.assertEqual(result["status"], "fail")
        failed = [c for c in result["checks"] if c["status"] == "fail"]
        self.assertEqual([c["tool"] for c in failed], ["edta_tirlearner_pandas"])

    def test_compatible_indexing_adds_runtime_evidence(self):
        result, calls = self.exercise(False)
        self.assertEqual(result["status"], "pass")
        evidence = next(c for c in result["checks"] if c["tool"] == "edta_tirlearner_pandas")
        self.assertEqual(evidence["pandas"], "2.3.3")
        self.assertEqual(len(result["checks"]), 10)

    def test_missing_teaid_db_blocks_doctor_while_cli_and_classifiers_pass(self):
        result, _ = self.exercise(False, fail_teaid=True)
        self.assertEqual([r["tool"] for r in result["checks"] if r["status"] == "fail"], ["teaid_protein_database"])

    def test_v4_checks_actual_model_instead_of_irrelevant_legacy_pandas(self):
        result, calls = self.exercise(False, v4=True)
        self.assertEqual(result["tir_backend"]["backend"], "v4-cpu")
        self.assertIn("edta_tirlearner_cpu", [c["tool"] for c in result["checks"]])
        self.assertFalse(any(Path(c[-1]).name == "tirlearner_probe.py" for c in calls))

    def test_failed_v4_model_blocks_acceptance(self):
        result, _ = self.exercise(True, v4=True)
        self.assertEqual([r["tool"] for r in result["checks"] if r["status"] == "fail"], ["edta_tirlearner_cpu"])

    def test_explicit_v3_uses_package_version_and_pandas_probe(self):
        result, calls = self.exercise(False, explicit_v3=True)
        self.assertEqual(result["status"], "pass")
        probe = next(c for c in calls if "--backend" in c)
        self.assertEqual(probe[probe.index("--backend") + 1], "v3")
        evidence = next(c for c in result["checks"] if c["tool"] == "edta_tirlearner_pandas")
        self.assertEqual(evidence["version"], "3.0.7")


if __name__ == "__main__":
    unittest.main()
