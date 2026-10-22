"""Cooperative cancellation, scoped to one live launcher attempt.

Requests never signal a stored PID. Each worker tears down only the commands it
started; a supervisor crash cannot be repaired by this interface.
"""
import os
import re
from pathlib import Path
import sys
from .common import WorkflowError, now, read_json, write_json


def cancellation_requested():
    path, token = os.environ.get('TEFLOW_CANCEL_FILE'), os.environ.get('TEFLOW_LAUNCH_ID')
    if not path or not token or not Path(path).exists():
        return False
    record = read_json(path)
    if record.get('attempt_id') != token:
        raise WorkflowError('Cancellation request does not match this launch')
    return True


def check_cancelled():
    if cancellation_requested():
        raise WorkflowError('Run cancellation requested; no further external command will start')


def write_request(path, attempt_id, reason):
    path = Path(path)
    if path.exists():
        if read_json(path).get('attempt_id') != attempt_id:
            raise WorkflowError('Conflicting cancellation request')
        return
    write_json(path, dict(attempt_id=attempt_id, requested=now(), reason=reason))


def cancel(c):
    from .resources import pool_root
    from .resource_pool import identity_alive, transaction
    if sys.platform != 'linux':
        raise WorkflowError('Cancellation must run on the same Linux host as the launcher')
    root = pool_root(c)
    if not (root/'controller.json').is_file():
        raise WorkflowError('No supervised launcher found')
    with transaction(root):
        rec = read_json(root/'controller.json')
        if rec.get('control_protocol') != 1:
            raise WorkflowError('This launcher predates supervised cancellation; inspect the original run')
        if rec.get('run_id') != c['run_id'] or rec.get('config') != c['_config_path']:
            raise WorkflowError('The active controller belongs to a different configuration')
        if rec.get('status') not in ('preflight', 'running', 'cancelling'):
            raise WorkflowError('Launcher is already terminal; use status/report')
        if identity_alive(rec['owner']) is not True:
            raise WorkflowError('Launcher is not verified live on this host; inspect runtime-status')
        if not re.fullmatch(r'[0-9a-f]{32}', str(rec.get('attempt_id', ''))):
            raise WorkflowError('Invalid launcher attempt ID')
        attempt = Path(c['work_root'])/c['run_id']/'launches'/rec['attempt_id']
        if not attempt.is_dir() or not attempt.resolve().is_relative_to(attempt.parent.resolve()):
            raise WorkflowError('Launcher control directory is missing or outside the launch directory')
        write_request(attempt/'cancel.json', rec['attempt_id'], 'teflow cancel')
    return dict(status='CANCEL_REQUESTED', attempt_id=rec['attempt_id'],
                request=str(attempt/'cancel.json'), processes_signalled=0,
                note='Wait for launcher status cancelled and empty leases before resume; pure Python stages may finish first')
