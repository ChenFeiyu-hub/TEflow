#!/usr/bin/env python3
"""Provision TE-Aid from an installed RepeatMasker protein library before database freeze."""
import argparse
from pathlib import Path
import sys
recipes = Path(__file__).resolve().parents[1]
python_root = recipes / "src" if (recipes / "src/teflow").is_dir() else recipes.parent.parent
if not (python_root / "teflow/teaid.py").is_file():
    raise RuntimeError("Cannot locate the matching teflow package for TE-Aid setup")
sys.path.insert(0, str(python_root))
from teflow.common import load_config, WorkflowError
from teflow.teaid import installed_repeatpeps, prepare_database


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", required=True)
    p.add_argument("--output", type=Path, required=True, help="New installation log directory")
    p.add_argument("--repeatpeps", type=Path)
    a = p.parse_args()
    try:
        if a.output.exists():
            raise WorkflowError("Log directory already exists; use a new output directory")
        c = load_config(a.config)
        result = prepare_database(c, a.repeatpeps or installed_repeatpeps(c), a.output)
        print("TE-Aid protein database ready. Run lock-databases before freeze/doctor.")
    except (WorkflowError, OSError, ValueError) as e:
        print(str(e), file=sys.stderr)
        raise SystemExit(2)
