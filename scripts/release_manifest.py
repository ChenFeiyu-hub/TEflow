#!/usr/bin/env python3
"""List (--write: save) a bounded source inventory. No checksum verification gate."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re

TOP = (".gitattributes", ".gitignore", "README.md", "CHANGELOG.md", "CITATION.cff", "LICENSE",
       "CONTRIBUTING.md", "pyproject.toml", "setup.py", "MANIFEST.in")
FOLDERS = (".github", "docs", "envs", "examples", "scripts", "src", "tests", "workflow")


def inventory(root):
    paths = [root / name for name in TOP]
    paths += [p for folder in FOLDERS for p in (root / folder).rglob("*") if p.is_file()]
    files = {}
    for path in sorted(paths):
        rel = path.relative_to(root)
        if any(x == "__pycache__" or x.endswith(".egg-info") for x in rel.parts) or path.suffix in {".pyc", ".pyo"}:
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(root) or not path.is_file():
            raise ValueError("Unsafe/missing source file: " + str(rel))
        if path.stat().st_size > 1024 * 1024:
            raise ValueError("Unexpected source file above 1 MiB: " + str(rel))
        files[rel.as_posix()] = dict(bytes=path.stat().st_size)
    return files


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--write", action="store_true", help="Refresh manifest after intentional source changes, before packaging")
    args = p.parse_args()
    root = Path(__file__).resolve().parents[1]
    version = re.search(r'__version__\s*=\s*[\"\x27]([^\"\x27]+)', (root / "src/teflow/__init__.py").read_text(encoding="utf-8")).group(1)
    files = inventory(root)
    target = root / "source_manifest.json"
    if args.write:
        record = dict(schema_version=2, version=version, date=datetime.now(timezone.utc).date().isoformat(), files=files,
                      purpose='Informational source inventory; no SHA-256 release/upload validation')
        target.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(dict(status="written" if args.write else "inventory_only", version=version, source_files=len(files),checksums_verified=False)))


if __name__ == "__main__":
    main()
