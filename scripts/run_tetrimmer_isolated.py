#!/usr/bin/env python3
"""Run the unchanged pinned TEtrimmer with private per-call TE-Aid work directories."""
from pathlib import Path
import sys

recipes = Path(__file__).resolve().parents[1]
python_root = recipes / "src" if (recipes / "src/teflow").is_dir() else recipes.parent.parent
if not (python_root / "teflow/teaid_isolation.py").is_file():
    raise RuntimeError("Cannot locate the matching teflow package for the isolation wrapper")
# The upstream environment does not itself need teflow installed. Import the
# matching pure-Python wrapper from the engine installation or source checkout.
sys.path.insert(0, str(python_root))
from teflow.teaid_isolation import launch

if __name__ == "__main__":
    launch()
