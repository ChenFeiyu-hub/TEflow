import json
import io
from contextlib import redirect_stdout
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from teflow.boundary_review import prepare, plan, execute, pack, analyze, read_hsps, validate_msa, FIELDS
from teflow.common import WorkflowError, fasta, table, read_json, sha256
from teflow.evaluation import tsv
from teflow.library_qc import revcomp
from teflow.cli import main


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.d=Path(self.temp.name)
        self.genome=self.d/'genome.fa'; self.genome.write_text('>chr\nACGTTAGCATGCTAACGTGCATACGATTCG\n')
        self.rows=[dict(locus_id='ref',group_id='g',seqid='chr',start=0,end=12,strand='+',role='reference',reason='reference'),
                   dict(locus_id='other',group_id='g',seqid='chr',start=18,end=30,strand='-',role='candidate',reason='chosen')]
        self.loci=self.d/'selected.tsv'; self.save()
        self.tool=dict(blastn=dict(command=[sys.executable,'fake.py'],expected_version=None))
    def tearDown(self): self.temp.cleanup()
    def save(self): table(self.loci,self.rows,list(self.rows[0]))
    def prep(self, **kwargs):
        out=self.d/'review'; prepare(self.genome,self.loci,out,flank=5,terminal=2,tools=self.tool,**kwargs); return out
    def hsp(self,q,s,qa,qb,sa,sb,qs,ss):
        ident=sum(a==b for a,b in zip(qs,ss)); mis=sum(a!=b and a!='-' and b!='-' for a,b in zip(qs,ss))
        gaps=sum(c=='-' and (i==0 or seq[i-1]!='-') for seq in (qs,ss) for i,c in enumerate(seq))
        return '\t'.join(map(str,['ref','other',round(100*ident/len(qs),3),len(qs),mis,gaps,qa,qb,sa,sb,1e-5,30,len(q),len(s),qs,ss]))+'\n'
    def test_asymmetric_clipping_and_reverse_complement(self):
        out=self.prep(); rows=tsv(out/'loci.tsv'); seq=dict(fasta(out/'group001/subjects.fa'))
        self.assertEqual((int(rows[0]['core_start']),int(rows[1]['core_start'])),(0,0))
        self.assertEqual(seq['other'],revcomp(dict(fasta(self.genome))['chr'][13:30]))
        self.assertEqual(seq['other'][:12],revcomp(dict(fasta(self.genome))['chr'][18:30]))
        self.assertEqual(rows[0]['annotation_status'],'not_provided')
        self.assertEqual(rows[0]['overlapping_CDS_union_bp'],'')
    def test_input_constraints_and_no_overwrite(self):
        self.rows[1]['start']=-1; self.save()
        with self.assertRaises(WorkflowError): self.prep()
        self.assertFalse((self.d/'review').exists())
        self.rows[1]['start']=18; self.rows[1]['locus_id']='../unsafe'; self.save()
        with self.assertRaises(WorkflowError): self.prep()
        self.rows[1]['locus_id']='other'; self.rows[1]['role']='reference'; self.save()
        with self.assertRaises(WorkflowError): self.prep()
        self.rows[1]['role']='candidate'; self.save(); self.prep()
        with self.assertRaisesRegex(WorkflowError,'exists'): self.prep()
    def test_plan_is_readonly_tamper_and_portability(self):
        out=self.prep(); p=plan(out)
        self.assertFalse(p['computation_launched']); self.assertFalse((out/'alignments').exists())
        moved=self.d/'moved'; shutil.copytree(out,moved); self.genome.unlink()
        self.assertEqual(plan(moved)['prepared_fingerprint'],p['prepared_fingerprint'])
        (moved/'group001/subjects.fa').write_text('>x\nACGT\n')
        with self.assertRaisesRegex(WorkflowError,'changed'): plan(moved)
        with self.assertRaisesRegex(WorkflowError,'changed'): pack(moved,self.d/'bad.tar.gz')
    def test_gaps_reverse_orientation_and_exact_source_validation(self):
        path=self.d/'blast.tsv'; q='ACGTAC'; s='AGTAC'
        path.write_text(self.hsp(q,s,1,6,1,5,q,'A-GTAC'))
        r=list(read_hsps(path,{'ref':q},{'other':s}))[0]
        self.assertEqual(len(r['pairs']),5); self.assertNotIn(1,[p[0] for p in r['pairs']])
        s=revcomp(q); path.write_text(self.hsp(q,s,1,6,6,1,q,q))
        r=list(read_hsps(path,{'ref':q},{'other':s}))[0]
        self.assertEqual(r['orientation'],'opposite'); self.assertEqual(r['pairs'][0][:2],(0,5))
        path.write_text(path.read_text().replace('\t100.0\t','\t0\t'))
        with self.assertRaises(WorkflowError): list(read_hsps(path,{'ref':q},{'other':s}))
        path.write_text(self.hsp(q,s,1,6,6,1,'TCGTAC',q))
        with self.assertRaisesRegex(WorkflowError,'frozen FASTA'): list(read_hsps(path,{'ref':q},{'other':s}))
    def test_disjoint_hits_are_not_an_envelope_and_duplicates_not_added(self):
        out=self.prep(); aln=out/'alignments'; aln.mkdir()
        seq=dict(fasta(out/'group001/subjects.fa')); q,s=seq['ref'],seq['other']
        first=self.hsp(q,s,1,2,1,2,q[:2],s[:2]); last=self.hsp(q,s,11,12,11,12,q[10:12],s[10:12])
        (aln/'group001.blast.tsv').write_text(first+first+last)
        analyze(out,aln)
        row=next(r for r in tsv(aln/'pair_summary.tsv') if r['subject']=='other' and r['orientation']=='same')
        self.assertEqual(row['query_core_paired_bp'],'4'); self.assertEqual(row['query_internal_paired_bp'],'0')
        self.assertEqual(row['longest_single_HSP_query_core_paired_bp'],'2')
    def test_no_hit_is_explicit_and_empty_internal_denominator(self):
        self.rows[0]['end']=2; self.save(); out=self.prep(); aln=out/'alignments'; aln.mkdir()
        (aln/'group001.blast.tsv').write_text(''); analyze(out,aln)
        row=tsv(aln/'pair_summary.tsv')[0]; self.assertEqual(row['HSPs'],'0')
        self.assertEqual(row['query_internal_fraction'],'')
    def test_sensitivity_is_explicit_and_region_summary_matches_DUST(self):
        self.tool['dustmasker']=dict(command=['dustmasker'],expected_version=None)
        out=self.prep(dust_sensitivity=True); p=plan(out)
        commands=[c['argv'] for c in p['commands'] if '-dust' in c['argv']]
        self.assertEqual([c[c.index('-dust')+1] for c in commands],['yes','no'])
        aln=out/'alignments'; aln.mkdir()
        for suffix in ('.blast.tsv','.nodust.blast.tsv'): (aln/('group001'+suffix)).write_text('')
        seqs=dict(fasta(out/'group001/subjects.fa'))
        (aln/'group001.dust.fa').write_text(''.join('>'+k+'\n'+v[:4].lower()+v[4:]+'\n' for k,v in seqs.items()))
        result=analyze(out,aln)
        self.assertEqual(result['self_control_status'],'inspect_incomplete_self_hits')
        self.assertEqual({r['search_mode'] for r in tsv(aln/'pair_summary.tsv')},{'dust','no_dust'})
        self.assertEqual(tsv(aln/'sequence_complexity.tsv')[0]['core_DUST_bp'],'4')
    def test_reverse_strand_CDS_projection(self):
        annotation=self.d/'genes.gff3'
        annotation.write_text('chr\tref\tgene\t20\t25\t.\t-\t.\tID=g1\nchr\tref\tmRNA\t20\t25\t.\t-\t.\tID=t1;Parent=g1\nchr\tref\tCDS\t20\t25\t.\t-\t0\tParent=t1\n')
        out=self.prep(annotation=annotation)
        r=tsv(out/'cds_oriented.tsv')[0]
        self.assertEqual((r['locus_id'],r['start'],r['end']),('other','5','11'))
        self.assertEqual(tsv(out/'loci.tsv')[1]['overlapping_CDS_union_bp'],'6')
    def test_msa_requires_same_bases_and_short_explicit_group(self):
        path=self.d/'msa.fa'; path.write_text('>a\nAC-G\n>b\nATCG\n')
        self.assertEqual(validate_msa(path,{'a':'ACG','b':'ATCG'})['columns'],4)
        with self.assertRaises(WorkflowError): validate_msa(path,{'a':'TCG','b':'ATCG'})
        with self.assertRaisesRegex(WorkflowError,'Unknown MAFFT'): self.prep(msa_groups=['absent'])
    def test_failure_receipt_and_no_silent_restart(self):
        out=self.prep()
        with patch('teflow.boundary_review.run',side_effect=WorkflowError('tool failed')):
            with self.assertRaisesRegex(WorkflowError,'tool failed'): execute(out)
        self.assertTrue((out/'alignments/failed.json').exists()); self.assertFalse((out/'alignments/complete.json').exists())
        with self.assertRaisesRegex(WorkflowError,'exists'): execute(out)
        archive=pack(out,self.d/'feedback.tar.gz'); self.assertGreater(archive['files'],5)
    def test_execution_receipts_and_complete_pack(self):
        out=self.prep()
        def fake(cmd,cwd,log,**kwargs):
            Path(log).write_text('mock external tool\n')
            if '-out' in cmd: Path(cmd[cmd.index('-out')+1]).write_text('')
            return 'mock external tool'
        with patch('teflow.boundary_review.run',side_effect=fake):
            self.assertEqual(execute(out)['summary']['HSPs'],0)
        self.assertTrue((out/'alignments/complete.json').is_file())
        pack(out,self.d/'ok.tar.gz')
        (out/'alignments/pair_summary.tsv').write_text('changed')
        with self.assertRaisesRegex(WorkflowError,'changed'): pack(out,self.d/'bad.tar.gz')
    def test_invalid_field_number_nan_and_coordinates(self):
        p=self.d/'bad.tsv'; p.write_text('bad\n')
        with self.assertRaises(WorkflowError): list(read_hsps(p,{'ref':'AC'},{'other':'AC'}))
        r=self.hsp('AC','AC',1,2,1,2,'AC','AC').split('\t'); r[10]='nan'; p.write_text('\t'.join(r))
        with self.assertRaises(WorkflowError): list(read_hsps(p,{'ref':'AC'},{'other':'AC'}))
        r[10]='0'; r[7]='3'; p.write_text('\t'.join(r))
        with self.assertRaises(WorkflowError): list(read_hsps(p,{'ref':'AC'},{'other':'AC'}))
        r[7]=str(10**15); p.write_text('\t'.join(r))
        with self.assertRaises(WorkflowError): list(read_hsps(p,{'ref':'AC'},{'other':'AC'}))
    def test_public_cli_plan_and_pack(self):
        out=self.prep(); captured=io.StringIO()
        with redirect_stdout(captured): self.assertEqual(main(['boundary-plan','--review',str(out)]),0)
        self.assertFalse(json.loads(captured.getvalue())['computation_launched'])
        with redirect_stdout(io.StringIO()): self.assertEqual(main(['boundary-pack','--review',str(out),'--output',str(self.d/'cli.tar.gz')]),0)
