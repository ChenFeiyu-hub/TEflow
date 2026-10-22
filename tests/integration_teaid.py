"""Tiny real BLAST protein database test, not a TE-Aid or genome benchmark.

Usage: TEFLOW_TEST_BLAST_BIN=/path/to/blast/bin PYTHONPATH=src python tests/integration_teaid.py
"""
import json
import os
from pathlib import Path
import sys
import tempfile
from teflow.teaid import database_prefix, prepare_database

blast = Path(os.environ["TEFLOW_TEST_BLAST_BIN"]).resolve()
with tempfile.TemporaryDirectory(prefix="teflow-protein-") as tmp:
    root = Path(tmp)
    shim = root / "environment_command.py"
    shim.write_text("import os,sys\nfrom pathlib import Path\np=Path(os.environ['TEFLOW_TEST_BLAST_BIN'])/sys.argv[3]\nos.execv(str(p),[str(p),*sys.argv[4:]])\n")
    env = root / "env"
    c = {"tools": {"tetrimmer": {"command": [sys.executable, str(shim), "-p", str(env), "TEtrimmer"]}}}
    prefix = database_prefix(c)
    prefix.parent.mkdir(parents=True)
    prefix.write_text("previous incomplete download")
    (prefix.parent.parent / "TE-Aid").write_text("fixture entry marker; never executed")
    (env / "share/teflow-vendor/sources.lock.json").write_text(json.dumps({"files": {}}))
    proteins = root / "proteins.fa"
    proteins.write_text(">synthetic_protein\n" + "MKWVTFISLLFLFSSAYSADKSEVAHRFKDLGE" * 4 + "\n")
    result = prepare_database(c, proteins, root / "logs")
    assert result["status"] == "pass"
    assert (Path(result["previous_database"]) / "RepeatPeps.lib").read_text() == "previous incomplete download"
    assert prefix.read_bytes() == proteins.read_bytes()
    print("PASS: real makeblastdb v4, blastdbcmd protein info and blastp self hit; previous DB preserved")
