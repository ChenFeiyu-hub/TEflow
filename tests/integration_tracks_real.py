"""Optional real TRF/dust interface check on a tiny deterministic sequence."""
import argparse
import json
from pathlib import Path
import random
import tempfile
from teflow.common import write_json, sha256
from teflow.runtime import run
from teflow.formats import trf_dat, dust_fasta

p=argparse.ArgumentParser()
p.add_argument("--trf", required=True, help="JSON argv prefix, e.g. [\"/env/bin/trf\"]")
p.add_argument("--dustmasker", required=True, help="JSON argv prefix")
p.add_argument("--output", required=True)
args=p.parse_args()
out=Path(args.output).resolve(); out.mkdir(parents=True,exist_ok=True)
if any(out.iterdir()): raise SystemExit("Use an empty output directory")
rng=random.Random(729)
seq="".join(rng.choices("ACGT",k=300)) + "AT"*100 + "G"*100 + "".join(rng.choices("ACGT",k=300))
genome=out / "genome.fa"; genome.write_text(">s1\n" + seq + "\n")
trf=json.loads(args.trf); dust=json.loads(args.dustmasker)
run(trf+["genome.fa","2","7","7","80","10","50","500","-d","-h"],out,out / "trf.log",60,cpu_limit=1)
rows=trf_dat(out / "genome.fa.2.7.7.80.10.50.500.dat",{"s1":len(seq)})
run(dust+["-in","genome.fa","-out","dust.fa","-outfmt","fasta","-level","20","-window","64","-linker","1"],out,out / "dust.log",60,cpu_limit=1)
low=dust_fasta(out / "dust.fa",genome)
assert rows and low, "Designed low-complexity/tandem sequence should have both tracks"
write_json(out / "validation.json",dict(status="pass",trf_command=trf,dust_command=dust,genome_bp=len(seq),
          trf_intervals=len(rows),dust_intervals=len(low),input_sha256=sha256(genome),scope="real executables; tiny synthetic sequence; no genome discovery benchmark"))
print("PASS: real TRF and dust output contracts")
