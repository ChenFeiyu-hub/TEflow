"""Keep MAFFT FASTA stdout separate from diagnostics under runtime.run's group."""
import subprocess
import sys


def main():
    if len(sys.argv)<3: raise SystemExit('Output FASTA and MAFFT argv required')
    with open(sys.argv[1],'xb') as f:
        result=subprocess.run(sys.argv[2:],stdout=f,check=False)
    return result.returncode


if __name__=='__main__': raise SystemExit(main())
