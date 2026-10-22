#!/usr/bin/env python3
"""Install checksum-locked, unchanged upstream sources into an isolated runtime.

Avoids the obsolete BioPerl metapackage pulled by Bioconda pfam_scan.
All actual runtime dependencies are declared in envs/tetrimmer.yml.
No pip/CPAN installs, dependency bypass flags, or source patches are used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(spec, cache):
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / spec["filename"]
    if not target.exists():
        # Unique temporary download; never overwrite an existing cached archive.
        fd, name = tempfile.mkstemp(prefix=target.name + ".", dir=cache)
        try:
            with os.fdopen(fd, "wb") as out:
                request = urllib.request.Request(spec["url"], headers={"User-Agent": "teflow-source-installer/0.1.2"})
                with urllib.request.urlopen(request, timeout=60) as response:
                    shutil.copyfileobj(response, out)
            if sha256(name) != spec["sha256"]:
                raise ValueError("Downloaded SHA256 mismatch: " + spec["name"])
            if target.exists():
                raise ValueError("Archive appeared during download; retry after checking concurrent installers")
            Path(name).rename(target)
        finally:
            Path(name).unlink(missing_ok=True)
    if sha256(target) != spec["sha256"]:
        raise ValueError("Cached SHA256 mismatch; preserve and inspect: " + str(target))
    return target


def extract_checked(archive, dest, root, include=None):
    """Copy only ordinary files/directories under the expected archive root."""
    with tarfile.open(archive, "r:gz") as tf:
        members = tf.getmembers()
        for member in members:
            p = PurePosixPath(member.name)
            if (p.is_absolute() or ".." in p.parts or not p.parts or
                    p.parts[0] != root or "\\" in member.name or
                    not (member.isfile() or member.isdir())):
                raise ValueError("Unsafe/unexpected archive member: " + member.name)
        for member in members:
            parts = PurePosixPath(member.name).parts
            # Do not install TEtrimmer's videos, example genome, or documentation.
            if include and len(parts) > 1 and parts[1] not in include:
                continue
            p = dest.joinpath(*PurePosixPath(member.name).parts)
            if member.isdir():
                p.mkdir(parents=True, exist_ok=True)
            else:
                p.parent.mkdir(parents=True, exist_ok=True)
                with tf.extractfile(member) as source, p.open("xb") as out:
                    shutil.copyfileobj(source, out)
                p.chmod(member.mode & 0o777)


def launcher(prefix, source_dir, spec):
    interpreter = shlex.quote(str(prefix / "bin" / spec["interpreter"]))
    entry = shlex.quote(str(source_dir / spec["entry"]))
    # Do not generate bytecode inside the frozen upstream source tree.
    lines = ["#!/usr/bin/env bash", "set -euo pipefail", "export PYTHONDONTWRITEBYTECODE=1"]
    if spec["interpreter"] == "perl":
        lines.append("export PERL5LIB=" + shlex.quote(str(source_dir)) + '${PERL5LIB:+:"$PERL5LIB"}')
    lines.append(f'exec {interpreter} {entry} "$@"')
    return "\n".join(lines) + "\n"


def install(prefix, cache, specs):
    if sys.platform != "linux" or Path(sys.prefix).resolve() != prefix:
        raise ValueError("Run this installer with micromamba run -p PREFIX python on Linux")
    if not (prefix / "conda-meta").is_dir():
        raise ValueError("Create the declared Conda runtime first")
    destination = prefix / "share" / "teflow-vendor"
    if destination.exists() or any((prefix / "bin" / s["command"]).exists() for s in specs):
        raise ValueError("Source installation or commands already exist; preserve them and use a fresh environment")
    archives = [(s, fetch(s, cache)) for s in specs]
    # All downloads/checksums and archive checks precede source publication.
    (prefix / "share").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="teflow-sources-", dir=prefix / "share") as tmp:
        staging = Path(tmp) / "vendor"
        staging.mkdir()
        for spec, archive in archives:
            extract_checked(archive, staging, spec["root"], spec.get("include"))
            if not (staging / spec["root"] / spec["entry"]).is_file():
                raise ValueError("Missing upstream entry point: " + spec["entry"])
        staging.rename(destination)
    try:
        files = {}
        for p in sorted(destination.rglob("*")):
            if p.is_file():
                files[p.relative_to(prefix).as_posix()] = sha256(p)
        for spec in specs:
            script = prefix / "bin" / spec["command"]
            with script.open("x", encoding="utf-8", newline="\n") as out:
                out.write(launcher(prefix, destination / spec["root"], spec))
            script.chmod(0o755)
            files[script.relative_to(prefix).as_posix()] = sha256(script)
        # Verify Perl module loading and TEtrimmer's real import/CLI paths.
        subprocess.run([str(prefix / "bin/perl"), "-MMoose", "-MIPC::Run",
                        "-MBio::LocatableSeq", "-MBio::Seq::RichSeq", "-e", "1"],
                       check=True, timeout=120)
        for command, args in (("blastn", ["-version"]), ("makeblastdb", ["-version"]),
                              ("blastdbcmd", ["-version"]), ("rmblastn", ["-version"]),
                              ("pfam_scan.pl", ["-h"]), ("TEtrimmer", ["--version"]),
                              ("TEtrimmer", ["--help"])):
            subprocess.run([str(prefix / "bin" / command), *args], check=True, timeout=120)
        lock = {"schema_version": 1, "sources": specs, "files": files, "status": "verified_cli"}
        (destination / "sources.lock.json").write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
        print("Upstream sources and CLI checks complete; classification/Pfam database checks are still required.")
    except BaseException:
        print("Source installation incomplete. Preserved for diagnosis: " + str(destination), file=sys.stderr)
        raise


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--prefix", type=Path)
    ap.add_argument("--cache", type=Path, required=True)
    ap.add_argument("--fetch-only", action="store_true", help="Verify downloads only; does not install")
    a = ap.parse_args()
    spec_file = Path(__file__).resolve().parents[1] / "envs" / "vendor-sources.json"
    specs = json.loads(spec_file.read_text(encoding="utf-8"))["sources"]
    if a.fetch_only:
        for spec in specs:
            print(str(fetch(spec, a.cache.resolve())))
    else:
        if a.prefix is None:
            ap.error("--prefix is required for installation")
        install(a.prefix.resolve(), a.cache.resolve(), specs)


if __name__ == "__main__":
    main()
