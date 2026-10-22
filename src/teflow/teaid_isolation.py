"""Isolate each pinned TE-Aid subprocess without editing installed upstream files.

TE-Aid 1.7.2 writes a bare `header` in cwd even with -o. Each invocation gets
its own temporary cwd. Query/genome/output arguments stay absolute; stdout,
stderr, exit handling, biological parameters and published algorithms are unchanged.
"""
from __future__ import annotations
import hashlib
import importlib
import multiprocessing
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile


PINNED = {
    "TEaid.py": "f43e4729fee182a3f688451bb755a36497868dcbaf0c47a90c8513b6237150e9",
    "TE-Aid-master/TE-Aid": "a82bb08f3e10e1d4e01981eac5ed33ccbd2280c24e122e91decaa518ff6a5ee5",
    "TEtrimmer.py": "f19dd3079217edb0dbad3d79f569a83bcfbdd24914cba7dd02c799b271bcdb34",
}


class IsolatedSubprocess:
    """Replace only TEaid's module-local subprocess binding, not Python's module."""
    def __init__(self, binary):
        self.binary = Path(binary).resolve()

    def __getattr__(self, name):
        return getattr(subprocess, name)

    def run(self, args, *positional, **kwargs):
        if (not isinstance(args, (list, tuple)) or not args or
                Path(args[0]).resolve() != self.binary):
            return subprocess.run(args, *positional, **kwargs)
        if kwargs.get("shell") or "cwd" in kwargs:
            raise ValueError("Unexpected TE-Aid subprocess interface")
        paths = {}
        for flag in ("-q", "-g", "-o"):
            if args.count(flag) != 1 or args.index(flag) + 1 == len(args):
                raise ValueError("Missing/ambiguous TE-Aid path: " + flag)
            p = Path(args[args.index(flag) + 1])
            if not p.is_absolute():
                raise ValueError("Isolated TE-Aid requires absolute paths: " + flag)
            paths[flag] = p
        paths["-o"].mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".teflow-teaid-", dir=paths["-o"]) as cwd:
            return subprocess.run(args, *positional, cwd=cwd, **kwargs)


def launch(argv=None):
    if sys.platform != "linux":
        raise RuntimeError("The pinned TEtrimmer isolation wrapper requires Linux")
    root = Path(sys.prefix) / "share/teflow-vendor/TEtrimmer-1.7.2/tetrimmer"
    for rel, expected in PINNED.items():
        if hashlib.sha256((root / rel).read_bytes()).hexdigest() != expected:
            raise RuntimeError("Pinned upstream source differs: " + rel)
    # The published pipeline uses fork workers on the supported Linux/Python 3.11
    # environment. Refuse a different mode rather than silently losing isolation.
    method = multiprocessing.get_start_method(allow_none=True)
    if method is None:
        multiprocessing.set_start_method("fork")
    elif method != "fork":
        raise RuntimeError("TE-Aid isolation requires the audited fork worker mode")
    sys.path.insert(0, str(root))
    module = importlib.import_module("TEaid")
    if Path(module.__file__).resolve() != (root / "TEaid.py").resolve():
        raise RuntimeError("Unexpected TEaid import location")
    module.subprocess = IsolatedSubprocess(root / "TE-Aid-master/TE-Aid")
    entry = root / "TEtrimmer.py"
    sys.argv = [str(entry), *(sys.argv[1:] if argv is None else argv)]
    runpy.run_path(str(entry), run_name="__main__")
