#!/usr/bin/env python3
"""Read existing v4 intermediate evidence; never launches TIR-Learner or EDTA."""
from pathlib import Path
import sys

recipes = Path(__file__).resolve().parents[1]
python_root = recipes / "src" if (recipes / "src/teflow").is_dir() else recipes.parent.parent
sys.path.insert(0, str(python_root))
from teflow.tir_checkpoints import main

if __name__ == "__main__":
    sys.exit(main())
