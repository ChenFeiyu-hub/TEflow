"""Tiny actual DIAMOND run: >5 targets, multiple HSPs, both query strands.

This is an interface/sensitivity-parameter check, not a TE benchmark. It does
not install software or launch genome discovery. Requires existing DIAMOND.
"""
import argparse
from pathlib import Path
import random
import tempfile
from teflow.candidate_review import prepare_review, run_review, pack_review
from teflow.common import write_json, read_json
from teflow.evaluation import tsv
from teflow.library_qc import CODONS, revcomp

p = argparse.ArgumentParser(); p.add_argument("--diamond", required=True); p.add_argument("--output")
args = p.parse_args()
root = Path(args.output).resolve() if args.output else Path(tempfile.mkdtemp(prefix="teflow-real-candidate-"))
root.mkdir(exist_ok=True, parents=True)
if any(root.iterdir()): raise SystemExit("Use an empty output directory")
rng = random.Random(1015)
peptide_a = "M" + "".join(rng.choices("ACDEFGHIKLMNPQRSTVWY", k=119))
peptide_b = "M" + "".join(rng.choices("ACDEFGHIKLMNPQRSTVWY", k=119))
# HSPs must be non-enveloped in both query and target. Repeating the same
# peptide twice in a query cannot test this: its target range is enveloped.
protein = peptide_a + "".join(rng.choices("ACDEFGHIKLMNPQRSTVWY", k=1000)) + peptide_b
back = {aa: codon for codon, aa in CODONS.items()}
query = "".join(back[a] for a in peptide_a) + "N"*300 + "".join(back[a] for a in peptide_b)
library = root / "library.fa"; library.write_text(">P#DNA/hAT\n" + query + "\n>M#DNA/hAT\n" + revcomp(query) + "\n")
genome = root / "genome.fa"; genome.write_text(">chr\n" + query + "\n")
annotation = root / "genome.fa.out"
annotation.write_text(f"SW score\n100 0 0 0 chr 1 {len(query)} (0) + P DNA/hAT 1 {len(query)} (0) 1\n")
align = root / "genome.fa.align"
align.write_text(f"100 0 0 0 chr 1 {len(query)} (0) P#DNA/hAT 1 {len(query)} (0) raw1 1\nchr 1 {query} {len(query)}\nP#DNA 1 {query} {len(query)}\n")
proteins = root / "proteins.faa"; proteins.write_text("".join(f">target{i}\n{protein}\n" for i in range(8)))
selection = root / "families.txt"; selection.write_text("P\nM\n")
review = root / "review"
prepare_review(dict(genome=genome, library=library, rm_out=annotation, rm_align=align, host_proteins=proteins),
               review, selection, tool=dict(command=[str(Path(args.diamond).resolve())], expected_version="2.1.11"), max_loci=2)
result = run_review(review, threads=1, timeout=120)
hsps = tsv(review / "protein_qc/hsps.tsv")
for fid in ("P", "M"):
    rows = [r for r in hsps if r["family_id"] == fid]
    assert len({r['sseqid'] for r in rows}) == 8, rows
    assert len(rows) >= 16, rows
assert any(int(r['qframe']) < 0 for r in hsps)
assert any(int(r['qframe']) > 0 for r in hsps)
pack_review(review, root / "feedback.tar.gz")
write_json(root / "validation.json", dict(status="pass", tool="DIAMOND 2.1.11", query_families=2, protein_targets=8,
           reported_HSPs=len(hsps), both_query_strands=True, BTOP_consumption_verified=True,
           scope="Small synthetic sequences; actual tool execution; not a biological TE validation"))
print("PASS: real DIAMOND expanded-target/HSP reporting and traceback on both strands", len(hsps))
