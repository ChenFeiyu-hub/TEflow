"""Small dependency execution probes; standalone inside either upstream environment."""
import hashlib
import importlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


def main(tool):
    checks = []
    def call(argv, cwd, allowed=(0,)):
        r = subprocess.run(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=90)
        if r.returncode not in allowed:
            raise RuntimeError("Dependency execution failed: " + repr(argv) + "\n" + r.stdout[-1000:])
        checks.append(dict(command=argv, returncode=r.returncode))
        return r.stdout
    modules = ["Bio", "pybedtools"] if tool == "heliano" else ["Bio", "numpy", "pandas", "pysam", "tensorflow", "torch"]
    for name in modules:
        mod = importlib.import_module(name)
        checks.append(dict(module=name, version=getattr(mod, "__version__", "available")))
    commands = ["bedtools", "makeblastdb", "blastn", "cd-hit-est", "mafft"]
    # HiTE uses the bioinformatics Ninja (ninja-nj), not the unrelated ninja build tool.
    commands += ["hmmsearch", "getorf", "gt", "dialign2-2", "cons", "rnabob", "Rscript"] if tool == "heliano" else ["RepeatMasker", "RepeatModeler", "Ninja"]
    for name in commands:
        if not shutil.which(name):
            raise RuntimeError("Missing dependency: " + name)
        checks.append(dict(binary=name, path=shutil.which(name)))
    with tempfile.TemporaryDirectory(prefix="teflow-probe-") as d:
        root = Path(d)
        dna = "ATG" + "GCC"*48 + "TAA"
        (root / "dna.fa").write_text(">probe\n" + dna + "\n>copy\n" + dna + "\n")
        (root / "site.bed").write_text("probe\t0\t9\n")
        text = call(["bedtools", "getfasta", "-fi", "dna.fa", "-bed", "site.bed"], d)
        if dna[:9] not in text:
            raise RuntimeError("bedtools extraction mismatch")
        call(["makeblastdb", "-in", "dna.fa", "-dbtype", "nucl", "-out", "db"], d)
        call(["blastn", "-query", "dna.fa", "-db", "db", "-num_threads", "1", "-outfmt", "6", "-out", "hits.tsv"], d)
        call(["cd-hit-est", "-i", "dna.fa", "-o", "cluster.fa", "-c", "0.8", "-n", "5", "-T", "1", "-M", "128"], d)
        if not (root / "cluster.fa").stat().st_size:
            raise RuntimeError("cd-hit produced no representative")
        call(["mafft", "--thread", "1", "--quiet", "dna.fa"], d)
        if tool == "heliano":
            call(["getorf", "-sequence", "dna.fa", "-outseq", "orf.fa", "-minsize", "9", "-auto"], d)
            call(["Rscript", "--vanilla", "-e", "library(bedtoolsr);library(seqinr);cat('R packages loaded')"], d)
            launcher = Path(shutil.which("heliano")).resolve().read_text()
            m = re.search(r"HMMFILE\s*=\s*['\"]([^'\"]+)['\"]", launcher)
            if not m or not Path(m[1]).is_file():
                raise RuntimeError("Cannot resolve installed HELIANO HMM")
            call(["hmmsearch", "--cpu", "1", "--tblout", "domains.tsv", m[1], "orf.fa"], d)
            checks.append(dict(heliano_hmm=m[1], sha256=hashlib.sha256(Path(m[1]).read_bytes()).hexdigest()))
        else:
            probe_ninja(root, call)
            source = Path("/HiTE/main.py")
            if not source.is_file():
                raise RuntimeError("Expected HiTE container source is missing")
            checks.append(dict(hite_main_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                               pretrained_reference_exposure="not_established; record image digest"))
    print(json.dumps(dict(status="pass", checks=checks, scope="dependency operations on synthetic sequences; not whole-pipeline or biological validation")))


def probe_ninja(root, call):
    """Exercise the exact upstream clustering interface on three aligned sequences."""
    root = Path(root)
    ids = {"probe_a", "probe_b", "probe_c"}
    (root / "ninja.fa").write_text(">probe_a\n" + "ACGT"*40 + "\n>probe_b\n" +
                                  "ACGT"*39 + "ACGA\n>probe_c\n" + "ACGT"*39 + "ACGG\n")
    call(["Ninja", "--in", "ninja.fa", "--out", "ninja.clusters.tsv", "--out_type", "c",
          "--corr_type", "m", "--cluster_cutoff", "0.2", "--threads", "1"], str(root))
    rows = [line.split() for line in (root / "ninja.clusters.tsv").read_text().splitlines() if line.strip()]
    if len(rows) != 3 or any(len(row) != 2 for row in rows) or {row[1] for row in rows} != ids:
        raise RuntimeError("Ninja clustering did not preserve all three synthetic sequence IDs")


if __name__ == "__main__":
    try:
        main(sys.argv[1])
    except Exception as e:
        print(json.dumps(dict(status="fail", error=str(e))))
        raise SystemExit(2)
