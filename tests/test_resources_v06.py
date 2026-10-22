import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from teflow.common import WorkflowError, file_stamp, sha256, HASH_METRICS, _FILE_HASHES, read_json, write_json
from teflow.resources import validate, policy, stage_resources
from teflow.runtime import stage_copy
from teflow_runtime.login import login_state


class PolicyTests(unittest.TestCase):
    def config(self):
        return dict(schema_version=2,samples=[{'id':'s'}],execution=dict(mode='server',threads=16,mem_mb=8192),
                    branches={'edta':{'enabled':True},'hite':{'enabled':True}})

    def test_explicit_concurrency_preserves_heavy_defaults(self):
        c = self.config(); validate(c)
        self.assertEqual(stage_resources(c,'rm_edta')['threads'],16)
        c['execution']['scheduling'] = dict(mode='branches',max_jobs=2,io_slots=2)
        validate(c)
        self.assertEqual(stage_resources(c,'rm_edta'),dict(threads=4,mem_mb=4096,io=1))
        self.assertEqual(stage_resources(c,'edta')['threads'],16)
        c['execution']['scheduling']['stages'] = {'edta':{'threads':8,'mem_mb':4096}}
        validate(c)
        self.assertEqual(stage_resources(c,'edta')['threads'],8)

    def test_reject_impossible_resources_and_multi_species(self):
        for overrides in ({'threads':17},{'mem_mb':8193},{'io':3},{'threads':2}):
            c = self.config()
            c['execution']['scheduling'] = dict(mode='branches',max_jobs=2,io_slots=2,stages={'repeatmasker':overrides})
            with self.assertRaises(WorkflowError): validate(c)
        c=self.config(); c['execution']['scheduling']=dict(mode='branches',max_jobs=2,io_slots=2)
        c['samples'].append({'id':'second'})
        with self.assertRaisesRegex(WorkflowError,'exactly one'): validate(c)

    def test_staging_never_shares_inode_or_rewrites_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            a,b = Path(tmp)/'source',Path(tmp)/'target'
            a.write_bytes(b'original'*1024); stage_copy(a,b)
            self.assertEqual(a.read_bytes(),b.read_bytes())
            self.assertNotEqual(a.stat().st_ino,b.stat().st_ino)
            b.write_bytes(b'changed')
            self.assertTrue(a.read_bytes().startswith(b'original'))
            with self.assertRaises(WorkflowError): stage_copy(a,b)

    def test_cached_identity_reduces_read_bytes_and_invalidates_same_size_edit(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,{'TEFLOW_IDENTITY_CACHE':str(Path(tmp)/'cache.sqlite')}):
            p = Path(tmp)/'large'; p.write_bytes(b'a'*1048577)
            start=HASH_METRICS['bytes_read']; old=sha256(p)
            self.assertEqual(HASH_METRICS['bytes_read']-start,1048577)
            _FILE_HASHES.clear()
            self.assertEqual(sha256(p),old)
            self.assertEqual(HASH_METRICS['bytes_read']-start,1048577)
            p.write_bytes(b'b'*1048577)
            self.assertNotEqual(sha256(p),old)
            self.assertEqual(HASH_METRICS['bytes_read']-start,2097154)

    def test_closing_state_separate_from_active_flag(self):
        def call(argv,**kw):
            stdout = ('Linger=yes\nSessions=1 2\n' if argv[1]=='show-user' else
                      'Id=1\nState=online\nActive=yes\n' if argv[2]=='1' else
                      'Id=2\nState=closing\nActive=yes\n')
            return dict(returncode=0,stdout=stdout)
        with patch('teflow_runtime.login.os.getuid',return_value=1002,create=True), patch('teflow_runtime.login.call',side_effect=call):
            r=login_state(detailed=True)
        self.assertEqual((r['session_count'],r['active_or_online_sessions'],r['closing_sessions']),(2,1,1))


@unittest.skipUnless(sys.platform.startswith('linux'),'Linux local resource pool')
class LeaseTests(unittest.TestCase):
    def setUp(self):
        from teflow.resource_pool import Lease
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
        self.budget=dict(threads=min(2,len(os.sched_getaffinity(0))),mem_mb=128,jobs=2,io=2)
        self.request=dict(threads=1,mem_mb=64,io=1)
        self.policy=dict(memory_headroom_mb=0,poll_seconds=1,admission_timeout_seconds=1)
        self.Lease=Lease

    def tearDown(self): self.tmp.cleanup()

    def test_memory_pressure_starts_no_command_and_holds_no_lease(self):
        from teflow.resource_pool import inspect_pool
        with patch('teflow.resource_pool.available_mb',return_value=1):
            with self.assertRaisesRegex(WorkflowError,'node_memory_pressure'):
                with self.Lease(self.root/'pool',self.root/'attempt',self.budget,self.request,self.policy,{}):
                    self.fail('admitted despite pressure')
        self.assertFalse(inspect_pool(self.root/'pool')['leases'])

    def test_unreadable_process_identity_is_unknown_not_dead(self):
        from teflow.resource_pool import identity_alive
        from teflow.runtime import process_identity
        record=process_identity(os.getpid())
        with patch('pathlib.Path.read_text',side_effect=PermissionError('unreadable')):
            self.assertIsNone(identity_alive(record))

    def test_controller_lock_is_exclusive_and_released_by_close(self):
        from teflow.resource_pool import acquire_controller
        fd=acquire_controller(self.root)
        try:
            with self.assertRaisesRegex(WorkflowError,'Another TEflow'): acquire_controller(self.root)
        finally: os.close(fd)
        os.close(acquire_controller(self.root))

    def test_parallel_cpu_leases_tmpdirs_and_cleanup(self):
        if len(os.sched_getaffinity(0)) < 2:
            self.skipTest('Two disjoint CPU leases require at least two inherited CPUs')
        from teflow.resource_pool import inspect_pool
        program='''
import json,sys,time
from pathlib import Path
from teflow.resource_pool import Lease
from teflow.runtime import run
root=Path(sys.argv[1]); name=sys.argv[2]
with Lease(root/'pool',root/name,dict(threads=2,mem_mb=128,jobs=2,io=2),dict(threads=1,mem_mb=64,io=1),dict(memory_headroom_mb=0,poll_seconds=1,admission_timeout_seconds=10),dict(stage=name)) as lease:
    (root/(name+'.ready')).write_text(json.dumps(dict(cpu_ids=lease.cpus,tmp=str(lease.attempt/'tmp'))))
    run([sys.executable,'-c','import time; time.sleep(2)'],lease.attempt,lease.attempt/'child.log')
'''
        env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'))
        children=[subprocess.Popen([sys.executable,'-c',program,str(self.root),name],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for name in ('a','b')]
        try:
            import time
            until=time.monotonic()+10
            while len(list(self.root.glob('*.ready')))<2 and time.monotonic()<until: time.sleep(.05)
            a,b=[read_json(self.root/(name+'.ready')) for name in ('a','b')]
            self.assertFalse(set(a['cpu_ids']) & set(b['cpu_ids']))
            self.assertNotEqual(a['tmp'],b['tmp'])
            leases=inspect_pool(self.root/'pool')['leases']
            self.assertEqual(len(leases),2)
            self.assertEqual(sum(r['request']['mem_mb'] for r in leases.values()),128)
            for p in children:
                stdout,stderr=p.communicate(timeout=15)
                self.assertEqual(p.returncode,0,stderr)
            self.assertFalse(inspect_pool(self.root/'pool')['leases'])
        finally:
            for p in children:
                if p.poll() is None: p.terminate(); p.wait(timeout=5)

    def test_dead_owner_during_dispatch_cannot_be_auto_reclaimed(self):
        from teflow.resource_pool import transaction,reconcile
        from teflow.runtime import process_identity
        rec=dict(owner=dict(process_identity(os.getpid()),start_ticks='not-current'),attempt=str(self.root),commands=[],spawn_in_progress=True)
        with transaction(self.root) as state: state['leases']['test']=rec
        with self.assertRaisesRegex(WorkflowError,'during command dispatch'): reconcile(self.root)
        with transaction(self.root) as state: state['leases']['test']['spawn_in_progress']=False
        self.assertEqual(len(reconcile(self.root)['released']),1)

    def test_timeout_releases_lease_only_after_command_group_cleanup(self):
        from teflow.resource_pool import inspect_pool
        from teflow.runtime import run,group_alive
        lease=self.Lease(self.root/'pool',self.root/'timeout',self.budget,self.request,self.policy,{})
        with self.assertRaisesRegex(WorkflowError,'timed out'):
            with lease:
                run([sys.executable,'-c','import subprocess,sys,time; subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"]);time.sleep(30)'],
                    lease.attempt,lease.attempt/'child.log',timeout=.2)
        self.assertFalse(inspect_pool(self.root/'pool')['leases'])
        self.assertFalse(group_alive(read_json(lease.attempt/'child.log.command.json')))
        self.assertEqual(read_json(lease.attempt/'status.json')['phase'],'failed')


if __name__=='__main__': unittest.main()
