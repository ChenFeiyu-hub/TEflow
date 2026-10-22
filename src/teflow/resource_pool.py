"""Linux local leases and observation; no TE algorithms or scheduler dependencies.

CPU affinity is enforced. Memory is admission/observation only. No process outside
an owned command is signalled. Leases surviving an unclean exit require reconciliation.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import json
import os
import platform
from pathlib import Path
import sys
import threading
import time
import uuid
from .common import WorkflowError, now, read_json, write_json

CURRENT = ContextVar('teflow_stage_lease', default=None)


def identity_alive(identity):
    if identity.get('host') != platform.node() or not identity.get('boot_id') or not identity.get('start_ticks'):
        return None
    try:
        if Path('/proc/sys/kernel/random/boot_id').read_text().strip()!=identity['boot_id']:
            return False
        fields=Path('/proc/'+str(identity['pid'])+'/stat').read_text().rsplit(')',1)[1].split()
        return fields[0]!='Z' and fields[19]==str(identity['start_ticks'])
    except FileNotFoundError:
        return False
    except (OSError,IndexError,ValueError):
        return None


@contextmanager
def transaction(root):
    import fcntl
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    with (root/'pool.lock').open('a+') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        p = root/'pool.json'
        state = read_json(p) if p.exists() else dict(schema_version=1, leases={})
        yield state
        write_json(p, state)


def inspect_pool(root):
    root = Path(root)
    if not (root/'pool.json').exists():
        return dict(schema_version=1, leases={}, enforcement='observe_only')
    state = read_json(root/'pool.json')
    for rec in state['leases'].values():
        rec['owner_alive'] = identity_alive(rec['owner']) if sys.platform.startswith('linux') else None
        status = Path(rec['attempt'])/'status.json'
        rec['observation'] = read_json(status) if status.exists() else None
    state['enforcement'] = 'observe_only'
    return state


def _assert_quiescent(rec):
    from .runtime import group_alive
    if identity_alive(rec['owner']) is not False:
        raise WorkflowError('Lease owner is live or cannot be verified: ' + rec['attempt'])
    if rec.get('spawn_in_progress'):
        raise WorkflowError('Worker died during command dispatch; process ownership requires manual review: ' + rec['attempt'])
    for command in rec.get('commands', []):
        if group_alive(command):
            raise WorkflowError('Owned command group is still live; lease retained: ' + rec['attempt'])


def reconcile(root):
    """Explicitly remove dead, quiescent lease records; never stop or adopt processes."""
    released = []
    with transaction(root) as state:
        for token, rec in list(state['leases'].items()):
            _assert_quiescent(rec)
            released.append(dict(token=token, attempt=rec['attempt']))
        for rec in released:
            del state['leases'][rec['token']]
    return dict(status='reconciled', released=released, processes_signalled=0)


def acquire_controller(root, metadata=None):
    """Supervisor lock; only its scheduler receives the fd explicitly via pass_fds."""
    import fcntl
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    fd = os.open(root/'controller.lock', os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with transaction(root) as state:
            if state['leases']:
                raise WorkflowError('Unresolved runtime leases; inspect runtime-status, then runtime-reconcile after processes exit')
        os.set_inheritable(fd, False)
        from .runtime import process_identity
        write_json(root/'controller.json',{**(metadata or {}), 'owner':process_identity(os.getpid()),
                   'started':now(), 'scope':'one_active_controller_per_work_root'})
        return fd
    except BlockingIOError as e:
        os.close(fd)
        raise WorkflowError('Another TEflow controller is using this work_root') from e
    except BaseException:
        os.close(fd)
        raise


def available_mb():
    try:
        for line in Path('/proc/meminfo').read_text().splitlines():
            if line.startswith('MemAvailable:'):
                return int(line.split()[1])//1024
    except (OSError, ValueError):
        pass
    return None


def process_tree(pid):
    """Sample live descendants, not unrelated processes belonging to the same Unix account."""
    rows = {}
    page = os.sysconf('SC_PAGE_SIZE')
    for p in Path('/proc').glob('[0-9]*/stat'):
        try:
            v = p.read_text().rsplit(')',1)[1].split()
            if v[0] != 'Z':
                rows[int(p.parent.name)] = (int(v[1]), max(0,int(v[21]))*page)
        except (OSError, ValueError, IndexError):
            continue
    owned = {pid} if pid in rows else set()
    while True:
        more = {n for n,(parent,_) in rows.items() if parent in owned} - owned
        if not more: break
        owned |= more
    return dict(rss_bytes=sum(rows[n][1] for n in owned) if owned else None, processes=len(owned))


class Lease:
    def __init__(self, root, output, budget, request, policy, labels):
        self.root, self.budget, self.request, self.policy = Path(root), budget, request, policy
        self.token = uuid.uuid4().hex
        self.attempt = Path(output)/self.token
        self.labels, self.commands = labels, []
        self.stop = threading.Event()
        self.monitor = None
        self.cpus, self.old_cpus, self.context_token = [], None, None
        self.started = time.monotonic()
        self.peak = None
        self.monitor_error = None
        self.owner = None
        self.sample_lock = threading.Lock()
        self.samples = 0
        self.descendant_samples = 0
        self.max_processes = 0
        self.last_sample = None
        self.max_sample_gap = 0.0
        self.burst_until = 0.0

    def status(self, phase, **extra):
        write_json(self.attempt/'status.json', dict(created=now(), phase=phase,
                   enforcement='observe_only', request=self.request, cpu_ids=self.cpus,
                   rss_kind='sampled_process_tree_sum_including_shared_pages',
                   rss_peak_bytes=self.peak, elapsed_seconds=time.monotonic()-self.started,
                   telemetry=dict(samples=self.samples, descendant_samples=self.descendant_samples,
                       max_processes=self.max_processes, max_sample_gap_seconds=self.max_sample_gap,
                       quality='descendants_observed' if self.descendant_samples else 'parent_only',
                       exact_peak=False, burst_interval_seconds=0.25, burst_seconds=10,
                       steady_interval_seconds=self.policy['poll_seconds']),
                   sampled_peak_exceeds_request=(self.peak>self.request['mem_mb']*1048576) if self.peak is not None else None,
                   labels=self.labels, owner=self.owner, **extra))

    def __enter__(self):
        from .runtime import process_identity
        if not sys.platform.startswith('linux'):
            raise WorkflowError('Runtime observation and leases require Linux')
        self.owner = process_identity(os.getpid())
        self.old_cpus = set(os.sched_getaffinity(0))
        candidates = sorted(self.old_cpus)[:self.budget['threads']]
        if len(candidates) < self.budget['threads']:
            raise WorkflowError('Configured pool exceeds CPU affinity available to this process')
        while True:
            from .control import check_cancelled
            check_cancelled()
            waiting = None
            with transaction(self.root) as state:
                leases = state['leases']
                if any(identity_alive(r['owner']) is not True for r in leases.values()):
                    raise WorkflowError('Dead/unverified runtime lease; use runtime-status then runtime-reconcile')
                if leases and (state['budget'] != self.budget or state['cpu_ids'] != candidates):
                    raise WorkflowError('Active pool budget/affinity differs; do not mix controllers')
                taken = {n for r in leases.values() for n in r['cpu_ids']}
                free = [n for n in candidates if n not in taken]
                if (len(free) < self.request['threads'] or len(leases) >= self.budget['jobs'] or
                    sum(r['request']['mem_mb'] for r in leases.values())+self.request['mem_mb'] > self.budget['mem_mb'] or
                    sum(r['request']['io'] for r in leases.values())+self.request['io'] > self.budget['io']):
                    waiting = 'resource_reservations'
                avail = available_mb()
                # Reserve the not-yet-observed portion of existing jobs as well as the new request.
                future = 0
                for rec in leases.values():
                    sp = Path(rec['attempt'])/'status.json'
                    obs = read_json(sp) if sp.exists() else {}
                    observed_mb = (obs.get('rss_bytes') or 0)/1048576
                    future += max(0,rec['request']['mem_mb']-observed_mb)
                if avail is None:
                    waiting = 'memory_availability_unknown'
                elif avail < self.policy['memory_headroom_mb']+future+self.request['mem_mb']:
                    waiting = 'node_memory_pressure'
                if waiting is None:
                    self.cpus = free[:self.request['threads']]
                    state.update(budget=self.budget, cpu_ids=candidates)
                    leases[self.token] = dict(owner=self.owner, cpu_ids=self.cpus,
                        request=self.request, attempt=str(self.attempt), labels=self.labels, commands=[])
            if waiting is None: break
            self.status('waiting', reason=waiting, node_available_mb=avail)
            if time.monotonic()-self.started >= self.policy['admission_timeout_seconds']:
                self.status('admission_timeout', reason=waiting)
                raise WorkflowError('Admission timed out ('+waiting+'); no analysis started; inspect '+str(self.attempt))
            time.sleep(min(self.policy['poll_seconds'],1))
        try:
            os.sched_setaffinity(0,self.cpus)
            (self.attempt/'tmp').mkdir(parents=True)
            self.context_token = CURRENT.set(self)
            self._sample()
            self.monitor = threading.Thread(target=self._monitor, daemon=True)
            self.monitor.start()
            return self
        except BaseException:
            self.__exit__(*sys.exc_info())
            raise

    def _sample(self, reason='periodic'):
        with self.sample_lock:
            self._sample_locked(reason)

    def _sample_locked(self, reason):
        rec = process_tree(os.getpid())
        tick = time.monotonic()
        if self.last_sample is not None:
            self.max_sample_gap = max(self.max_sample_gap, tick-self.last_sample)
        self.last_sample = tick
        self.samples += 1
        self.descendant_samples += int(rec['processes'] > 1)
        self.max_processes = max(self.max_processes, rec['processes'])
        if rec['rss_bytes'] is not None:
            self.peak = max(self.peak or 0, rec['rss_bytes'])
        available = available_mb()
        self.status('running', **rec, node_available_mb=available,
                    node_below_headroom=available<self.policy['memory_headroom_mb'] if available is not None else None)
        with (self.attempt/'metrics.jsonl').open('a',encoding='utf-8') as f:
            f.write(json.dumps(dict(at=now(),elapsed=tick-self.started,reason=reason,**rec))+'\n')

    def _monitor(self):
        try:
            while not self.stop.wait(min(0.25, self.policy['poll_seconds'])):
                tick = time.monotonic()
                if tick < self.burst_until or self.last_sample is None or tick-self.last_sample >= self.policy['poll_seconds']:
                    self._sample()
        except Exception as e:
            self.monitor_error = type(e).__name__+': '+str(e)

    def register(self, command):
        # Record before waiting: a killed worker leaves enough evidence to refuse unsafe reuse.
        self.commands.append(dict(command))
        with transaction(self.root) as state:
            state['leases'][self.token]['commands'] = self.commands
            state['leases'][self.token]['spawn_in_progress'] = False
        # Capture short tools as well as the worker. Burst is reset for every
        # command; after ten seconds the configured steady interval applies.
        self.burst_until = time.monotonic()+10
        try:
            self._sample('command_started')
        except Exception as e:
            self.monitor_error = type(e).__name__+': '+str(e)

    def before_spawn(self):
        from .control import check_cancelled
        check_cancelled()
        with transaction(self.root) as state:
            state['leases'][self.token]['spawn_in_progress'] = True

    def spawn_failed(self):
        with transaction(self.root) as state:
            state['leases'][self.token]['spawn_in_progress'] = False

    def check_quiescent(self):
        from .runtime import group_alive
        if any(group_alive(r) for r in self.commands):
            raise WorkflowError('Command descendants remain live; completion and resource release withheld')

    def __exit__(self, exc_type, exc, tb):
        self.stop.set()
        if self.monitor: self.monitor.join(timeout=max(5,self.policy['poll_seconds']))
        try:
            self._sample('stage_finished')
        except Exception as e:
            self.monitor_error = type(e).__name__+': '+str(e)
        try:
            self.check_quiescent()
        except BaseException:
            self.status('unresolved_children', error=str(exc) if exc else None)
            raise
        else:
            self.status('failed' if exc else 'complete', error=str(exc) if exc else None,
                        monitor_error=self.monitor_error)
            with transaction(self.root) as state:
                state['leases'].pop(self.token,None)
        finally:
            if self.context_token is not None: CURRENT.reset(self.context_token)
            if self.old_cpus is not None: os.sched_setaffinity(0,self.old_cpus)
