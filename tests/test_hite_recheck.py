import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from teflow.common import WorkflowError, read_json, write_json, sha256
from teflow.hite_image import identity_for_digest, inspect_image, ZENODO_SHA256, ZENODO_SIZE
from teflow.cli import configure_v2
from teflow.stages import verify_version, _doctor_attempt
from teflow.upstream_probe import probe_ninja
from teflow.adapters.discovery import run_hite

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("prepare_hite_recheck", REPO / "scripts/prepare_hite_recheck.py")
recheck = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recheck)


class HiTERecheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()

    def tearDown(self):
        self.temp.cleanup()

    def identity(self):
        return identity_for_digest(self.root / "image.sif", ZENODO_SIZE, ZENODO_SHA256)

    def config(self):
        root = self.root
        hite = ["micromamba", "run", "-p", str(root / "envs/engine"), "python",
                str(root / "old_repo/scripts/run_hite_container.py"), "--image", str(root / "image.sif"),
                "--bind", str(root), "--"]
        return dict(schema_version=2, run_id="old", work_root=str(root / "work"),
                    results_root=str(root / "results"), samples=[dict(id="sample",genome=str(root / "genome.fa"))],
                    branches=dict(hite=dict(enabled=True,parameters=dict(min_TE_len=100))),
                    execution=dict(mode="server",threads=32,mem_mb=131072), parameters=dict(max_divergence=40),
                    databases=dict(files=[]), qc=dict(pfam=False), evaluation=dict(widths=[6,20]),
                    tools=dict(hite=dict(command=hite,expected_version="3.3.3",image=str(root / "image.sif")),
                               repeatmasker=dict(command=["RepeatMasker"],expected_version="4.2.4"),
                               trf=dict(command=["trf"],expected_version="4.10.0"),
                               dustmasker=dict(command=["dustmasker"],expected_version="2.17.0")))

    def test_known_profile_requires_both_exact_size_and_digest(self):
        profile = self.identity()
        self.assertEqual((profile["release_label"],profile["reported_version"]),("3.3.3","3.3.2"))
        self.assertFalse(identity_for_digest("image.sif",ZENODO_SIZE,"0"*64)["recognized"])
        self.assertFalse(identity_for_digest("image.sif",1,ZENODO_SHA256)["recognized"])
        p = self.root / "image.sif"; p.write_bytes(b"different image")
        with self.assertRaises(WorkflowError): inspect_image(p,require_known=True)

    def test_configure_records_exact_image_identity_without_global_version_downgrade(self):
        image = self.root / "image.sif"; image.write_bytes(b"test")
        for profile, expected in ((self.identity(),"3.3.2"),(dict(recognized=False),"3.3.3")):
            c = self.config()
            with patch("teflow.hite_image.inspect_image",return_value=profile):
                configure_v2(c,self.root / "envs","micromamba",image=str(image))
            self.assertEqual(c["tools"]["hite"]["expected_version"],expected)
            self.assertEqual(c["tools"]["hite"]["image_identity"],profile)
        with self.assertRaises(WorkflowError):
            verify_version(self.config(),"hite","HiTE, version 3.3.2")

    def test_new_run_preserves_frozen_old_files_and_custom_branch_settings(self):
        original = self.config(); src=self.root / "old.json"; dst=self.root / "new.json"
        write_json(src,original)
        manifest=self.root / "work/old/run_manifest.json"; write_json(manifest,dict(fingerprint="preserved"))
        before = (sha256(src),sha256(manifest))
        with patch.object(recheck,"inspect_image",return_value=self.identity()):
            recheck.prepare(src,dst,"new")
        c=read_json(dst)
        self.assertEqual((sha256(src),sha256(manifest)),before)
        self.assertEqual(c["tools"]["hite"]["expected_version"],"3.3.2")
        self.assertIn(str(REPO / "scripts/run_hite_container.py"),c["tools"]["hite"]["command"])
        self.assertEqual(c["tools"]["hite"]["probe_command"],c["tools"]["hite"]["command"]+["--teflow-probe"])
        for field in ("branches","qc","evaluation","databases","execution","samples"):
            self.assertEqual(c[field],original[field])
        self.assertFalse((self.root / "work/new").exists())

    def test_recheck_refuses_existing_outputs_and_run_directories(self):
        src=self.root / "old.json"; dst=self.root / "new.json"; write_json(src,self.config())
        with patch.object(recheck,"inspect_image",return_value=self.identity()):
            with self.assertRaises(WorkflowError): recheck.prepare(src,dst,"old")
            (self.root / "work/new").mkdir(parents=True)
            with self.assertRaises(WorkflowError): recheck.prepare(src,dst,"new")
            dst.write_text("preserved")
            with self.assertRaises(WorkflowError): recheck.prepare(src,dst,"unused")
        self.assertEqual(dst.read_text(),"preserved")

    def test_ninja_probe_uses_clustering_binary_and_rejects_partial_results(self):
        seen=[]
        def run(args,cwd):
            seen.append(args)
            (Path(cwd)/"ninja.clusters.tsv").write_text("0\tprobe_a\n0\tprobe_b\n0\tprobe_c\n")
        probe_ninja(self.root,run)
        self.assertEqual(seen[0][0],"Ninja")
        self.assertEqual(seen[0][-2:],["--threads","1"])
        def bad(args,cwd):
            (Path(cwd)/"ninja.clusters.tsv").write_text("0\tprobe_a\n")
        with self.assertRaises(RuntimeError): probe_ninja(self.root,bad)

    def test_dependency_failure_cause_is_retained_in_doctor_json(self):
        c=dict(execution=dict(mode="server"),tools=dict(hite=dict(command=["fake"],
               probe_command=["fake","probe"],expected_version="3.3.2")))
        def run(argv,cwd,log,*args,**kwargs):
            if argv==["fake","probe"]:
                Path(log).write_text('warning\n{"status":"fail","error":"Missing dependency: Ninja"}\n')
                raise WorkflowError("Command exited 2")
            return "HiTE, version 3.3.2"
        with patch("teflow.stages.run",side_effect=run):
            with self.assertRaises(WorkflowError): _doctor_attempt(c,self.root,True)
        failed=read_json(self.root/"doctor.json")["checks"][-1]
        self.assertEqual(failed["probe_error"],"Missing dependency: Ninja")
        self.assertEqual(failed["status"],"fail")

    def test_hite_library_uses_cli_version_and_separate_image_identity(self):
        c=self.config(); c["tools"]["hite"].update(expected_version="3.3.2",image_identity=self.identity())
        base=self.root/"base"; (base/"prepared").mkdir(parents=True)
        (base/"prepared/genome.fa").write_text(">chr\nACGTACGTACGT\n")
        folder=base/"hite"; folder.mkdir()
        def call(tool,args,name):
            raw=Path(args[args.index("--out_dir")+1]); raw.mkdir()
            (raw/"confident_TE.cons.fa").write_text(">test#DNA/hAT\nACGTACGTACGT\n")
            (folder/(name+".log")).write_text("ok\n")
        details,outputs=run_hite(c,base,folder,1,call,False)
        self.assertEqual(details["software_identity"]["cli_version"],"3.3.2")
        self.assertEqual(details["software_identity"]["image_identity"]["release_label"],"3.3.3")
        self.assertIn("HiTE-CLI-3.3.2",(folder/"library.fa.provenance.tsv").read_text())

    def test_taxon_flag_is_explicit_and_legacy_defaults_plant(self):
        c=self.config()
        base=self.root/'base'; (base/'prepared').mkdir(parents=True)
        (base/'prepared/genome.fa').write_text('>chr\nACGTACGTACGT\n')
        for taxon,expected in ((None,1),('plant',1),('metazoa',0),('fungi',0),('other',0)):
            s=dict(c['samples'][0])
            if taxon: s['taxon_group']=taxon
            folder=base/str(taxon);folder.mkdir()
            seen=[]
            def call(tool,args,name):
                seen.append(args[args.index('--plant')+1])
                raw=Path(args[args.index('--out_dir')+1]);raw.mkdir()
                (raw/'confident_TE.cons.fa').write_text('>x#DNA/hAT\nACGT\n')
                (folder/(name+'.log')).write_text('ok\n')
            run_hite(c,base,folder,1,call,False,s)
            self.assertEqual(seen,[expected])


if __name__ == "__main__": unittest.main()
