import importlib.util
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from teflow.common import WorkflowError, sha256, table, write_json, read_json
from teflow.delivery import retention_summary, select
from teflow.formats import canonical_library
from teflow.publishing import atomic_directory
from teflow.resources import cpu_affinity_plan


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.c = dict(work_root=str(self.root/'work'), results_root=str(self.root/'results'), run_id='r',
                      samples=[dict(id='s')], schema_version=2, branches=dict(edta=dict(enabled=True)))
        self.out = self.root/'results/r/s'

    def tearDown(self): self.tmp.cleanup()

    def test_directory_failure_does_not_publish_truncated_output(self):
        dest = self.root/'export'
        with self.assertRaisesRegex(RuntimeError, 'injected'):
            with atomic_directory(dest) as pending:
                (pending/'genome.fa').write_text('partial')
                raise RuntimeError('injected')
        self.assertFalse(dest.exists())
        with atomic_directory(dest) as pending:
            (pending/'genome.fa').write_text('complete')
        with self.assertRaises(RuntimeError):
            with atomic_directory(dest, replace=True) as pending:
                raise RuntimeError('injected replacement')
        self.assertEqual((dest/'genome.fa').read_text(), 'complete')
        with self.assertRaises(WorkflowError):
            with atomic_directory(dest): pass

    def test_unique_parent_counts_and_overlapping_missing_coverage(self):
        self.c['branches']['edta_tetrimmer'] = dict(enabled=True)
        (self.out/'edta').mkdir(parents=True)
        (self.out/'edta_tetrimmer').mkdir()
        table(self.out/'edta/family_provenance.tsv', [dict(family_id=x) for x in ('E1','E2','E3')], ['family_id'])
        table(self.out/'edta_tetrimmer/parents.tsv', [dict(parent_branch='edta',parent_family_id='E1',family_id=x) for x in ('T1','T2')], ['parent_branch','parent_family_id','family_id'])
        rows=[dict(seqid='chr',start=a,end=b,family_id=f,tier='te') for a,b,f in [(0,10,'E1'),(5,20,'E2'),(15,25,'E3')]]
        table(self.out/'edta/mask_sources.tsv',rows,['seqid','start','end','family_id','tier'])
        r=retention_summary(self.c,'s')
        self.assertEqual((r['retained_unique_parents'],r['missing_parent_families']),(1,2))
        self.assertEqual((r['missing_family_te_coverage_bp'],r['missing_family_exclusive_te_coverage_bp']),(20,15))
        (self.out/'edta/mask_sources.tsv').unlink()
        self.assertEqual(retention_summary(self.c,'s')['status'],'counts_only')
        self.assertIsNone(retention_summary(self.c,'s')['missing_family_te_coverage_bp'])

    def test_branch_export_fault_and_retry_preserve_last_complete_directory(self):
        from teflow.v2stages import export_one
        dest = self.out/'edta'
        def fail(c, sid, base, folder, branch, pending):
            (pending/'genome.softmasked.fa').write_text('truncated')
            raise RuntimeError('injected export interruption')
        def succeed(c, sid, base, folder, branch, pending):
            p = pending/'genome.softmasked.fa'; p.write_text('complete')
            return [p], dict(status='fixture')
        with patch('teflow.v2stages._export_one', side_effect=fail):
            with self.assertRaisesRegex(RuntimeError, 'interruption'):
                export_one(self.c, 's', self.root, self.root, 'edta')
        self.assertFalse(dest.exists())
        with patch('teflow.v2stages._export_one', side_effect=succeed):
            paths, _ = export_one(self.c, 's', self.root, self.root, 'edta')
        self.assertEqual(paths, [dest/'genome.softmasked.fa'])
        with patch('teflow.v2stages._export_one', side_effect=fail):
            with self.assertRaises(RuntimeError):
                export_one(self.c, 's', self.root, self.root, 'edta')
        self.assertEqual(paths[0].read_text(), 'complete')
        self.assertTrue(list(self.out.glob('.edta.partial-*')))

    def fixture_export(self):
        dest=self.out/'edta'; dest.mkdir(parents=True)
        names=['genome.softmasked.fa','repeat.mask.bed','library.fa','te_fragments.gff3','family_provenance.tsv','mask_sources.tsv']
        for name in names: (dest/name).write_text(name+'\n')
        write_json(dest/'manifest.json',dict(branch='edta',outputs={n:sha256(dest/n) for n in names}))
        return dest

    def test_selection_copy_preserves_sources_and_refuses_missing_policy(self):
        source=self.fixture_export()
        state=dict(stages=[dict(sample='s',stage='export_edta',status='complete')])
        with patch('teflow.cli.run_status',return_value=state):
            with self.assertRaises(WorkflowError): select(self.c,self.root/'bad','edta','all_interspersed',mode='copy')
            dest=self.root/'chosen'
            r=select(self.c,dest,'edta','te_primary',mode='copy')
            self.assertEqual(r['status'],'SELECTION_WRITTEN')
            self.assertEqual((dest/'library.fa').read_bytes(),(source/'library.fa').read_bytes())
            self.assertFalse(read_json(dest/'selection.json')['automatic_selection'])
            with self.assertRaises(WorkflowError): select(self.c,dest,'edta','te_primary',mode='copy')
        with patch('teflow.cli.run_status',return_value=dict(stages=[dict(sample='s',stage='export_edta',status='artifact_metadata_changed')])):
            with self.assertRaises(WorkflowError): select(self.c,self.root/'invalid','edta','te_primary',mode='copy')

    @unittest.skipUnless(os.name=='posix', 'symlinks require a supported platform')
    def test_relative_selection_links_survive_publication(self):
        source=self.fixture_export()
        with patch('teflow.cli.run_status',return_value=dict(stages=[dict(sample='s',stage='export_edta',status='complete')])):
            dest=self.root/'chosen'
            select(self.c,dest,'edta','te_primary')
            self.assertTrue((dest/'library.fa').is_symlink())
            self.assertEqual((dest/'library.fa').resolve(), source/'library.fa')

    def test_identity_cache_failure_falls_back_without_weakening_identity(self):
        p=self.root/'sequence'; p.write_bytes(b'a'*(1024*1024))
        import hashlib
        with patch.dict(os.environ,TEFLOW_IDENTITY_CACHE=str(self.root/'db')):
            with patch('teflow.common.sqlite3.connect',side_effect=sqlite3.OperationalError('locked')):
                with self.assertWarns(RuntimeWarning): self.assertEqual(sha256(p),hashlib.sha256(p.read_bytes()).hexdigest())

    def test_unrecognized_library_class_fails_before_search(self):
        p=self.root/'library.fa'; p.write_text('>x#UnexpectedRoot/subfamily\nACGT\n')
        with self.assertRaisesRegex(WorkflowError,'classification root'):
            canonical_library(p,self.root/'canonical.fa','R','fixture')

    def test_cpu_preview_uses_inherited_set_without_cross_project_guarantee(self):
        with patch('os.sched_getaffinity',return_value={16,17,18,19},create=True):
            r=cpu_affinity_plan(dict(execution=dict(threads=2)))
        self.assertEqual(r['planned_pool_cpu_ids'],[16,17])
        self.assertFalse(r['cross_project_exclusivity'])

    @unittest.skipUnless(os.name=='posix','Linux container wrapper paths')
    def test_hite_cleanenv_explicitly_binds_private_tmp(self):
        script=Path(__file__).resolve().parents[1]/'scripts/run_hite_container.py'
        spec=importlib.util.spec_from_file_location('hite_wrapper',script)
        module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        image=self.root/'hite.sif'; image.touch()
        private=self.root/'private'; private.mkdir()
        argv=[str(script),'--image',str(image),'--bind',str(self.root),'--','--help']
        with patch('sys.argv',argv),patch.dict(os.environ,TMPDIR=str(private)),patch.object(module.shutil,'which',return_value='/usr/bin/apptainer'),patch.object(module.os,'execvp') as call:
            module.main()
        command=call.call_args.args[1]
        self.assertIn(str(private)+':/tmp',command)
        self.assertIn('TMPDIR=/tmp',command)
        self.assertIn('--cleanenv',command)


if __name__=='__main__': unittest.main()
