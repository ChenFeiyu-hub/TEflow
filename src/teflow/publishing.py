"""Publish a finished directory on one filesystem; retain failed attempts."""
from contextlib import contextmanager
from pathlib import Path
import uuid
from .common import WorkflowError


@contextmanager
def atomic_directory(target, *, replace=False):
    target = Path(target).absolute()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink() or (target.exists() and (not replace or not target.is_dir())):
        raise WorkflowError('Output already exists or is a symlink: ' + str(target))
    token = uuid.uuid4().hex
    pending = target.with_name('.' + target.name + '.partial-' + token)
    pending.mkdir(exist_ok=False)
    # Exceptions preserve the hidden pending directory for diagnosis. Never
    # advertise it as a completed output, and never recursively delete user data.
    yield pending
    if target.is_symlink():
        raise WorkflowError('Output became a symlink during publication')
    previous = None
    if target.exists():
        if not replace or not target.is_dir():
            raise WorkflowError('Output appeared during publication')
        previous = target.with_name('.' + target.name + '.previous-' + token)
        target.rename(previous)
    try:
        pending.rename(target)
    except OSError:
        # A failed second rename must not hide an earlier completed delivery.
        # If something else appeared, retain previous for explicit inspection.
        if previous is not None and not target.exists() and not target.is_symlink():
            previous.rename(target)
        raise
