"""Synthetic interface fixture only; deliberately not a TE detection algorithm."""
import csv
from pathlib import Path
import shutil
import sys

tool, *args = sys.argv[1:]
versions = {"edta": "2.3.0", "tetrimmer": "1.7.2", "repeatmasker": "4.2.4", "trf": "4.10.0", "dustmasker": "2.17.0"}
versions.update(heliano="1.3.1", heliano_cons="1.0.2", hite="3.3.3", diamond="2.1.11", hmmscan="3.4")
# RepeatMasker accepts -v, not the BLAST-style -version flag. Reject the
# unsupported spelling so this fixture cannot hide a broken doctor probe.
if tool == "repeatmasker" and any(a in args for a in ("-version", "--version")):
    print("Unknown option: version", file=sys.stderr)
    raise SystemExit(1)
if any(a in args for a in ("--help", "--version", "-version", "-v", "version", "--check_dependencies")) or (tool == "hmmscan" and args == ["-h"]):
    banner = "EDTA v2.3" if tool == "edta" else tool + " " + versions[tool]
    print("FIXTURE ONLY", banner, "--input_file --pfam_dir --continue_analysis --num_threads All passed!")
    raise SystemExit(0)

# Only opted-in synthetic acceptance records timing/affinity and injected failure.
import os
if os.environ.get('TEFLOW_FIXTURE_EVENTS'):
    import atexit, json, time
    def event(kind, **extra):
        row=dict(event=kind,tool=tool,cwd=str(Path.cwd()),pid=os.getpid(),at=time.monotonic(),
                 cpu_ids=sorted(os.sched_getaffinity(0)),tmpdir=os.environ.get('TMPDIR'),**extra)
        fd=os.open(os.environ['TEFLOW_FIXTURE_EVENTS'],os.O_WRONLY|os.O_APPEND|os.O_CREAT,0o600)
        try: os.write(fd,(json.dumps(row)+'\n').encode())
        finally: os.close(fd)
    event('start'); atexit.register(event,'end')
    if os.environ.get('TEFLOW_FIXTURE_SPAWN_CHILD') == '1':
        import subprocess
        descendant = subprocess.Popen([sys.executable,'-c','import time; time.sleep(120)'])
        event('child_started', child_pid=descendant.pid)
    time.sleep(float(os.environ.get('TEFLOW_FIXTURE_DELAY','0.4')))
    if os.environ.get('TEFLOW_FIXTURE_FAIL_STAGE')==Path.cwd().name:
        raise SystemExit('deliberate fixture stage failure')

def arg(name):
    return args[args.index(name) + 1]

if tool == "edta":
    Path("genome.fa.mod.EDTA.TElib.fa").write_text(">Original1#DNA/hAT\nACGTACGTACGT\n>Original2#Unknown\nTTTTGGGGCCCC\n")
    for name in ("intact", "TEanno"):
        Path("genome.fa.mod.EDTA." + name + ".gff3").write_text("##gff-version 3\ns000001\tEDTA\trepeat_region\t1\t12\t.\t+\t.\tID=fixture\n")
elif tool == "tetrimmer":
    p = Path(arg("--output_dir")); p.mkdir(exist_ok=True)
    (p / "summary.txt").write_text("input_name,output_name,status,evaluation,low_copy\nE0000001,E0000001,processed,Good,False\nE0000002,E0000002,skipped,NaN,False\n")
    (p / "TEtrimmer_consensus_merged.fasta").write_text(">E0000001#DNA/hAT\nACGTACGTACGT\n")
elif tool == "repeatmasker":
    header = Path(arg("-lib")).read_text().splitlines()[0][1:]
    name, cls = header.split("#")
    query = Path(args[-1]); output = Path(arg("-dir")) / (query.name + ".out")
    if query.name == "candidates.fa":
        qid = query.read_text().splitlines()[0][1:]
        output.write_text("SW score\n100 1 0 0 " + qid + " 3 6 (18) + " + name + " " + cls + " 1 4 (8) 1\n")
    else:
        start = 65 if name.startswith("H") else 9 if name.startswith("I") else 1
        output.write_text("SW score\n100 1 0 0 s000001 " + str(start) + " " + str(start+11) + " (0) C " + name + " " + cls + " (0) 12 1 1\n")
        if "-a" in args:
            output.with_suffix(".align").write_text("FIXTURE auxiliary alignment; scientific parser is tested separately.\n")
elif tool == "trf":
    Path("genome.fa.2.7.7.80.10.50.500.dat").write_text("Tandem Repeats Finder\nSequence: s000001\n20 31 2 6 2 100 0 20 25 25 25 25 2.0 AC ACACACACACAC\n")
elif tool == "dustmasker":
    text = Path(arg("-in")).read_text()
    lines = text.splitlines(); lines[1] = lines[1][:4].lower() + lines[1][4:]
    Path(arg("-out")).write_text("\n".join(lines) + "\n")
elif tool == "heliano":
    from teflow.common import fasta
    p = Path(arg("-o")); p.mkdir()
    seqid, dna = next(fasta(arg("-g")))
    (p / "RC.representative.bed").write_text(seqid + "\t65\t88\tSF1\t2\t+\t1e-10\t100\tHLE1\tnonauto\tH_native\n")
    (p / "RC.representative.fa").write_text(">H_native\n" + dna[64:88] + "\n")
    (p / "pairlist.tbl").write_text("synthetic terminal evidence only\n")
elif tool == "heliano_cons":
    p = Path(arg("-o")); p.mkdir()
    (p / "RC.representative.cons.fa").write_text(">SF1.1\n" + "ACGT"*6 + "\n")
elif tool == "hite":
    p = Path(arg("--out_dir")); p.mkdir()
    (p / "confident_TE.cons.fa").write_text(">I_native#MITE/DTA\nGCAATTCGGCAT\n")
    (p / "low_confident_TE.cons.fa").write_text(">excluded#Unknown\nGCAATTCGGCAT\n")
elif tool == "diamond":
    if args[0] == "makedb":
        Path(arg("--db") + ".dmnd").write_text("synthetic database\n")
    else:
        Path(arg("--out")).write_text("")
elif tool == "hmmscan":
    Path(arg("--domtblout")).write_text("# synthetic no hits\n")
else:
    raise SystemExit("Unknown fixture tool")
