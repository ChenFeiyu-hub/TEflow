#!/usr/bin/env python3
"""Verify the reviewed v021 cleanup case and prepare a new v022 run without genome discovery."""
import argparse
import json
import os
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from teflow.common import WorkflowError
from teflow.teaid_recovery import recover


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--run-id", default="at_compare_v022")
    p.add_argument("--apply", action="store_true", help="Create the new run; default only verifies")
    a = p.parse_args()
    os.environ["TEFLOW_REPOSITORY"] = str(REPO)
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        print(json.dumps(recover(a.config, a.output, a.run_id, REPO, a.apply), indent=2))
    except (OSError, WorkflowError, ValueError) as e:
        p.exit(2, "Reviewed recovery stopped: " + str(e) + "\n")


if __name__ == "__main__":
    main()
