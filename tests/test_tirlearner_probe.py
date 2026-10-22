"""Regression: a working EDTA CLI must not hide a failed pandas runtime probe."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from teflow.common import WorkflowError
from teflow.stages import doctor


class TirLearnerDoctorTests(unittest.TestCase):
    def exercise(self, fail_probe, fail_teaid=False):
        versions = {"edta": "2.3.0", "tetrimmer": "1.7.2", "repeatmasker": "4.2.4",
                    "trf": "4.10.0", "dustmasker": "2.17.0"}
        commands = {"edta": "EDTA.pl", "tetrimmer": "TEtrimmer", "repeatmasker": "RepeatMasker",
                    "trf": "trf", "dustmasker": "dustmasker"}
        c = dict(execution=dict(mode="server"), tools={
            name: dict(command=["micromamba", "run", "-p", "/test/envs/" + name, commands[name]],
                       expected_version=version) for name, version in versions.items()})
        calls = []

        def fake_run(argv, cwd, log, *args):
            calls.append(argv)
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


if __name__ == "__main__":
    unittest.main()
