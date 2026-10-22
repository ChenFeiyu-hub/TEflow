"""Locate versioned recipes in a checkout, an explicit override, or an installed wheel."""
from pathlib import Path
import os
from .common import WorkflowError

FOLDERS = ("workflow", "scripts", "envs")


def asset_root():
    override = os.environ.get("TEFLOW_REPOSITORY")
    package = Path(__file__).resolve().parent
    candidates = [Path(override).expanduser().resolve()] if override else [package / "_assets", package.parents[1]]
    for root in candidates:
        if (root / "workflow/Snakefile").is_file() and all((root / name).is_dir() for name in FOLDERS):
            return root
    raise WorkflowError("Workflow recipes missing; reinstall the complete package or check TEFLOW_REPOSITORY")


def asset_path(relative):
    root = asset_root()
    rel = Path(relative)
    path = (root / rel).resolve()
    if rel.is_absolute() or not rel.parts or rel.parts[0] not in FOLDERS or not path.is_relative_to(root):
        raise WorkflowError("Asset path must stay within workflow/, scripts/ or envs/")
    if not path.is_file():
        raise WorkflowError("Asset not found: " + str(relative))
    return path


def recipe_files():
    root = asset_root()
    return {p.relative_to(root).as_posix(): p for sub in FOLDERS for p in sorted((root / sub).rglob("*"))
            if p.is_file() and "__pycache__" not in p.parts and p.suffix not in {".pyc", ".pyo"}}
