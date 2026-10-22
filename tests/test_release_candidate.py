import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from teflow.common import WorkflowError, read_json, write_json
from teflow.control import cancel, cancellation_requested, check_cancelled, write_request
from teflow.reporting import runtime_summary, latest_launch, log_view


class ReleaseViews(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.c = dict(work_root=str(self.root/'work'),run_id='one',samples=[dict(id='plant')],
                      _config_path=str(self.root/'config.json'))

    def tearDown(self):
        self.temp.cleanup()

    def test_cancellation_requires_exact_attempt_not_stale_path(self):
        p = self.root/'cancel.json'
        with patch.dict(os.environ,TEFLOW_CANCEL_FILE=str(p),TEFLOW_LAUNCH_ID='a'):
            self.assertFalse(cancellation_requested())
            write_request(p,'a','test')
            original = p.read_bytes()
            write_request(p,'a','again')
            self.assertEqual(p.read_bytes(),original)
            with self.assertRaisesRegex(WorkflowError,'cancellation'): check_cancelled()
            with patch.dict(os.environ,TEFLOW_LAUNCH_ID='b'):
                with self.assertRaisesRegex(WorkflowError,'match'): cancellation_requested()

    def test_legacy_single_sample_does_not_claim_tool_peak(self):
        folder = self.root/'work/one/plant/.runtime/qc_edta/a'
        write_json(folder/'status.json',dict(phase='complete',rss_peak_bytes=20,elapsed_seconds=5))
        (folder/'metrics.jsonl').write_text('{"at":"2026-10-17T00:00:00+00:00","rss_bytes":20,"processes":1}\n')
        row = runtime_summary(self.c)['attempts'][0]
        self.assertEqual((row['quality'], row['samples']),('initial_only',1))
        self.assertFalse(runtime_summary(self.c)['exact_memory_peak'])

    def test_partial_metric_line_and_unavailable_observations_are_explicit(self):
        folder = self.root/'work/one/plant/.runtime/qc_edta/a'
        write_json(folder/'status.json',dict(phase='running'))
        (folder/'metrics.jsonl').write_text('{"at":')
        row = runtime_summary(self.c)['attempts'][0]
        self.assertTrue(row['metrics_incomplete'])
        self.assertEqual(row['quality'],'no_samples')

    def test_dead_launcher_is_interrupted_not_running(self):
        write_json(self.root/'work/one/launches/a.json',dict(status='running',owner={}))
        with patch('teflow.reporting.sys.platform','linux'), patch('teflow.resource_pool.identity_alive',return_value=False):
            self.assertEqual(latest_launch(self.c)['observed_state'],'interrupted_review')

    def test_log_tail_is_bounded(self):
        p = self.root/'large.log'
        p.write_text('x'*140000+'\nlast\n')
        write_json(self.root/'work/one/launches/a.json',dict(status='succeeded',scheduler_log=str(p)))
        data = log_view(self.c,lines=1)
        self.assertEqual(data['logs'][0]['tail'],'last')
        with self.assertRaises(WorkflowError): log_view(self.c,lines=0)


@unittest.skipUnless(sys.platform=='linux','Linux runtime ownership')
class CancellationOwnership(unittest.TestCase):
    setUp = ReleaseViews.setUp
    tearDown = ReleaseViews.tearDown

    def test_scheduler_retains_lock_if_supervisor_closes_its_fd(self):
        import subprocess
        from teflow.resource_pool import acquire_controller
        fd = acquire_controller(self.root/'pool')
        child = subprocess.Popen([sys.executable,'-c','import time;time.sleep(0.5)'],pass_fds=(fd,))
        os.close(fd)
        try:
            with self.assertRaisesRegex(WorkflowError,'Another TEflow'): acquire_controller(self.root/'pool')
        finally: child.wait(timeout=5)
        os.close(acquire_controller(self.root/'pool'))
    def test_wrong_run_and_old_protocol_do_not_create_request(self):
        from teflow.runtime import process_identity
        root = self.root/'work/.teflow-runtime'
        rec = dict(owner=process_identity(os.getpid()),control_protocol=1,run_id='other',
                   config=self.c['_config_path'],attempt_id='a',status='running')
        write_json(root/'controller.json',rec)
        with self.assertRaisesRegex(WorkflowError,'different'): cancel(self.c)
        rec['run_id']='one'; rec['control_protocol']=0
        write_json(root/'controller.json',rec)
        with self.assertRaisesRegex(WorkflowError,'predates'): cancel(self.c)
        self.assertFalse(list(self.root.rglob('cancel.json')))

    def test_dead_owner_cannot_be_cancelled(self):
        root = self.root/'work/.teflow-runtime'
        write_json(root/'controller.json',dict(owner={},control_protocol=1,run_id='one',
                   config=self.c['_config_path'],attempt_id='a',status='running'))
        with self.assertRaisesRegex(WorkflowError,'verified live'): cancel(self.c)
        self.assertFalse(list(self.root.rglob('cancel.json')))

    def test_modified_control_path_cannot_escape_launches(self):
        from teflow.runtime import process_identity
        root = self.root/'work/.teflow-runtime'
        write_json(root/'controller.json',dict(owner=process_identity(os.getpid()),control_protocol=1,run_id='one',
                   config=self.c['_config_path'],attempt_id='../elsewhere',status='running'))
        with self.assertRaisesRegex(WorkflowError,'attempt ID'): cancel(self.c)
        self.assertFalse(list(self.root.rglob('cancel.json')))

    def test_short_command_has_descendant_samples(self):
        from teflow.resource_pool import Lease
        from teflow.runtime import run
        lease = Lease(self.root/'pool',self.root/'attempt',dict(threads=1,mem_mb=256,jobs=1,io=1),
                      dict(threads=1,mem_mb=128,io=1),
                      dict(poll_seconds=10,memory_headroom_mb=0,admission_timeout_seconds=5),{})
        with lease:
            run([sys.executable,'-c','import time; data=bytearray(12000000); time.sleep(0.8)'],
                lease.attempt,lease.attempt/'child.log')
        r = read_json(lease.attempt/'status.json')
        self.assertGreater(r['telemetry']['samples'],2)
        self.assertGreater(r['telemetry']['descendant_samples'],0)
        self.assertEqual(r['phase'],'complete')


if __name__ == '__main__': unittest.main()
