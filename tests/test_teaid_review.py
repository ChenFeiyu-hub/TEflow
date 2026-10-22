import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from teflow.common import WorkflowError, write_json, sha256, read_json
from teflow.teaid_recovery import new_configuration, verify_files
from teflow.tetrimmer_audit import audit_tetrimmer


class ReviewBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_target_configuration_preserves_parameters_and_old_input(self):
        repo = self.root / "repo"; (repo / "scripts").mkdir(parents=True)
        (repo / "scripts/run_tetrimmer_isolated.sh").write_text("wrapper")
        old = dict(run_id="old", work_root=str(self.root / "work"), results_root=str(self.root / "results"),
                   tools={"tetrimmer":{"command":["mm","run","-p","/env/tt","TEtrimmer"],"expected_version":"1.7.2"}},
                   parameters={"max_divergence":40}, execution={"threads":32}, branches={"edta_tetrimmer":{"enabled":True}})
        snapshot = copy.deepcopy(old)
        new = new_configuration(old,self.root / "new.json","new",repo)
        self.assertEqual(old,snapshot)
        for k in ("parameters","execution","branches"):
            self.assertEqual(new[k],old[k])
        self.assertEqual(new["tools"]["tetrimmer"]["command"][:-1],old["tools"]["tetrimmer"]["command"][:-1])
        (self.root / "new.json").write_text("existing")
        with self.assertRaisesRegex(WorkflowError,"new configuration"):
            new_configuration(old,self.root / "new.json","new",repo)

    def test_evidence_outside_stage_or_modified_is_refused(self):
        stage = self.root / "stage"; stage.mkdir()
        outside = self.root / "outside"; outside.write_text("same")
        with self.assertRaisesRegex(WorkflowError,"evidence"):
            verify_files(stage,{"../outside":sha256(outside)})
        inside = stage / "data"; inside.write_text("data")
        expected = sha256(inside); inside.write_text("changed")
        with self.assertRaisesRegex(WorkflowError,"evidence"):
            verify_files(stage,{"data":expected})

    def test_normal_audit_still_blocks_cleanup_warning_and_forged_review(self):
        inp = self.root / "input.fa"; inp.write_text(">E1#LTR/Gypsy\nAACG\n")
        out = self.root / "out"; out.mkdir()
        (out / "summary.txt").write_text("input_name,output_name,status,evaluation,low_copy\nE1,E1,processed,Good,False\n")
        (out / "TEtrimmer_consensus_merged.fasta").write_text(">E1#LTR/Gypsy\nAACG\n")
        (out / "error_file.txt").write_text("rm: cannot remove 'header': No such file or directory\n")
        with self.assertRaisesRegex(WorkflowError,"nonempty error"):
            audit_tetrimmer(out,inp)
        with self.assertRaisesRegex(WorkflowError,"pinned recovery"):
            audit_tetrimmer(out,inp,reviewed_cleanup={"status":"verified_sequence_level_reuse"})
        self.assertEqual(read_json(out / "teflow_audit.json")["status"],"quarantined")
