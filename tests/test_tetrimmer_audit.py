import csv
import json
from pathlib import Path
import tempfile
import unittest
from teflow.common import WorkflowError
from teflow.tetrimmer_audit import audit_tetrimmer


class TetrimmerAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.input = self.root / "input.fa"
        self.input.write_text(">E14#LTR/Gypsy\nAACGTTAC\n")
        self.out = self.root / "out"
        self.out.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def outputs(self, evaluation="Need_check", copies="10", seq="AACGTTAC", name="E14", output_name=None):
        (self.out / "summary.txt").write_text(
            "input_name,output_name,status,evaluation,low_copy,input_full_blast_n,output_length\n"
            f"{name},{output_name or name},processed,{evaluation},False,{copies},8077\n")
        (self.out / "TEtrimmer_consensus_merged.fasta").write_text(f">{name}#LTR/Gypsy\n{seq}\n")

    def test_fallback_records_actual_length_and_parent_not_rejected_extension_length(self):
        self.outputs()
        r = audit_tetrimmer(self.out, self.input)
        self.assertEqual(r["retained_origins"], {"original_input_fallback": 1})
        with (self.out / "teflow_parent_map.tsv").open() as f:
            row = next(csv.DictReader(f, delimiter="\t"))
        self.assertEqual(row["retained_length"], "8")
        self.assertEqual(row["summary_output_length"], "8077")

    def test_rejected_extension_and_insufficient_copy_count_are_not_accepted(self):
        for seq, copies in [("AACGTTACAAAA", "10"), ("AACGTTAC", "1"), ("AACGTTAC", "NaN")]:
            self.outputs(seq=seq, copies=copies)
            with self.assertRaisesRegex(WorkflowError, "Invalid.*fallback"):
                audit_tetrimmer(self.out, self.input)

    def test_need_ext_and_renamed_parent_are_traced_to_original(self):
        self.outputs(evaluation="Need_ext", name="renamed")
        (self.out / "Sequence_name_mapping.txt").write_text(
            "original_input_seq_name\tTEtrimmer_modified_seq_name\nE14#LTR/Gypsy\trenamed#LTR/Gypsy\n")
        audit_tetrimmer(self.out, self.input)
        with (self.out / "teflow_parent_map.tsv").open() as f:
            row = next(csv.DictReader(f, delimiter="\t"))
        self.assertEqual(row["input_name"], "E14")

    def test_parent_fallback_can_reference_failed_subfamily_rows(self):
        self.outputs(output_name="E14_01")
        self.assertEqual(audit_tetrimmer(self.out, self.input)["retained_families"], 1)

    def test_full_or_truncated_error_evidence_still_quarantines(self):
        self.outputs()
        for filename in ("error_file.txt", "error_file.txt.tail.txt"):
            error = self.out / filename
            error.write_text("BLAST Database error: No alias or index file found")
            with self.assertRaisesRegex(WorkflowError, "nonempty error logs"):
                audit_tetrimmer(self.out, self.input)
            self.assertEqual(json.loads((self.out / "teflow_audit.json").read_text())["status"], "quarantined")
            error.unlink()

    def test_duplicate_mapping_is_rejected(self):
        self.outputs()
        (self.out / "Sequence_name_mapping.txt").write_text(
            "original_input_seq_name\tTEtrimmer_modified_seq_name\nE14\tE14\nE14\tE14\n")
        with self.assertRaisesRegex(WorkflowError, "uniquely"):
            audit_tetrimmer(self.out, self.input)
