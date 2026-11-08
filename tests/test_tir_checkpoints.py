import csv
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from teflow.common import WorkflowError, read_json
from teflow.tir_checkpoints import audit, candidates, CHECKPOINTS


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.native = self.root / "native"
        self.native.mkdir()
        self.sites = self.root / "sites.tsv"
        self.sites.write_text("alias\tstart_0based\tend_exclusive\ns000001\t108\t120\n")
        self.data = {"chunk.fa": {"s000001;;100": dict(seq_length=100, chunking_offset=100,
                       seq_start_incl_tsd=[1], seq_stop_incl_tsd=[28], tsd1_size=[8], tsd2_size=[8], tir1_size=[3], tir2_size=[3])}}

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, data):
        with gzip.open(self.native / name, "wt", encoding="utf-8") as stream:
            json.dump(data, stream)

    def test_native_offsets_and_TSD_exclusion_match_output_formatter(self):
        row = next(candidates(self.data))
        self.assertEqual((row["seqid"], row["start"], row["end"]), ("s000001", 108, 120))

    def test_missing_checkpoints_are_not_negative_calls(self):
        self.write(CHECKPOINTS[0], self.data)
        result = audit(self.native, self.sites, self.root / "out")
        self.assertEqual(result["status"], "AUDIT_PARTIAL")
        with (self.root / "out/checkpoint_counts.tsv").open() as stream:
            rows = list(csv.DictReader(stream, delimiter="\t"))
        self.assertEqual(rows[0]["exact"], "1")
        self.assertEqual(rows[1]["exact"], "")
        self.assertEqual(rows[1]["status"], "missing")

    def test_empty_complete_checkpoints_and_limit_are_explicit(self):
        for name in CHECKPOINTS:
            self.write(name, self.data if name.startswith("post") else {})
        result = audit(self.native, self.sites, self.root / "out", max_matches=1)
        self.assertEqual(result["status"], "AUDIT_READY")
        self.assertTrue(result["match_details_truncated"])
        self.assertEqual((result["matches"], result["matches_saved"]), (2, 1))
        self.assertEqual(read_json(self.root / "out/matches.json")[0]["target_fraction"], 1)

    def test_bad_array_lengths_fail_closed_and_existing_output_preserved(self):
        self.data["chunk.fa"]["s000001;;100"]["tsd1_size"] = []
        self.write(CHECKPOINTS[0], self.data)
        result = audit(self.native, self.sites, self.root / "out")
        self.assertEqual(result["files"][0]["status"], "unavailable")
        self.assertEqual(read_json(self.root / "out/matches.json"), [])
        with self.assertRaisesRegex(WorkflowError, "new audit output"):
            audit(self.native, self.sites, self.root / "out")
        with self.assertRaisesRegex(WorkflowError, "outside the native"):
            audit(self.native, self.sites, self.native / "out")


if __name__ == "__main__":
    unittest.main()
