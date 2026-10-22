#!/usr/bin/env python3
"""Run bounded acceptance from a verified source checkout, without reinstalling TEflow."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from teflow_runtime.acceptance import main

if __name__ == "__main__":
    raise SystemExit(main())
