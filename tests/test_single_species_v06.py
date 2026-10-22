import json
from pathlib import Path
import tempfile
import unittest
from teflow.common import WorkflowError, write_json, fasta
from teflow.classification import classify, standard_class, tier
from teflow.formats import rm_out, export_branch
from teflow.evaluation import coverage_layers


class SingleSpeciesFormats(unittest.TestCase):
    def test_explicit_aliases_and_root_only_evidence(self):
        for name in ('DNA/MULE-MuDR', 'DNA/CMC-EnSpm', 'DNA/Kolobok', 'DNA/P', 'DNA/Merlin', 'MITE/DTH'):
            self.assertEqual(standard_class(name), 'TIR_MITE', name)
            self.assertEqual(tier(name), 'te')
        self.assertEqual(standard_class('DNA/Crypton'), 'DNA_other')
        self.assertEqual(standard_class('DNA/Polinton'), 'DNA_other')
        self.assertEqual(classify('DNA/new_family')['mapping_status'], 'root_only')
        self.assertEqual(classify('DNA/other')['superfamily_code'], '')
        self.assertTrue(classify('sine/trna?')['classification_uncertain'])
        self.assertEqual(classify('DNA/PseudogeneLike')['standard_class'], 'DNA_other')
        with self.assertRaises(WorkflowError): classify('unrecognized/anything')

    def test_consensus_coordinates_both_strands_and_discrepancy(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp)/'test.out'
            p.write_text('SW score\n100 1 0 0 s 1 4 (16) + F DNA/hAT 2 5 (7) 1\n'
                         '100 1 0 0 s 9 12 (8) C F DNA/hAT (7) 5 2 2 *\n')
            rows = rm_out(p, {'s':20}, {'F'}, {'F':12})
            self.assertEqual([(r['rep_start'],r['rep_end'],r['rep_left'],r['consensus_length']) for r in rows], [(2,5,7,12)]*2)
            self.assertEqual(rows[1]['consensus_coordinate_status'], 'verified')
            self.assertEqual(rm_out(p, {'s':20}, {'F'}, {'F':13})[0]['consensus_coordinate_status'], 'length_mismatch')
            with self.assertRaisesRegex(WorkflowError,'inferred=12'):
                rm_out(p, {'s':20}, {'F'}, {'F':13}, strict_consensus=True)
            p.write_text(p.read_text().replace('(7)', '7', 1))
            with self.assertRaises(WorkflowError): rm_out(p, {'s':20}, {'F'})

    def test_masks_union_and_gff_target(self):
        with tempfile.TemporaryDirectory() as temp:
            d=Path(temp);prep=d/'prepared';prep.mkdir()
            (prep/'genome.fa').write_text('>s\nACGTACGTACGT\n')
            write_json(prep/'manifest.json', dict(sequences=[dict(alias='s',original_id='chr',length=12,included=True)]))
            lib=d/'lib.fa';lib.write_text('>F#DNA/hAT\nACGT\n>U#Unknown\nACGT\n')
            out=d/'rm.out';out.write_text('SW score\n100 1 0 0 s 1 4 (8) + F DNA/hAT 1 4 (0) 1\n100 1 0 0 s 3 6 (6) C U Unknown (0) 4 1 2\n')
            q=export_branch(prep, lib, out, d/'E', 'E', softmask_policies=['te_primary','all_interspersed'])
            self.assertEqual(q['repeat_mask_bp'],4)
            self.assertEqual(q['interspersed_incl_unknown_bp'],6)
            self.assertEqual(list(fasta(d/'E/genome.softmasked.fa'))[0][1],'acgtACGTACGT')
            self.assertEqual(list(fasta(d/'E/genome.softmasked.all_interspersed.fa'))[0][1],'acgtacGTACGT')
            self.assertIn('Target=F 1 4 +', (d/'E/te_fragments.gff3').read_text())
            self.assertIn('Target=U 1 4 +', (d/'E/te_fragments.gff3').read_text())
            reverse=(d/'E/te_fragments.gff3').read_text().splitlines()[2].split('\t')
            self.assertEqual(reverse[6],'-')  # genomic - / Target +, not -/-
            self.assertEqual(coverage_layers(d,['E'])[0]['interspersed_incl_unknown_bp'],6)
            # A mismatch remains in the evidence table, never a false Target.
            lib.write_text('>F#DNA/hAT\nACGTA\n>U#Unknown\nACGT\n')
            export_branch(prep,lib,out,d/'M','M')
            self.assertNotIn('Target=F ',(d/'M/te_fragments.gff3').read_text())

    def test_real_processrepeats_negative_remaining_is_diagnostic(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'rm.out'
            p.write_text('SW score\n1215 18.9 7.4 5.7 s 1 340 (0) C E DNA/Helitron (-2) 1346 876 16516\n')
            row=rm_out(p,{'s':340},{'E'},{'E':1344})[0]
            self.assertEqual(row['rep_left'],-2)
            self.assertEqual(row['consensus_length'],1344)
            self.assertEqual(row['consensus_coordinate_status'],'out_of_bounds')
            self.assertEqual(row['rep_tokens'],'(-2) 1346 876')
            with self.assertRaises(WorkflowError): rm_out(p,{'s':340},{'E'},{'E':1344},strict_consensus=True)
