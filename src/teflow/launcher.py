"""Unified Linux launcher. Same freeze, probes and scheduler limits as the legacy shell."""
import importlib.util
import os
from pathlib import Path
import sys
import uuid
import signal
import subprocess
import threading
import time
from .assets import asset_path, asset_root
from .branches import graph
from .common import WorkflowError, load_config, now, write_json, work
from .inputs import audit_sample
from .runtime import freeze
from .stages import doctor
from .resource_pool import acquire_controller


def run_root(c):
    return Path(c["work_root"]) / c["run_id"]


def validate_launch(c, target=None, environ=None):
    if c["execution"]["mode"] != "server":
        raise WorkflowError("Production launcher requires execution.mode=server")
    if c["execution"]["threads"] < 4:
        raise WorkflowError("RepeatMasker requires at least 4 workflow threads")
    if target and target not in graph(c):
        raise WorkflowError("Target stage is not enabled: " + target)
    environ = os.environ if environ is None else environ
    cores, mem = (c["execution"][k] for k in ("threads", "mem_mb"))
    def allocation(name):
        value = environ.get(name)
        if value is None or value == "":
            return None
        try:
            result = int(value)
        except ValueError as e:
            raise WorkflowError("Invalid Slurm allocation: " + name) from e
        if result < 1:
            raise WorkflowError("Invalid Slurm allocation: " + name)
        return result
    cpus = allocation("SLURM_CPUS_PER_TASK")
    if cpus and cores > cpus:
        raise WorkflowError("Frozen thread budget exceeds Slurm allocation")
    node_mem = allocation("SLURM_MEM_PER_NODE")
    cpu_mem = allocation("SLURM_MEM_PER_CPU")
    # One task/node launcher: reject a configuration beyond either advertised bound.
    limits = [n for n in (node_mem, cpu_mem * cpus if cpu_mem and cpus else None) if n is not None]
    if limits and mem > min(limits):
        raise WorkflowError("Frozen memory budget exceeds Slurm allocation")


def scheduler_command(c, dry_run=False, resume=False, target=None):
    from .resources import policy
    p = policy(c)
    if dry_run and resume:
        raise WorkflowError("Select one execution mode: --dry-run or --resume")
    argv = [sys.executable, "-m", "snakemake", "--snakefile", str(asset_path("workflow/Snakefile")),
            "--directory", str(run_root(c)), "--cores", str(c["execution"]["threads"]),
            "--resources", "mem_mb=" + str(c["execution"]["mem_mb"]), "io_heavy="+str(p['io_slots']),
            "stage_slots="+str(p['max_jobs']), "--printshellcmds",
            "--config", "teflow_config=" + c["_config_path"]]
    if resume:
        argv += ["resume=1", "--rerun-incomplete"]
    if dry_run:
        argv.append("--dry-run")
    if p['keep_going']:
        argv.append('--keep-going')
    if target:
        argv += ["--"] + [str(work(c, s["id"]) / ".dag" / (target + ".done")) for s in c["samples"]]
    return argv


def check_project(args):
    c = load_config(args.config)
    dependencies = not args.versions_only
    if dependencies and sys.platform != "linux":
        raise WorkflowError("Dependency execution requires Linux; use validate-inputs for a portable input audit")
    attempt = run_root(c) / "checks" / uuid.uuid4().hex
    result = dict(created=now(), status="running", config=c["_config_path"], dependencies_checked=dependencies,
                  frozen=False, computation_scope="Input audit and installation probes; no genome discovery")
    write_json(attempt / "check.json", result)
    try:
        audits = [audit_sample(s) for s in c["samples"]]
        write_json(attempt / "inputs.json", dict(samples=audits))
        result["doctor"] = doctor(c, attempt / "doctor", dependencies)
        result["status"] = "pass"
    except (WorkflowError, OSError, KeyError, ValueError) as e:
        result.update(status="fail", error=str(e))
        write_json(attempt / "check.json", result)
        raise WorkflowError(str(e) + "; check report: " + str(attempt / "check.json")) from e
    write_json(attempt / "check.json", result)
    return dict(status="pass", report=str(attempt / "check.json"), dependencies_checked=dependencies,
                frozen=False, next="teflow run --config CONFIG --dry-run (freezes this run and checks the DAG)")


def launch(args):
    c = load_config(args.config)
    validate_launch(c, args.target_stage)
    if sys.platform != "linux":
        raise WorkflowError("Production and scheduler dry-run require Linux")
    if importlib.util.find_spec("snakemake") is None:
        raise WorkflowError("Snakemake missing; install the [engine] extra or the engine environment")
    argv = scheduler_command(c, args.dry_run, args.resume, args.target_stage)
    from .resources import pool_root
    from .runtime import process_identity
    token = uuid.uuid4().hex
    folder = run_root(c)/'launches'/token
    record = dict(schema_version=1, control_protocol=1, attempt_id=token, created=now(), status='preflight',
                  owner=process_identity(os.getpid()), run_id=c['run_id'], config=c['_config_path'],
                  mode='dry-run' if args.dry_run else 'resume' if args.resume else 'run',
                  target_stage=args.target_stage, command=argv)
    controller_fd = acquire_controller(pool_root(c), record)
    log = folder.with_suffix('.json')
    handlers = {}
    old_env = {k: os.environ.get(k) for k in ('TEFLOW_CANCEL_FILE','TEFLOW_LAUNCH_ID','TEFLOW_IDENTITY_CACHE')}
    def save(**updates):
        record.update(updates)
        write_json(log, record)
        write_json(pool_root(c)/'controller.json', record)
    def interrupt(signum, frame):
        from .control import write_request
        write_request(folder/'cancel.json', token, 'launcher signal '+str(signum))
    try:
        folder.mkdir(parents=True, exist_ok=False)
        os.environ.update(TEFLOW_CANCEL_FILE=str(folder/'cancel.json'), TEFLOW_LAUNCH_ID=token,
                          TEFLOW_IDENTITY_CACHE=str(pool_root(c)/'identity-cache.sqlite'))
        for sig in (signal.SIGINT, signal.SIGTERM):
            handlers[sig] = signal.signal(sig, interrupt)
        save()
        print("teflow: launcher receipt " + str(log), file=sys.stderr, flush=True)
        return _dispatch(c, args, argv, folder, save, controller_fd)
    except BaseException as e:
        from .control import cancellation_requested
        from .resource_pool import inspect_pool
        unresolved = list(inspect_pool(pool_root(c))['leases'])
        save(status='cleanup_unresolved' if unresolved else 'cancelled' if cancellation_requested() else 'failed',
             unresolved_leases=unresolved,
             phase='preflight_or_dispatch', finished=now(), error=type(e).__name__+': '+str(e))
        raise
    finally:
        for sig, handler in handlers.items():
            signal.signal(sig, handler)
        for key, value in old_env.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value
        os.close(controller_fd)


def _dispatch(c,args,argv,folder,save,controller_fd):
    from .resources import pool_root
    from .control import check_cancelled, cancellation_requested
    from .reporting import preview
    # Keep the original ordering: changed frozen inputs stop before probes or scheduling.
    check_cancelled()
    frozen = freeze(c)
    check_cancelled()
    doctor(c, run_root(c) / "doctor", True)
    check_cancelled()
    env = dict(os.environ, TEFLOW_REPOSITORY=str(asset_root()), TEFLOW_ALLOW_PRODUCTION="1", PYTHONUNBUFFERED="1",
               OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    scope = preview(c, args.target_stage)
    write_json(folder/'preview.json', scope)
    print('teflow: scope '+str(scope['counts'])+'; scheduler log '+str(folder/'scheduler.log'), file=sys.stderr, flush=True)
    save(fingerprint=frozen['fingerprint'], preview=str(folder/'preview.json'), scheduler_log=str(folder/'scheduler.log'))
    # The supervisor retains its lock and records the final outcome. The scheduler
    # gets a private session, so a terminal signal cannot bypass cooperative cleanup.
    process = subprocess.Popen(argv, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               start_new_session=True, pass_fds=(controller_fd,))
    from .runtime import process_identity
    save(status='running', scheduler=process_identity(process.pid), dispatched=now())
    def copy_output():
        with (folder/'scheduler.log').open('wb') as output:
            for block in iter(process.stdout.readline, b''):
                output.write(block); output.flush()
                try:
                    sys.stdout.write(block.decode('utf-8',errors='replace')); sys.stdout.flush()
                except (OSError, ValueError):
                    pass
    reader = threading.Thread(target=copy_output, daemon=True)
    reader.start()
    stop_sent = False
    try:
        while process.poll() is None:
            if cancellation_requested() and not stop_sent:
                save(status='cancelling', cancel_requested=now())
                # This is our unreaped Popen child, never a PID loaded from disk.
                process.send_signal(signal.SIGINT)
                stop_sent = True
            time.sleep(0.1)
        code = process.wait()
    except BaseException:
        from .control import write_request
        write_request(folder/'cancel.json', folder.name, 'supervisor exception')
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
            process.wait()
        raise
    finally:
        reader.join(timeout=5)
        process.stdout.close()
    # Snakemake may return while a stage is still recording its cleanup.
    from .resource_pool import inspect_pool
    deadline = time.monotonic()+30
    while True:
        leases = inspect_pool(pool_root(c))['leases']
        if not leases or time.monotonic() >= deadline: break
        time.sleep(0.1)
    cancelled = cancellation_requested()
    state = ('cancelled' if cancelled else 'dry_run_passed' if args.dry_run else 'succeeded') if code == 0 or cancelled else 'failed'
    if leases:
        state = 'cleanup_unresolved'
    save(status=state, finished=now(), scheduler_returncode=code, unresolved_leases=list(leases),
         note='Run receipts describe execution; report/status describe artifacts and scientific limitations')
    return 130 if cancelled and not leases else 1 if leases or code else 0
