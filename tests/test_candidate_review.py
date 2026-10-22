import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from teflow.common import WorkflowError, digest, read_json, sha256, table, write_json
from teflow.candidate_review import (prepare_review, review_plan, run_review, export_decisions, pack_review,
                                    parse_hsps, verify_review, from_workflow)
from teflow.repeat_alignments import Genome, iter_alignments, link_final, project_spans
from teflow.review_context import annotation_models, native_loci
from teflow.library_qc import revcomp
from teflow.evaluation import branch_evaluation, tsv
from teflow.alignment_artifacts import locate_alignment
from teflow.runtime import config_fingerprint


class CandidateReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.d = Path(self.tmp.name)
        self.dna = "ATGGCTGTTCAG"
        self.genome = self.put("genome.fa", ">chr\n" + self.dna + "ACGTTT\n")
        self.lib = self.put("library.fa", ">F1#DNA/hAT\n" + self.dna + "\n")
        self.align = self.put("genome.fa.align", "100 0.0 0.0 0.0 chr 1 12 (6) F1#DNA/hAT 1 12 (0) raw1 1\n"
                              "chr 1 " + self.dna + " 12\nF1#DNA 1 " + self.dna + " 12\n")
        self.out = self.put("genome.fa.out", "SW score\n100 0 0 0 chr 1 12 (6) + F1 DNA/hAT 1 12 (0) 1\n")
        self.annotation = self.put("genes.gff3", "chr\tref\tgene\t1\t12\t.\t+\t.\tID=g1\n"
             "chr\tref\tmRNA\t1\t12\t.\t+\t.\tID=t1;Parent=g1\n"
             "chr\tref\texon\t1\t12\t.\t+\t.\tParent=t1\nchr\tref\tCDS\t1\t12\t.\t+\t0\tParent=t1\n")
        self.protein = self.put("host.faa", ">g1\nMAVQ\n")
        self.families = self.put("families.txt", "F1\n")
        self.paths = dict(genome=self.genome, library=self.lib, rm_out=self.out, rm_align=self.align,
                          annotation=self.annotation, host_proteins=self.protein)
        self.fake = self.put("fake_diamond.py", "import sys\nfrom pathlib import Path\na=sys.argv[1:]\n"
            "if a[0]=='version': print('diamond version 2.1.11')\n"
            "elif a[0]=='makedb': Path(a[a.index('--db')+1]+'.dmnd').write_text('fixture')\n"
            "else: Path(a[a.index('--out')+1]).write_text('F1#DNA/hAT\\tg1\\t100\\t4\\t1e-10\\t50\\t1\\t12\\t1\\t4\\t1\\t4\\t12\\t4\\n')\n")
        self.tool = dict(command=[sys.executable, str(self.fake)], expected_version="2.1.11")

    def tearDown(self): self.tmp.cleanup()

    def put(self, name, text):
        p = self.d / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text, encoding="utf-8"); return p

    def prepare(self, name="review", paths=None):
        prepare_review(paths or self.paths, self.d / name, self.families, tool=self.tool, max_loci=2, flank=5)
        return self.d / name

    def test_plus_minus_and_gap_column_projection(self):
        plus = list(iter_alignments(self.align, Genome(self.genome), {"F1": self.dna}))[0]
        self.assertEqual(project_spans(plus, [(3, 6)]), ([("chr", 3, 6)], []))
        self.genome.write_text(">chr\n" + revcomp(self.dna) + "ACGTTT\n")
        self.align.write_text("100 0 0 0 chr 1 12 (6) C F1#DNA/hAT (0) 12 1 raw1 1\n"
                             "chr 1 " + revcomp(self.dna) + " 12\nC F1#DNA 12 " + revcomp(self.dna) + " 1\n")
        minus = list(iter_alignments(self.align, Genome(self.genome), {"F1": self.dna}))[0]
        self.assertEqual(project_spans(minus, [(0, 3)]), ([("chr", 9, 12)], []))
        # Each side has an insertion: query G at 2 has no library base;
        # library G at 2 has no query base and cannot contribute a genomic bp.
        self.genome.write_text(">chr\nACGT\n")
        self.align.write_text("100 0 0 0 chr 1 4 (0) F1#DNA/hAT 1 4 (0) raw1 1\n"
                             "chr 1 ACG-T 4\nF1#DNA 1 AC-GT 4\n")
        block = list(iter_alignments(self.align, Genome(self.genome), {"F1": "ACGT"}))[0]
        self.assertEqual(project_spans(block, [(0, 4)]), ([("chr", 0, 2), ("chr", 3, 4)], [("chr", 2, 3)]))

    def test_invalid_sequence_and_coordinates_stop(self):
        self.genome.write_text(">chr\nTTGGCTGTTCAGACGTTT\n")
        with self.assertRaisesRegex(WorkflowError, "genome sequence mismatch"):
            list(iter_alignments(self.align, Genome(self.genome), {"F1": self.dna}))
        self.genome.write_text(">chr\n" + self.dna + "ACGTTT\n")
        self.align.write_text(self.align.read_text().replace("(6)", "(7)"))
        with self.assertRaises(WorkflowError): list(iter_alignments(self.align, Genome(self.genome), {"F1": self.dna}))

    def test_original_numeric_chromosome_and_variable_fasta_lines(self):
        self.genome.write_text(">1 description\nATG\nGCTGTT\nCAGACGTTT\n")
        self.align.write_text(self.align.read_text().replace("chr", "1"))
        block = list(iter_alignments(self.align, Genome(self.genome), {"F1": self.dna}))[0]
        self.assertEqual((block["seqid"], block["qseq"]), ("1", self.dna))

    def test_final_name_never_replaces_mixed_raw_families(self):
        common = dict(seqid="chr", strand="+", upstream_group="1")
        blocks = [dict(common, alignment_id="a", family_id="X", start=0, end=7),
                  dict(common, alignment_id="b", family_id="Y", start=5, end=12)]
        records = [dict(common, fragment_id="f", family_id="X", start=0, end=13)]
        row = list(link_final(records, blocks))[0]
        self.assertEqual((row["raw_families"], row["status"], row["uncovered_bp"]), ("X;Y", "uncovered_or_partial", 1))
        records[0]["end"] = 12
        self.assertEqual(list(link_final(records, blocks))[0]["status"], "mixed_raw_families")

    def test_prepare_qc_export_pack_and_no_reexecution(self):
        root = self.prepare(); before = sha256(self.genome)
        plan = review_plan(root, 1)
        self.assertFalse((root / "protein_qc").exists()); self.assertFalse(plan["computation_launched"])
        result = run_review(root, 1, 30)
        self.assertEqual(result["summary"]["reported_HSPs"], 1)
        self.assertEqual(tsv(root / "protein_qc/raw_alignment_projection.tsv")[0]["paired_reported_protein_span_bp"], "12")
        self.assertEqual(sha256(self.genome), before)
        with self.assertRaisesRegex(WorkflowError, "directory exists"): run_review(root, 1)
        pending = export_decisions(root, root / "decisions.template.tsv", self.d / "pending")
        self.assertEqual(pending["counts"]["mask_library.fa"], 0)
        choices = tsv(root / "decisions.template.tsv")
        choices[0].update(biological_status="gene_capture_candidate", catalog_action="retain", masking_action="exclude",
                          reviewer="test", reviewed_at="2026-10-15", evidence="synthetic check", reason="Keep catalog, defer mask")
        path = self.d / "decisions.tsv"; table(path, choices, list(choices[0]))
        result = export_decisions(root, path, self.d / "curated")
        self.assertEqual(result["counts"], {"catalog.fa": 1, "mask_library.fa": 0})
        pack = pack_review(root, self.d / "review.tar.gz")
        self.assertEqual(pack["omitted"], ["protein_qc/host.db.dmnd"])
        self.assertFalse(Path(pack["archive"] + ".sha256").exists())

    def test_immutable_evidence_and_missing_review_reason(self):
        root = self.prepare()
        choices = tsv(root / "decisions.template.tsv"); choices[0]["masking_action"] = "include"
        path = self.d / "decisions.tsv"; table(path, choices, list(choices[0]))
        with self.assertRaisesRegex(WorkflowError, "decision needs"): export_decisions(root, path, self.d / "reject")
        self.genome.write_text(self.genome.read_text().replace("ATG", "TTG", 1))
        with self.assertRaisesRegex(WorkflowError, "input changed"): review_plan(root)
        # Feedback remains possible after original inputs move or become unavailable.
        pack_review(root, self.d / "evidence.tar.gz")
        (root / "candidates.fa").write_text(">altered\nACGT\n")
        with self.assertRaisesRegex(WorkflowError, "evidence changed"): pack_review(root, self.d / "bad.tar.gz")

    def test_failure_receipt_is_preserved_without_complete(self):
        self.fake.write_text("raise SystemExit(3)\n")
        root = self.prepare()
        with self.assertRaises(WorkflowError): run_review(root, 1, 30)
        self.assertTrue((root / "protein_qc/failed.json").exists())
        self.assertFalse((root / "protein_qc/complete.json").exists())
        with self.assertRaisesRegex(WorkflowError, "directory exists"): run_review(root, 1)
        pack_review(root, self.d / "failed.tar.gz")

    def test_no_annotation_is_explicit_not_zero_risk(self):
        paths = dict(self.paths); del paths["annotation"]
        root = self.prepare(paths=paths)
        row = tsv(root / "loci.tsv")[0]
        self.assertEqual(row["annotation_status"], "not_provided")
        self.assertEqual(row["overlapping_CDS_union_bp"], "")

    def test_no_protein_hits_are_not_negative_labels(self):
        self.fake.write_text(self.fake.read_text().replace("F1#DNA/hAT\\tg1\\t100\\t4\\t1e-10\\t50\\t1\\t12\\t1\\t4\\t1\\t4\\t12\\t4\\n", ""))
        root = self.prepare(); run_review(root, 1, 30)
        self.assertEqual(tsv(root / "protein_qc/family_protein_evidence.tsv")[0]["evidence_status"], "no_reported_hit_not_negative_truth")

    def test_native_rc_alias_and_no_informative_sequence(self):
        path = self.d / "native.tsv"
        table(path, [dict(family_id="F1", seqid="chr", start=0, end=12, strand="+")],
              ["family_id", "seqid", "start", "end", "strand"])
        rows = native_loci(dict(native_loci=path), ["F1"], {"F1": revcomp(self.dna)}, Genome(self.genome), {})
        self.assertEqual(rows[0]["source"], "verified_native_representative")
        with self.assertRaisesRegex(WorkflowError, "no non-N"):
            native_loci(dict(native_loci=path), ["F1"], {"F1": "N"*12}, Genome(self.genome), {})

    def test_gff_parents_and_gtf_isoforms(self):
        model = annotation_models(self.annotation, Genome(self.genome))
        self.assertEqual(model["transcripts"][("g1", "t1")], [("chr", 0, 12)])
        gtf = self.put("gene.gtf", 'chr\tr\tCDS\t1\t6\t.\t+\t0\tgene_id "g"; transcript_id "a";\n'
                       'chr\tr\tCDS\t10\t12\t.\t+\t0\tgene_id "g"; transcript_id "a";\n'
                       'chr\tr\tCDS\t4\t12\t.\t+\t0\tgene_id "g"; transcript_id "b";\n')
        model = annotation_models(gtf, Genome(self.genome))
        self.assertEqual(model["cds"]["g"], [("chr", 0, 12)])
        self.assertEqual(len(model["transcripts"]), 2)

    def test_btop_gap_reverse_and_malformed_consumption(self):
        p = self.put("hits.tsv", "F1\tg\t75\t5\t1e-8\t40\t12\t1\t2\t5\t-1\t1A-1-G1\t12\t8\n")
        rows, _, _ = parse_hsps(p, {"F1": self.dna}, 1e-5)
        self.assertEqual(rows[0]["start"], 0)
        p.write_text(p.read_text().replace("1A-1-G1", "1A-2-G1"))
        with self.assertRaisesRegex(WorkflowError, "BTOP coordinate consumption"): parse_hsps(p, {"F1": self.dna}, 1e-5)

    def test_legacy_alignment_resolver_matches_out_and_command(self):
        imported = self.d / "imported"; original = self.d / "original"
        imported.mkdir(); original.mkdir()
        for p in (imported, original):
            shutil.copyfile(self.out, p / "genome.fa.out")
            write_json(p / "run.log.command.json", dict(argv=["RepeatMasker", "-a"], cwd=str(original), returncode=0))
        shutil.copyfile(self.align, original / "genome.fa.align")
        before = sha256(original / "genome.fa.align")
        result = locate_alignment(imported)
        self.assertEqual(result["sha256"], before); self.assertFalse(result["receipt_locked"])
        (original / "genome.fa.out").write_text("changed")
        with self.assertRaisesRegex(WorkflowError, "does not match"): locate_alignment(imported)

    def test_source_config_mode_requires_valid_receipts_but_not_new_source_fingerprint(self):
        root = self.d / "work/old/s"; prep = root / "prepared"; prep.mkdir(parents=True)
        shutil.copyfile(self.genome, prep / "genome.fa")
        write_json(prep / "manifest.json", dict(sequences=[dict(alias="chr", original_id="chr", length=18, included=True)],
                   outputs={"genome.fa": sha256(prep / "genome.fa")}))
        for stage, files in (("edta", [self.lib]), ("rm_edta", [self.out, self.align])):
            folder = root / stage; folder.mkdir()
            for p in files: shutil.copyfile(p, folder / p.name)
            material = dict(old_source="intentionally_not_current")
            write_json(folder / "complete.json", dict(status="complete", material=material, fingerprint=digest(material),
                       outputs={str(folder / p.name): sha256(folder / p.name) for p in files}))
        c = dict(schema_version=1, run_id="old", work_root=str(self.d / "work"), samples=[dict(id="s", genome=str(self.genome))],
                 tools={"diamond": self.tool}, qc={"host_proteins": str(self.protein)}, _config_path=str(self.put("old.json", "{}")))
        material = dict(config_sha256=config_fingerprint(c), inputs={"s": {"genome": sha256(self.genome)}})
        write_json(root.parent / "run_manifest.json", dict(material=material, fingerprint=digest(material)))
        paths, provenance, tool = from_workflow(c, "s", "edta")
        self.assertEqual(provenance["origin"], "verified_completed_workflow")
        self.assertTrue(provenance["alignment_source"]["receipt_locked"])
        (root / "edta/library.fa").write_text(">changed\nACGT\n")
        with self.assertRaisesRegex(WorkflowError, "output changed"): from_workflow(c, "s", "edta")

    def test_disabled_promoters_still_report_gene_context(self):
        prep = self.d / "prepared"; prep.mkdir(); dest = self.d / "export"; dest.mkdir()
        write_json(prep / "manifest.json", dict(sequences=[dict(original_id="chr", alias="chr", length=18, included=True)]))
        table(dest / "mask_sources.tsv", [dict(seqid="chr", start=0, end=12, family_id="F1", classification="DNA/hAT")],
              ["seqid", "start", "end", "family_id", "classification"])
        result = branch_evaluation(dict(evaluation=dict(promoter_analysis=False)), dict(annotation=str(self.annotation)), prep, dest, self.lib)
        self.assertFalse(result["promoter_analysis"])
        self.assertFalse((dest / "promoters.tsv").exists()); self.assertFalse((dest / "promoter_opportunities.tsv").exists())
        self.assertEqual(next(r for r in tsv(dest / "gene_context_coverage.tsv") if r["region"] == "CDS")["TE_overlap_bp"], "12")


if __name__ == "__main__": unittest.main()
