import csv
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from teflow.common import WorkflowError, fasta, biological_guard, write_json, sha256
from teflow.inputs import audit_sample, derive_cds
from teflow.formats import rm_out, union, audit_tetrimmer, export_branch, canonical_library
from teflow.runtime import run, stage_cache, finish_stage, release_lock, rm_parallel_jobs
from teflow.stages import verify_version


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, name, text):
        p = self.d / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def test_reverse_repeatmasker_boundary_and_nested_union(self):
        p = self.put("rm.out", "  SW  perc div. score\n100 1.0 0.0 0.0 s1 1 10 (90) C X DNA/hAT (0) 10 1 1\n120 2 0 0 s1 6 15 (85) + Y LTR/Gypsy 1 10 (0) 2 *\n")
        rows = rm_out(p, {"s1": 100}, {"X", "Y"})
        self.assertEqual((rows[0]["start"], rows[0]["end"], rows[0]["strand"]), (0, 10, "-"))
        self.assertEqual(union([(r["seqid"], r["start"], r["end"]) for r in rows]), [("s1", 0, 15)])
        self.assertTrue(rows[1]["overlap_flag"])

    def test_repeatmasker_rejects_ambiguous_empty_and_bad_coordinates(self):
        p = self.put("empty.out", "")
        with self.assertRaises(WorkflowError):
            rm_out(p, {}, set())
        p.write_text("There were no repetitive sequences detected\n")
        self.assertEqual(rm_out(p, {}, set()), [])
        p.write_text("100 1 0 0 s1 0 10 (90) + X Unknown 1 10 (0) 1\n")
        with self.assertRaises(WorkflowError):
            rm_out(p, {"s1": 100}, {"X"})

    def test_reference_ids_annotation_and_organelle_policy(self):
        genome = self.put("genome.fa", ">chr1\nACGTNN\n>Mt\naaaa\n")
        gff = self.put("gene.gff", "chr1\tx\tgene\t1\t6\t.\t+\t.\tID=g\n")
        s = dict(id="sample", genome=str(genome), annotation=str(gff), exclude_seqids=["Mt"])
        self.assertEqual(audit_sample(s)["selected_bp"], 6)
        gff.write_text("chr2\tx\tgene\t1\t6\t.\t+\t.\tID=g\n")
        with self.assertRaises(WorkflowError):
            audit_sample(s)
        self.put("duplicate.fa", ">x\nA\n>x\nC\n")
        with self.assertRaises(WorkflowError):
            list(fasta(self.d / "duplicate.fa"))

    def test_cds_phase_across_exons_reverse_strand_and_te_exclusion(self):
        seq = "ATG" + "CAA" * 30 + "TAA"
        split = 31
        forward = seq[:split] + "N" * 10 + seq[split:]
        comp = str.maketrans("ACGTN", "TGCAN")
        reverse = forward.translate(comp)[::-1]
        fa = self.put("g.fa", ">plus\n" + forward + "\n>minus\n" + reverse + "\n>excluded\n" + seq + "\n")
        ann = self.put("g.gff3", "plus\tx\tmRNA\t1\t106\t.\t+\t.\tID=tp;Parent=gp\n"
                       "plus\tx\tCDS\t1\t31\t.\t+\t0\tParent=tp\nplus\tx\tCDS\t42\t106\t.\t+\t2\tParent=tp\n"
                       "minus\tx\tmRNA\t1\t106\t.\t-\t.\tID=tm;Parent=gm\n"
                       "minus\tx\tCDS\t76\t106\t.\t-\t0\tParent=tm\nminus\tx\tCDS\t1\t65\t.\t-\t2\tParent=tm\n"
                       "excluded\tx\ttransposable_element_gene\t1\t96\t.\t+\t.\tID=gte\n"
                       "excluded\tx\tmRNA\t1\t96\t.\t+\t.\tID=tte;Parent=gte\nexcluded\tx\tCDS\t1\t96\t.\t+\t0\tParent=tte\n")
        result = derive_cds(ann, fa, self.d / "cds.fa")
        self.assertEqual(result["accepted_genes"], 2)
        self.assertEqual(result["transcript_processing_counts"]["annotated_TE_gene"], 1)
        self.assertEqual([s for _, s in fasta(self.d / "cds.fa")], [seq, seq])
        result = derive_cds(ann, fa, self.d / "cds2.fa", {"plus"})
        self.assertEqual(result["accepted_genes"], 1)

    def test_gtf_separate_stop_codon_is_appended_from_annotation(self):
        seq = "ATG" + "CAA" * 30 + "TAA"
        fa = self.put("stop.fa", ">p\n" + seq + "\n")
        ann = self.put("stop.gtf", 'p\tx\tCDS\t1\t93\t.\t+\t0\tgene_id "g"; transcript_id "t";\n'
                       'p\tx\tstop_codon\t94\t96\t.\t+\t0\tgene_id "g"; transcript_id "t";\n')
        q = derive_cds(ann, fa, self.d / "stop.cds.fa")
        self.assertEqual(q["accepted_genes"], 1)
        self.assertEqual(list(fasta(self.d / "stop.cds.fa"))[0][1], seq)

    def test_tetrimmer_zero_exit_is_not_completeness(self):
        lib = self.put("input.fa", ">E1#LTR/Gypsy\nACGT\n>E2#Unknown\nACGT\n")
        self.put("tt/summary.txt", "input_name,output_name,status,evaluation,low_copy\nE1,E1,processed,Good,False\n")
        self.put("tt/TEtrimmer_consensus_merged.fasta", ">E1#LTR/Gypsy\nACGT\n")
        with self.assertRaises(WorkflowError):
            audit_tetrimmer(self.d / "tt", lib)
        with (self.d / "tt/summary.txt").open("a") as f:
            f.write("E2,E2,skipped,NaN,False\n")
        self.assertEqual(audit_tetrimmer(self.d / "tt", lib)["terminal_inputs"], 2)
        self.put("tt/MSA/error_file.txt", "worker failed despite exit zero\n")
        with self.assertRaises(WorkflowError):
            audit_tetrimmer(self.d / "tt", lib)

    def test_cache_rejects_mutation_and_requires_explicit_resume(self):
        inp = self.put("in", "v1")
        folder = self.d / "stage"
        old, req = stage_cache(folder, {"x": 1}, [inp])
        self.assertIsNone(old)
        output = self.put("stage/out", "ok")
        finish_stage(folder, req, [output], {})
        release_lock(folder)
        self.assertIsNotNone(stage_cache(folder, {"x": 1}, [inp])[0])
        inp.write_text("v2")
        with self.assertRaises(WorkflowError):
            stage_cache(folder, {"x": 1}, [inp])
        f2 = self.d / "failed"
        stage_cache(f2, {}, [inp]); release_lock(f2)
        with self.assertRaises(WorkflowError):
            stage_cache(f2, {}, [inp])
        self.assertIsNone(stage_cache(f2, {}, [inp], resume=True)[0]); release_lock(f2)

    def test_process_failure_and_timeout_have_receipts(self):
        for script, timeout in (("raise SystemExit(7)", 3), ("import time; time.sleep(10)", 0.1)):
            with self.assertRaises(WorkflowError):
                run([sys.executable, "-c", script], self.d, self.d / "log", timeout)
            self.assertEqual(json.loads((self.d / "log.command.json").read_text())["status"], "failed")

    def test_no_production_on_local_and_correct_rm_budget(self):
        with self.assertRaises(WorkflowError):
            biological_guard({"execution": {"mode": "local_check"}})
        self.assertEqual(rm_parallel_jobs(32), 8)
        with self.assertRaises(WorkflowError):
            rm_parallel_jobs(2)

    def test_edta_short_banner_requires_exact_package_metadata(self):
        c = {"tools": {"edta": dict(command=["micromamba", "run", "-p", str(self.d), "EDTA.pl"], expected_version="2.3.0")}}
        banner = "##### Extensive de-novo TE Annotator (EDTA) v2.3 #####"
        with self.assertRaises(WorkflowError):
            verify_version(c, "edta", banner)
        write_json(self.d / "conda-meta/edta-2.3.0-build.json", dict(name="edta", version="2.3.0"))
        verify_version(c, "edta", banner)
        with self.assertRaises(WorkflowError):
            verify_version(c, "edta", "EDTA v2.2.0")

    def test_export_union_unknown_separation_original_coordinates(self):
        prep = self.d / "prepared"; prep.mkdir()
        self.put("prepared/genome.fa", ">s000001\nACGTACGTACGTACGTACGT\n")
        write_json(prep / "manifest.json", dict(sequences=[dict(alias="s000001", original_id="chrOriginal", length=20, included=True)]))
        lib = self.put("library.fa", ">E1#LTR/Gypsy\nACGT\n>E2#Unknown\nACGT\n")
        out = self.put("genome.out", "SW score\n100 1 0 0 s000001 1 4 (16) C E1 LTR/Gypsy (0) 4 1 1\n100 1 0 0 s000001 8 10 (10) + E2 Unknown 1 3 (0) 2\n")
        q = export_branch(prep, lib, out, self.d / "export", "edta")
        self.assertEqual(q["repeat_mask_bp"], 4)
        self.assertEqual((self.d / "export/te.mask.bed").read_text(), "chrOriginal\t0\t4\n")
        self.assertEqual(list(fasta(self.d / "export/genome.softmasked.fa")), [("chrOriginal", "acgtACGTACGTACGTACGT")])
        self.assertEqual(q["union_bp"]["unknown"], 3)


if __name__ == "__main__":
    unittest.main()
