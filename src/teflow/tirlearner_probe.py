"""Exercise the legacy pandas indexing used by TIR-Learner 3, without a genome.

Run this file with the EDTA environment's Python, not the workflow engine's.
It intentionally exercises the upstream indexing expression, not an iloc fix.
"""
from __future__ import annotations

import json
import sys
import warnings


def probe():
    import pandas as pd

    families = ["DTA", "DTC", "DTH"]
    frame = pd.DataFrame({"superfamily": families, "sequence": ["ACGT"] * 3})
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        try:
            observed = frame.apply(lambda row: row[0], axis=1).tolist()
        except KeyError as exc:
            raise RuntimeError(
                f"TIR-Learner 3 legacy row[0] indexing fails with pandas {pd.__version__}; "
                "use the pinned pandas=2.3.3 EDTA environment. Do not bypass missing TIR output with --force 1."
            ) from exc
    if observed != families:
        raise RuntimeError("TIR-Learner pandas indexing returned incorrect family labels")
    return dict(status="pass", pandas=pd.__version__, rows=len(frame),
                scope="Synthetic pandas row-indexing compatibility only; no TIR discovery or genome benchmark")


def main():
    try:
        result = probe()
    except Exception as exc:
        print(json.dumps(dict(status="fail", error=str(exc))), file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
