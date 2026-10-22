import copy
import hashlib
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from teflow.common import WorkflowError, read_json, write_json, fasta, load_config, table
from teflow.formats import tier, standard_class, canonical_library
from teflow.branches import validate, required_tools, graph
from teflow.adapters.discovery import heliano_native, audit_logs, run_heliano
from teflow.library_qc import combine_libraries, host_proteins, revcomp, library_qc
from teflow.evaluation import intersect, subtract, bp, scopes, branch_evaluation, tsv
from teflow.runtime import process_identity, group_alive
from teflow.stages import doctor


class V02Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.d = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def put(self, name, text):
        p = self.d / name; p.parent.mkdir(exist_ok=True, parents=True)
        p.write_text(text, encoding="utf-8"); return p

    def test_mite_unknown_and_unrecognized_are_distinct(self):
        for cls in ("MITE/DTA", "DNA/hAT", "DNA?/hAT?", "RC/Helitron", "LINE/L1"):
            self.assertEqual(tier(cls), "te")
        self.assertEqual(standard_class("MITE/DTA"), "TIR_MITE")
        self.assertEqual(tier("Unknown"), "unknown")
        with self.assertRaises(WorkflowError): tier("novel_typo")

    def test_conditional_graph_does_not_require_disabled_tools(self):
        c = dict(schema_version=2, branches={"hite": {"enabled": True}}, samples=[{}])
        validate(c)
        self.assertEqual(required_tools(c), {"hite", "repeatmasker", "trf", "dustmasker"})
        self.assertNotIn("edta", graph(c))
        c["branches"] = {"heliano": {"enabled": True}}
        with self.assertRaises(WorkflowError): validate(c)
        c["branches"] = {"reference_only": {"enabled": True}}
        with self.assertRaises(WorkflowError): validate(c)
        c["samples"][0]["reference_library"] = "ref.fa"; validate(c)

    def test_native_heliano_one_based_strand_roundtrip_and_terminal_contract(self):
        seq = "ATGCGTAACTGA"
        genome = self.put("genome.fa", ">chr\n" + seq + "\n")
        self.put("raw/RC.representative.fa", ">plus\nATGC\n>minus\n" + revcomp(seq[4:9]) + "\n")
        row = "chr\t1\t4\tSF1\t2\t+\t1e-5\t100\tHLE1\tnonauto\tplus\nchr\t5\t9\tSF2\t1\t-\t1e-6\t90\tHLE2\tauto\tminus\n"
        self.put("raw/RC.representative.bed", row)
        self.put("raw/pairlist.tbl", "terminal\n")
        result = heliano_native(self.d / "raw", genome, self.d / "sites.tsv")
        self.assertEqual((result[0]["start"], result[1]["end"]), (0, 9))
        (self.d / "raw/pairlist.tbl").unlink()
        with self.assertRaises(WorkflowError): heliano_native(self.d / "raw", genome, self.d / "sites.tsv")
        self.put("raw/pairlist.tbl", "terminal\n")
        self.put("raw/RC.representative.bed", row.replace("\t1\t4\t", "\t2\t4\t"))
        with self.assertRaises(WorkflowError): heliano_native(self.d / "raw", genome, self.d / "sites.tsv")

    def test_heliano_verified_empty_and_log_error(self):
        genome = self.put("g.fa", ">chr\nACGT\n")
        for f in ("RC.representative.fa", "RC.representative.bed", "pairlist.tbl"):
            self.put("raw/" + f, "")
        self.assertEqual(heliano_native(self.d / "raw", genome, self.d / "sites.tsv"), [])
        p = self.put("worker.log", "normal\nERROR: async worker failed\n")
        with self.assertRaises(WorkflowError): audit_logs([p])

    def test_sequence_assembly_only_exact_rc_same_class(self):
        a = self.put("a.fa", ">E1#DNA/hAT\nATGCC\n>E2#Unknown\nATGCC\n")
        b = self.put("b.fa", ">H1#DNA/hAT\nGGCAT\n>H2#DNA/hAT\nATGCA\n")
        output = self.d / "merged.fa"
        self.assertEqual(combine_libraries([("edta", a), ("heliano", b)], output, "EH"), 3)
        rows = tsv(str(output) + ".parents.tsv")
        self.assertEqual(rows[0]["family_id"], rows[2]["family_id"])
        self.assertNotEqual(rows[0]["family_id"], rows[1]["family_id"])

    def test_non_hle_cleanup_preserves_positions_and_rehashes_masked_sequence(self):
        self.put("base/prepared/genome.fa", ">chr\nATGCGTAACTGA\n")
        self.put("base/edta/library.fa", ">E1#DNA/hAT\nACTG\n>E2#RC/Helitron\nACTG\n>E3#Unknown\nACTG\n")
        table(self.d / "base/qc_edta/library_qc.tsv", [dict(family_id="E" + str(i), host_protein_hits=0, flags="") for i in range(1,4)], ["family_id", "host_protein_hits", "flags"])
        folder = self.d / "base/heliano"; folder.mkdir()
        def call(tool, args, name):
            (folder / (name + ".log")).write_text("ok\n")
            if tool == "heliano":
                raw = Path(args[args.index("-o")+1]); raw.mkdir()
                (raw / "RC.representative.bed").write_text("chr\t1\t12\tSF\t1\t+\t1e-6\t100\tHLE1\tauto\tH1\n")
                (raw / "RC.representative.fa").write_text(">H1\nATGCGTAACTGA\n")
                (raw / "pairlist.tbl").write_text("done\n")
            else:
                (folder / "candidates.fa.out").write_text("SW score\n100 0 0 0 H0000001#RC/Helitron 3 5 (7) + E1 DNA/hAT 1 3 (1) 1\n")
        c = dict(branches={}, parameters=dict(max_divergence=40))
        run_heliano(c, self.d / "base", folder, 4, call, False)
        seq = next(fasta(folder / "library.fa"))[1]
        self.assertEqual(seq, "ATNNNTAACTGA")
        row = tsv(folder / "library.fa.provenance.tsv")[0]
        self.assertEqual(row["sequence_sha256"], hashlib.sha256(seq.encode()).hexdigest())
        self.assertNotEqual(row["sequence_sha256"], row["raw_sequence_sha256"])
        self.assertEqual(len(list(fasta(folder / "non_hle.fa"))), 1)
        # A failed-stage retry can regenerate all derived products without deleting prior raw evidence.
        run_heliano(c, self.d / "base", folder, 4, call, True)
        self.assertTrue((folder / "raw.attempt001").is_dir())

    def test_interval_union_and_difference_have_set_semantics(self):
        a = [("c",0,10), ("c",5,20)]; b = [("c",7,13), ("d",0,99)]
        self.assertEqual(bp(a), 20)
        self.assertEqual(intersect(a,b), [("c",7,13)])
        self.assertEqual(subtract(a,b), [("c",0,7),("c",13,20)])
        self.assertEqual(bp(subtract(a,b)) + bp(intersect(a,b)), bp(a))

    def test_promoter_neighbor_clipping_both_strands(self):
        g = self.put("genes.gff", "c\tx\tgene\t101\t150\t.\t+\t.\tID=a\nc\tx\tgene\t151\t200\t.\t+\t.\tID=b\nc\tx\tgene\t300\t350\t.\t-\t.\tID=c\nc\tx\tgene\t401\t450\t.\t+\t.\tID=d\n")
        manifest = dict(sequences=[dict(original_id="c", included=True, length=500)])
        areas, windows, mode = scopes(dict(annotation=g), manifest, dict(promoter_upstream=200,promoter_near=20))
        byid = {r["gene_id"]:r for r in windows}
        self.assertEqual((byid["b"]["start"],byid["b"]["end"]), (150,150))
        self.assertEqual((byid["c"]["start"],byid["c"]["end"]), (350,400))
        self.assertIn("provisional", mode)

    def test_opportunities_honor_N_masks_and_short_empty_windows(self):
        prep = self.d / "prep"; out = self.d / "out"; prep.mkdir(); out.mkdir()
        write_json(prep / "manifest.json", dict(sequences=[dict(alias="s1",original_id="c",included=True,length=10)]))
        (prep / "genome.fa").write_text(">s1\nAACGNACGTA\n")
        promoters = self.put("prom.bed", "c\t0\t10\tg\t0\t+\nc\t0\t0\tempty\t0\t-\n")
        lib = self.put("lib.fa", ">E1#MITE/DTA\nAACG\n")
        table(out / "mask_sources.tsv", [dict(seqid="c",start=0,end=2,family_id="E1",classification="MITE/DTA")], ["seqid","start","end","family_id","classification"])
        for name, text in (("te.mask.bed","c\t0\t2\n"),("repeat_unknown.bed",""),("tandem_repeat.bed",""),("low_complexity.bed","")):
            (out / name).write_text(text)
        q = branch_evaluation(dict(evaluation=dict(widths=[4])), dict(promoters_bed=str(promoters)), prep, out, lib)
        rows = {(r["gene_id"],r["policy"]):r for r in tsv(out / "promoter_opportunities.tsv")}
        self.assertEqual(rows["g","M0"]["valid_windows_w4"], "3")
        self.assertEqual(rows["g","M1_TE"]["valid_windows_w4"], "2")
        self.assertEqual(rows["empty","M0"]["valid_windows_w4"], "0")
        self.assertEqual(q["reference"]["status"], "not_provided")

    def test_doctor_failure_does_not_poison_successful_retry(self):
        import teflow.stages as st
        out = self.d / "doctor"
        def failure(c, dest, dependencies):
            write_json(dest / "doctor.json",dict(status="fail")); raise WorkflowError("fixture failure")
        with patch.object(st,"_doctor_attempt",side_effect=failure):
            with self.assertRaises(WorkflowError): doctor({},out)
        self.assertFalse((out / "doctor.json").exists())
        def success(c,dest,dependencies):
            result = dict(status="pass"); write_json(dest / "doctor.json",result); return result
        with patch.object(st,"_doctor_attempt",side_effect=success):
            doctor({},out); content = (out / "doctor.json").read_bytes(); doctor({},out)
        self.assertEqual(len(list((out / "attempts").glob("*/doctor.json"))),3)
        self.assertEqual((out / "doctor.json").read_bytes(),content)

    def test_host_translation_rejects_non_coding_or_internal_stop(self):
        cds = self.put("cds.fa", ">x\nATGGCTTAA\n")
        self.assertEqual(host_proteins(cds,self.d / "p.fa"),1)
        self.assertIn("MA", (self.d / "p.fa").read_text())
        cds.write_text(">x\nATGTAAGCT\n")
        with self.assertRaises(WorkflowError): host_proteins(cds,self.d / "p.fa")

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux process-group contract")
    def test_dead_pid_keeps_boot_identity(self):
        identity = process_identity(99999999)
        self.assertTrue(identity.get("boot_id")); self.assertNotIn("start_ticks",identity)

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux stale-lock contract")
    def test_unlock_refuses_live_or_unverifiable_owner_and_removes_proven_stale(self):
        from teflow.migration import unlock_stage
        c=dict(schema_version=2,branches={"hite":dict(enabled=True)},work_root=str(self.d),run_id="run")
        folder=self.d / "run/s/hite"; lock=folder / ".lock"; lock.mkdir(parents=True)
        owner=process_identity(os.getpid()); write_json(lock / "owner.json",owner)
        with patch("teflow.migration.check_frozen",return_value=None):
            with self.assertRaises(WorkflowError): unlock_stage(c,"s","hite")
            write_json(lock / "owner.json",dict(pid=99999999,host=owner["host"]))
            with self.assertRaises(WorkflowError): unlock_stage(c,"s","hite")
            write_json(lock / "owner.json",dict(owner,pid=99999999,start_ticks="1"))
            self.assertEqual(unlock_stage(c,"s","hite")["status"],"stale_lock_removed")
        self.assertFalse(lock.exists())

    def test_invalid_qc_and_evaluation_settings_are_rejected(self):
        c=dict(schema_version=2,branches={"hite":dict(enabled=True)},samples=[{}])
        for setting in (dict(qc=None),dict(qc=dict(evalue="typo")),dict(evaluation=dict(reference_features="gene")),dict(evaluation=dict(widths=[6,"20"]))):
            with self.assertRaises(WorkflowError): validate(dict(c,**setting))

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux process-group contract")
    def test_term_and_hup_remove_descendants(self):
        for sig in (signal.SIGTERM, signal.SIGHUP):
            folder = self.d / str(sig); folder.mkdir()
            runner = folder / "runner.py"
            runner.write_text("from teflow.runtime import run\nimport sys\nrun([sys.executable,'-c',\"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c','import time; time.sleep(120)']); time.sleep(120)\"],sys.argv[1],sys.argv[1]+'/run.log')\n")
            p = subprocess.Popen([sys.executable,str(runner),str(folder)], stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            receipt = folder / "run.log.command.json"
            try:
                deadline = time.monotonic()+10
                while time.monotonic()<deadline:
                    if receipt.exists() and read_json(receipt).get("pid"): break
                    time.sleep(.05)
                self.assertTrue(receipt.exists()); time.sleep(.15)
                p.send_signal(sig); p.wait(timeout=10)
                r = read_json(receipt)
                self.assertEqual(r["status"],"interrupted")
                self.assertFalse(group_alive(r))
            finally:
                if p.poll() is None: p.kill(); p.wait()


if __name__ == "__main__": unittest.main()
