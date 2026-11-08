#!/usr/bin/env python3
"""Use the matching TEflow adapter inside an upstream Conda environment."""
from pathlib import Path
import sys

recipes = Path(__file__).resolve().parents[1]
python_root = recipes / "src" if (recipes / "src/teflow").is_dir() else recipes.parent.parent
if not (python_root / "teflow/edta_entry.py").is_file():
    raise RuntimeError("Cannot locate the matching TEflow EDTA adapter")
sys.path.insert(0, str(python_root))
from teflow.edta_entry import main

if __name__ == "__main__":
    sys.exit(main())
