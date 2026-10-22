"""Bind a dedicated task root and execute the pinned HiTE container without a shell."""
import argparse
import os
from pathlib import Path
import shutil
import sys

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--image", required=True)
    p.add_argument("--bind", required=True)
    p.add_argument("--engine", default="apptainer")
    args, rest = p.parse_known_args()
    if rest[:1] == ["--"]:
        rest = rest[1:]
    image, root = Path(args.image).resolve(), Path(args.bind).resolve()
    if not image.is_file() or not root.is_dir() or not shutil.which(args.engine):
        p.error("A local SIF, task root and Apptainer executable are required")
    if any(ch in str(root) + str(image) for ch in "\n,: \t"):
        p.error("Image and bind root require safe paths without spaces, commas or colons")
    recipes = Path(__file__).resolve().parents[1]
    probe = recipes / "src/teflow/upstream_probe.py"
    if not probe.is_file():
        probe = recipes.parent / "upstream_probe.py"
    if not probe.is_file():
        p.error("Matching HiTE dependency probe is missing from this installation")
    # Upstream documents `singularity run ... python /HiTE/main.py`; retain its runscript.
    argv = [args.engine, "run", "--cleanenv", "--bind", f"{root}:{root}", "--bind", f"{probe}:/teflow_probe.py:ro"]
    if os.environ.get('TMPDIR'):
        private_tmp = Path(os.environ['TMPDIR']).resolve()
        if not private_tmp.is_dir() or any(ch in str(private_tmp) for ch in "\n,: \t"):
            p.error('TMPDIR must be an existing safe directory')
        argv += ['--bind', f'{private_tmp}:/tmp', '--env', 'TMPDIR=/tmp', '--env', 'TMP=/tmp', '--env', 'TEMP=/tmp']
    argv.append(str(image))
    if rest == ["--teflow-probe"]:
        argv += ["python", "/teflow_probe.py", "hite"]
    else:
        for key in ("--genome", "--out_dir", "--work_dir"):
            if key in rest:
                value = Path(rest[rest.index(key)+1]).resolve()
                if not value.is_relative_to(root):
                    p.error(key + " is outside the bound task root")
        argv += ["python", "/HiTE/main.py"] + rest
    os.execvp(argv[0], argv)

if __name__ == "__main__":
    main()
