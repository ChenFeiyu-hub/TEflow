"""Exercise real DIAMOND and HMMER positive-hit parsing with synthetic protein/HMM."""
import argparse
import json
from pathlib import Path
import random
from teflow.common import read_json, write_json
from teflow.library_qc import CODONS, library_qc
from teflow.runtime import run
from teflow.evaluation import tsv

p=argparse.ArgumentParser()
p.add_argument("--prefix",required=True); p.add_argument("--output",required=True)
args=p.parse_args()
root=Path(args.output).resolve(); root.mkdir(parents=True,exist_ok=True)
if any(root.iterdir()): raise SystemExit("Use an empty output directory")
prefix=Path(args.prefix).resolve()
rng=random.Random(1013)
protein="M" + "".join(rng.choices("ACDEFGHIKLMNPQRSTVWY",k=249))
back={aa:codon for codon,aa in CODONS.items()}
dna="".join(back[x] for x in protein)
pep=root / "protein.faa"; pep.write_text(">synthetic\n" + protein + "\n")
lib=root / "library.fa"; lib.write_text(">E1#DNA/hAT\n" + dna + "\n")
pfam=root / "toy_hmm"; pfam.mkdir()
run([prefix / "bin/hmmbuild","--amino",pfam / "Pfam-A.hmm",pep],root,root / "hmmbuild.log",60,cpu_limit=1)
run([prefix / "bin/hmmpress",pfam / "Pfam-A.hmm"],root,root / "hmmpress.log",60,cpu_limit=1)
c=dict(qc=dict(host_proteins=str(pep),te_proteins=str(pep),pfam=True,evalue=1e-5),
       databases=dict(pfam_dir=str(pfam)),execution=dict(stage_timeout_seconds=120),
       tools={k:dict(command=[str(prefix / "bin" / k)]) for k in ("diamond","hmmscan")})
result=library_qc(c,root,lib,root / "qc",1)
row=tsv(root / "qc/library_qc.tsv")[0]
assert int(row["host_protein_hits"])>0 and int(row["te_protein_hits"])>0 and int(row["pfam_hits"])>0,row
assert "host_protein_similarity_review" in row["flags"]
assert result["automatic_filter"] is False and lib.exists()
write_json(root / "validation.json",dict(status="pass",evidence=result,row=row,
  scope="Real DIAMOND/HMMER; single synthetic sequence and toy HMM named Pfam-A for interface testing; no Pfam biological validation"))
print("PASS: real DIAMOND/HMMER positive evidence; library retained")
