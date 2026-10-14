"""Phase 4: no external sends, isolated scratch files, unsigned approval denied."""
from __future__ import annotations
from fixtures.baseline_loader import original_seen_bytes
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
import yaml

import run
import events_run
from sources import notify, approval
from sources.filters import is_ireland, scope_of, filter_jobs
from sources.outbox import empty_outbox, enqueue, record_delivery, pending_count
from sources.state import save_json, validate_seen, StateError
from scripts.state_recovery import snapshot, restore, digest, BASELINE_COUNT, BASELINE_HASH

ROOT = Path(__file__).resolve().parents[1]
CFG = yaml.safe_load((ROOT / 'config.yaml').read_text())


def job(location, description='', **kwargs):
    return dict(id='phase4', title='Graduate Developer', location=location, description=description,
                company='Example', source='mock', posted='2026-10-14', link='https://example.invalid', **kwargs)


class GeographyCases(unittest.TestCase):
    def test_usa_dublin_ohio(self):
        self.assertNotEqual(scope_of(job('Dublin, Ohio, United States'),CFG),'ireland')
        self.assertFalse(is_ireland('Dublin, Ohio, USA'))
    def test_usa_dublin_california(self):
        self.assertNotEqual(scope_of(job('Dublin, California, USA'),CFG),'ireland')
        self.assertFalse(is_ireland('Dublin, California, USA'))
    def test_usa_separate_country_field(self):
        self.assertEqual(scope_of(job('Dublin', country='United States'),CFG),'eligibility_unverified')
    def test_physical_override(self):
        self.assertEqual(scope_of(job('Dublin, Ireland', physical_location='California, USA'),CFG),'eligibility_unverified')
    def test_northern_ireland(self):
        for location in ('Belfast, Northern Ireland','Derry, Northern Ireland','Dublin / Belfast'):
            with self.subTest(location=location):
                self.assertNotEqual(scope_of(job(location),CFG),'ireland')
    def test_explicit_uk_only_overrides_roi(self):
        self.assertIsNone(scope_of(job('Dublin, Ireland - UK only'),CFG))
        self.assertIsNone(scope_of(job('Cork, Ireland', employer_restrictions='Applicants must be based in the UK'),CFG))
    def test_explicit_us_only_overrides_roi(self):
        self.assertIsNone(scope_of(job('Dublin, Ireland', description='Remote work: United States only'),CFG))
    def test_emea_unknown(self):
        self.assertEqual(scope_of(job('Remote - EMEA'), CFG),'eligibility_unverified')
    def test_emea_unknown_not_alerted(self):
        k,u,c=filter_jobs([job('Remote EMEA')],CFG)
        self.assertFalse(k);self.assertEqual(len(u),1)
    def test_cork_ireland(self):
        self.assertEqual(scope_of(job('Cork, Ireland'), CFG),'ireland')
    def test_dublin_ireland(self):
        self.assertEqual(scope_of(job('Dublin, Ireland'), CFG),'ireland')
    def test_foreign_country_overrides_eu_remote(self):
        self.assertEqual(scope_of(job('Remote - EU', country='United States'),CFG),'eligibility_unverified')
        self.assertEqual(scope_of(job('Remote - Europe', physical_location='California'),CFG),'eligibility_unverified')

    def test_other_uk_applicant_only_restriction(self):
        self.assertIsNone(scope_of(job('Cork, Ireland','UK applicants only'),CFG))

    def test_eu_explicit(self):
        self.assertEqual(scope_of(job('Remote - European Union'),CFG),'eu_remote')
        self.assertEqual(scope_of(job('Remote - EU (Ireland eligible)'),CFG),'eu_remote')
    def test_eu_remote_explicit_restriction(self):
        self.assertIsNone(scope_of(job('Remote — EU', employer_restrictions='UK only'),CFG))
    def test_no_unknown_to_ireland(self):
        self.assertIsNone(scope_of(job('Fully Remote'),CFG))
    def test_visa_negative_precedence(self):
        self.assertIsNone(scope_of(job('Berlin, Germany','No visa sponsorship',sponsors_visa=True), CFG))


class RuntimeSafety(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir=Path(self.tmp.name)
        seen=self.dir/'seen.json'; seen.write_text('{"test":"2026-10-14"}')
        outbox=self.dir/'outbox.json'; outbox.write_text('{"schema_version":1,"jobs":{}}')
        disc=self.dir/'discovery.json'; disc.write_text('{"linkedin_last_sweep_at":""}')
        paths={'SEEN_FILE':seen,'OUTBOX_FILE':outbox,'DISCOVERY_FILE':disc}
        for k,v in paths.items():
            pp=patch.object(run,k,v);pp.start();self.addCleanup(pp.stop)
        self.paths=[seen,outbox,disc]

    def test_readonly_dry_run_no_sources(self):
        before=[p.read_bytes() for p in self.paths]
        with patch.object(run,'prepare',side_effect=AssertionError('prepare called')) as prep,\
             patch.object(run,'deliver',side_effect=AssertionError('delivery called')) as delivery:
            self.assertEqual(run.main(['--dry-run']),0)
            prep.assert_not_called(); delivery.assert_not_called()
        self.assertEqual(before,[p.read_bytes() for p in self.paths])

    def test_production_prepare_requires_explicit_stage(self):
        before=[p.read_bytes() for p in self.paths]
        with patch.object(run,'prepare',return_value=0) as prep:
            self.assertEqual(run.main(['--prepare']),0)
            prep.assert_called_once()
        self.assertEqual(before,[p.read_bytes() for p in self.paths])

    def test_staging_prepare_still_denied(self):
        before=[p.read_bytes() for p in self.paths]
        staging_cfg=dict(CFG, runtime={'mode':'staging', 'dry_run':True})
        with patch.object(run,'load_yaml',return_value=staging_cfg), \
             patch.object(run,'prepare',side_effect=AssertionError('unsafe')) as prep:
            self.assertEqual(run.main(['--prepare']),3)
            prep.assert_not_called()
        self.assertEqual(before,[p.read_bytes() for p in self.paths])

    def test_deliver_denied_even_fake_credentials(self):
        env=dict(EMAIL_PASSWORD='dummy',EMAIL_SENDER='dummy',EMAIL_RECIPIENT='dummy',
                 TELEGRAM_BOT_TOKEN='dummy',TELEGRAM_CHAT_ID='dummy',
                 GITHUB_RUN_ID='1234', APPROVED='true')
        with patch.dict(os.environ,env),patch.object(run,'deliver') as send:
            self.assertEqual(run.main(['--deliver']),3)
            send.assert_not_called()

    def test_default_invocation_denied(self):
        with patch.object(run,'prepare') as prep,patch.object(run,'deliver') as dl:
            self.assertEqual(run.main([]),3)
            prep.assert_not_called();dl.assert_not_called()

    def test_production_requires_signed_channel_grants(self):
        self.assertEqual(CFG['runtime']['mode'],'production')
        # A test's result must not depend on any secrets added to the CI environment.
        with patch.dict(os.environ, {}, clear=True):
            for c in approval.CHANNELS:
                self.assertEqual(CFG['notifications'][c]['enabled'], c!='events_email')
                self.assertFalse(approval.approved(c,CFG))

    def test_config_and_inputs_cannot_bypass(self):
        cfg=dict(CFG)
        cfg['runtime']={'mode':'production'}
        cfg['notifications']={x:{'enabled':True} for x in approval.CHANNELS}
        with patch.dict(os.environ,{'GITHUB_RUN_ID':'42','EMAIL_PASSWORD':'fake','ENABLE_TELEGRAM':'true'}):
            for c in approval.CHANNELS:
                with self.subTest(c=c):self.assertFalse(approval.approved(c,cfg))

    def test_transport_no_smtp_telegram_network(self):
        with patch.dict(os.environ,{'EMAIL_PASSWORD':'dummy','EMAIL_SENDER':'a','EMAIL_RECIPIENT':'b',
                                    'TELEGRAM_BOT_TOKEN':'dummy','TELEGRAM_CHAT_ID':'dummy'}),\
             patch('sources.notify.smtplib.SMTP_SSL') as smtp,\
             patch('sources.notify.requests.post') as http:
            self.assertFalse(notify.send_email([job('Cork')],[]))
            self.assertFalse(notify.send_telegram([job('Cork')]))
            smtp.assert_not_called();http.assert_not_called()

    def test_events_gate_before_source_and_transport(self):
        with patch('events_run.collect_events',side_effect=AssertionError('network')) as collect,\
             patch('events_run.smtplib.SMTP_SSL') as smtp:
            self.assertEqual(events_run.main(),3)
            collect.assert_not_called();smtp.assert_not_called()

    def test_production_static_guard(self):
        cmd=subprocess.run([sys.executable,str(ROOT/'scripts/production_verify.py')],cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(cmd.returncode,0,cmd.stderr)

    def test_persistence_refused_without_trusted_actions_context(self):
        # Never execute a state-push script with CI credentials inside the real checkout.
        # Only verify its fail-closed guard with all privileged context removed.
        env={k:v for k,v in os.environ.items()
             if k not in ('GITHUB_ACTIONS','GITHUB_REPOSITORY','GITHUB_REF_NAME',
                          'GITHUB_TOKEN','GH_TOKEN')}
        cmd=subprocess.run([sys.executable,str(ROOT/'scripts/persist_state.py'),'main'],
                           cwd=self.dir,env=env,capture_output=True,text=True)
        self.assertNotEqual(cmd.returncode,0)
        self.assertIn('outside production GitHub Actions',cmd.stderr)

    def test_signed_per_channel_approval_in_disposable_fixture(self):
        # No production keys/secret material: ephemeral key generated and discarded.
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            from cryptography.hazmat.primitives import serialization
        except ImportError:
            self.skipTest('cryptography unavailable in isolated interpreter')
        (self.dir/'security').mkdir();(self.dir/'approvals').mkdir()
        private=Ed25519PrivateKey.generate()
        public=private.public_key().public_bytes(serialization.Encoding.PEM,
                                                  serialization.PublicFormat.SubjectPublicKeyInfo)
        (self.dir/'security/operator_public_key.pem').write_bytes(public)
        now=datetime.now(timezone.utc)
        payload={'channel':'email','environment':'production','run_id':'983374',
                 'issued_at':(now-timedelta(minutes=1)).isoformat(),
                 'expires_at':(now+timedelta(minutes=10)).isoformat()}
        signed=json.dumps(payload,sort_keys=True,separators=(',',':')).encode()
        doc={'grant':payload,'signature':private.sign(signed).hex()}
        (self.dir/'approvals/email.json').write_text(json.dumps(doc))
        cfg={'runtime':{'mode':'production'},'notifications':{x:{'enabled':True} for x in approval.CHANNELS}}
        with patch.object(approval,'ROOT',self.dir),patch.dict(os.environ,{'GITHUB_RUN_ID':'983374'}):
            self.assertTrue(approval.approved('email',cfg))
            self.assertFalse(approval.approved('telegram',cfg))
            self.assertFalse(approval.approved('events_email',cfg))
            self.assertTrue(approval.approved('email',CFG))
            staging_cfg={'runtime':{'mode':'staging'},
                         'notifications':{'email':{'enabled':True}}}
            self.assertFalse(approval.approved('email',staging_cfg))
            broken=dict(doc, signature='00'*64)
            (self.dir/'approvals/email.json').write_text(json.dumps(broken))
            self.assertFalse(approval.approved('email',cfg))
            (self.dir/'approvals/email.json').write_text(json.dumps(doc))
            with patch.dict(os.environ,{'GITHUB_RUN_ID':'different'}):
                self.assertFalse(approval.approved('email',cfg))


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.source=self.root/'source';self.source.mkdir();(self.source/'data').mkdir()
        self.target=self.root/'scratch'; self.target.mkdir();(self.target/'data').mkdir()
        (self.target/'.phase4_disposable').touch()
        self.snap=self.root/'snap'
        # Preserve full original 93,296 ID baseline in every snapshot test.
        (self.source/'data/seen_jobs.json').write_bytes(original_seen_bytes())
        self.baseline=self.root/'baseline_seen_jobs.json'
        self.baseline.write_bytes(original_seen_bytes())
        (self.source/'data/notification_outbox.json').write_text('{"schema_version":1,"jobs":{}}')
        (self.source/'data/discovery_state.json').write_text('{"linkedin_last_sweep_at":""}')

    def test_snapshot_baseline_preserved(self):
        m=snapshot(self.source,self.snap)
        self.assertEqual(m['baseline_seen_count'],BASELINE_COUNT)
        self.assertEqual(m['files']['seen_jobs.json']['sha256'],BASELINE_HASH)
        self.assertEqual(len(json.loads((self.snap/'seen_jobs.json').read_text())),BASELINE_COUNT)

    def test_recovery_merges_seen_pending_receipts_and_watermark(self):
        old=json.loads((self.source/'data/seen_jobs.json').read_text());
        old['snapshot_extra']='2026-10-14'
        (self.source/'data/seen_jobs.json').write_text(json.dumps(old))
        ob=enqueue(empty_outbox(),[job('Cork, Ireland')],[])
        ob['jobs']['phase4']['job']['id']='phase4'
        record_delivery(ob['jobs']['phase4'],'email',True)
        (self.source/'data/notification_outbox.json').write_text(json.dumps(ob))
        (self.source/'data/discovery_state.json').write_text('{"linkedin_last_sweep_at":"2026-10-12T10:00:00+00:00"}')
        snapshot(self.source,self.snap,self.baseline)
        # Simulate newer state arriving between snapshot and failed deployment.
        newest={'newer_job':'2026-10-14'}
        (self.target/'data/seen_jobs.json').write_text(json.dumps(newest))
        newer=enqueue(empty_outbox(),[job('Cork, Ireland')],[])
        record_delivery(newer['jobs']['phase4'],'telegram',True)
        late=job('Cork, Ireland'); late['id']='late_pending'
        enqueue(newer,[late],[])
        record_delivery(newer['jobs']['late_pending'],'email',False)
        (self.target/'data/notification_outbox.json').write_text(json.dumps(newer))
        (self.target/'data/discovery_state.json').write_text('{"linkedin_last_sweep_at":"2026-10-14T10:00:00+00:00"}')
        r=restore(self.snap,self.target)
        seen=json.loads((self.target/'data/seen_jobs.json').read_text())
        out=json.loads((self.target/'data/notification_outbox.json').read_text())
        self.assertEqual(r['seen_ids'],BASELINE_COUNT+2)
        self.assertIn('snapshot_extra',seen);self.assertIn('newer_job',seen)
        self.assertEqual(out['jobs']['phase4']['channels']['email']['status'],'sent')
        self.assertEqual(out['jobs']['phase4']['channels']['telegram']['status'],'sent')
        self.assertEqual(out['jobs']['late_pending']['channels']['email']['status'],'pending')
        self.assertEqual(out['jobs']['late_pending']['channels']['email']['attempts'],1)
        self.assertIn('last_error',out['jobs']['late_pending']['channels']['email'])
        self.assertEqual(json.loads((self.target/'data/discovery_state.json').read_text())['linkedin_last_sweep_at'],
                         '2026-10-14T10:00:00+00:00')
        self.assertTrue((self.target/'.phase4_recovery_journal').is_dir())

    def test_snapshot_capture_pending_and_receipts(self):
        ob=enqueue(empty_outbox(),[job('Cork, Ireland')],[])
        record_delivery(ob['jobs']['phase4'],'email',True)
        m=snapshot(self.source,self.snap)
        self.assertEqual(m['files']['notification_outbox.json']['pending_channels'],0)
        self.assertEqual(m['files']['notification_outbox.json']['sent_channels'],0)
        # Snapshot integrity is based on the bytes that actually existed.
        self.assertEqual(m['files']['notification_outbox.json']['sha256'],digest(
            (self.source/'data/notification_outbox.json').read_bytes()))

    def test_corrupt_state_quarantined_before_restore(self):
        snapshot(self.source,self.snap)
        (self.target/'data/seen_jobs.json').write_text('{bad')
        r=restore(self.snap,self.target)
        self.assertEqual(len(json.loads((self.target/'data/seen_jobs.json').read_text())),BASELINE_COUNT)
        self.assertIn('seen_jobs.json',r['quarantined_corrupt'])
        self.assertEqual((self.target/'.phase4_recovery_journal/seen_jobs.json').read_text(),'{bad')

    def test_hash_mismatch_no_overwrite(self):
        snapshot(self.source,self.snap)
        (self.snap/'notification_outbox.json').write_text('{}')
        (self.target/'data/seen_jobs.json').write_text('{"newer":"2026-10-14"}')
        before=(self.target/'data/seen_jobs.json').read_bytes()
        with self.assertRaises(StateError): restore(self.snap,self.target)
        self.assertEqual((self.target/'data/seen_jobs.json').read_bytes(),before)

    def test_no_marker_no_restore(self):
        snapshot(self.source,self.snap)
        (self.target/'.phase4_disposable').unlink()
        with self.assertRaises(ValueError): restore(self.snap,self.target)

    def test_symlinked_data_directory_rejected(self):
        snapshot(self.source,self.snap)
        (self.target/'data').rmdir()
        (self.target/'data').symlink_to(self.source/'data',target_is_directory=True)
        with self.assertRaises(ValueError): restore(self.snap,self.target)

    def test_manifest_path_traversal_rejected(self):
        snapshot(self.source,self.snap)
        manifest=json.loads((self.snap/'manifest.json').read_text())
        manifest['files']['../outside.json']=manifest['files']['discovery_state.json']
        (self.snap/'manifest.json').write_text(json.dumps(manifest))
        with self.assertRaises(StateError): restore(self.snap,self.target)

    def test_git_checkout_no_restore(self):
        snapshot(self.source,self.snap)
        (self.target/'.git').mkdir()
        with self.assertRaises(ValueError): restore(self.snap,self.target)

    def test_opaque_receipt_snapshot_preserves_exact_bytes(self):
        (self.source/'data/delivery_receipts.bin').write_bytes(b'\x00receipt\xff')
        m=snapshot(self.source,self.snap)
        self.assertIn('delivery_receipts.bin',m['files'])
        restore(self.snap,self.target)
        self.assertEqual((self.target/'data/delivery_receipts.bin').read_bytes(),b'\x00receipt\xff')

    def test_rolling_backup_copy_preserved_in_snapshot(self):
        (self.source/'data/notification_outbox.json.bak').write_text('{"schema_version":1,"jobs":{}}')
        m=snapshot(self.source,self.snap)
        self.assertIn('notification_outbox.json.bak',m['files'])
        restore(self.snap,self.target)
        self.assertEqual(json.loads((self.target/'data/notification_outbox.json.bak').read_text())['jobs'],{})

    def test_receipt_file_additional_snapshot(self):
        (self.source/'data/delivery_receipts.json').write_text('{"job":"sent"}')
        m=snapshot(self.source,self.snap)
        self.assertIn('delivery_receipts.json',m['files'])
        restore(self.snap,self.target)
        self.assertEqual(json.loads((self.target/'data/delivery_receipts.json').read_text()),{'job':'sent'})

    def test_atomic_failed_write_retains_original(self):
        state=self.target/'data/seen_jobs.json'
        save_json(state,{'a':'2026-10-14'},validate_seen)
        with patch('sources.state.os.replace',side_effect=OSError('simulated crash')):
            with self.assertRaises(OSError): save_json(state,{'a':'2026-10-14','b':'2026-10-14'},validate_seen)
        self.assertEqual(json.loads(state.read_text()),{'a':'2026-10-14'})

    def test_corrupt_baseline_snapshot_refused(self):
        (self.source/'data/seen_jobs.json').write_text('{"missing_history":"2026-10-14"}')
        with self.assertRaises(StateError): snapshot(self.source,self.snap)


if __name__=='__main__':unittest.main()