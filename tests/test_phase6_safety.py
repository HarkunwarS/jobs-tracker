"""Phase 6 release safety and disposable recovery assertions; never touches GitHub."""
from __future__ import annotations
from fixtures.baseline_loader import original_seen_bytes
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import yaml

from sources.approval import approved
from sources.outbox import empty_outbox, enqueue, record_delivery
from scripts.state_recovery import snapshot, restore, BASELINE_HASH, BASELINE_COUNT

ROOT = Path(__file__).resolve().parents[1]
STATES = ['seen_jobs.json', 'notification_outbox.json', 'discovery_state.json']


class OfflineReleaseSafety(unittest.TestCase):
    def state_hashes(self):
        return {name:(hashlib.sha256((ROOT/'data'/name).read_bytes()).hexdigest()
                      if (ROOT/'data'/name).exists() else None) for name in STATES}

    def test_production_discovery_workflow_is_controlled(self):
        cfg=yaml.safe_load((ROOT/'config.yaml').read_text())
        self.assertEqual(cfg['runtime']['mode'], 'production')
        self.assertIs(cfg['notifications']['events_email']['enabled'], False)
        wf=yaml.safe_load((ROOT/'.github/workflows/tracker.yml').read_text())
        triggers=wf.get('on', wf.get(True, {})) or {}
        self.assertIn('schedule', triggers)
        self.assertEqual(wf['permissions'], {'contents':'write'})
        self.assertIn("if: steps.gate.outputs.enabled", (ROOT/'.github/workflows/tracker.yml').read_text())
        self.assertNotIn('APPROVAL_GRANT', (ROOT/'.github/workflows/tracker.yml').read_text())
        events=yaml.safe_load((ROOT/'.github/workflows/events.yml').read_text())
        self.assertNotIn('schedule', events.get('on',events.get(True,{})) or {})
        self.assertTrue(approved('email',cfg))
        self.assertTrue(approved('telegram',cfg))
        self.assertFalse(approved('events_email',cfg))

    def test_no_mutation_from_read_only_dry_run(self):
        before=self.state_hashes()
        p=subprocess.run([sys.executable,'run.py','--dry-run'],cwd=ROOT,
                         capture_output=True,text=True,timeout=20)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(before,self.state_hashes())

    def test_disposable_rollback_preserves_pending_sent_and_newer_ids(self):
        with tempfile.TemporaryDirectory(prefix='phase6_restore_') as tmp:
            root=Path(tmp);source=root/'original';(source/'data').mkdir(parents=True)
            (source/'data/seen_jobs.json').write_bytes(original_seen_bytes())
            archived=json.loads((source/'data/seen_jobs.json').read_text())
            self.assertEqual(len(archived),BASELINE_COUNT)
            ob=enqueue(empty_outbox(),[{'id':'receipt','title':'test', 'location':'Cork, Ireland'}],[])
            record_delivery(ob['jobs']['receipt'],'email',True)
            ob=enqueue(ob,[{'id':'retry','title':'test','location':'Dublin, Ireland'}],[])
            record_delivery(ob['jobs']['retry'],'email',False,error='synthetic transport failure')
            (source/'data/notification_outbox.json').write_text(json.dumps(ob))
            (source/'data/discovery_state.json').write_text('{"linkedin_last_sweep_at":"2026-10-10T10:00:00+00:00"}')
            snap=root/'backup';manifest=snapshot(source,snap)
            self.assertEqual(manifest['baseline_seen_sha256'],BASELINE_HASH)
            target=root/'restore';(target/'data').mkdir(parents=True)
            (target/'.phase4_disposable').touch()
            (target/'data/seen_jobs.json').write_text('{"newer-id":"2026-10-14"}')
            (target/'data/notification_outbox.json').write_text('{"schema_version":1,"jobs":{}}')
            (target/'data/discovery_state.json').write_text('{"linkedin_last_sweep_at":"2026-10-14T10:00:00+00:00"}')
            restored=restore(snap,target)
            seen=json.loads((target/'data/seen_jobs.json').read_text())
            got=json.loads((target/'data/notification_outbox.json').read_text())
            discovery=json.loads((target/'data/discovery_state.json').read_text())
            self.assertEqual(restored['seen_ids'],BASELINE_COUNT+1)
            self.assertIn('newer-id',seen)
            self.assertEqual(got['jobs']['receipt']['channels']['email']['status'],'sent')
            self.assertEqual(got['jobs']['retry']['channels']['email']['status'],'pending')
            self.assertEqual(got['jobs']['retry']['channels']['email']['attempts'],1)
            self.assertEqual(discovery['linkedin_last_sweep_at'],'2026-10-14T10:00:00+00:00')
            other=root/'unmarked';(other/'data').mkdir(parents=True)
            with self.assertRaises(ValueError): restore(snap,other)
            # A corrupted copy MUST abort with no modification to restored state.
            (snap/'seen_jobs.json').write_text('{"broken":true}')
            before=(target/'data/seen_jobs.json').read_bytes()
            with self.assertRaises(Exception): restore(snap,target)
            self.assertEqual(before,(target/'data/seen_jobs.json').read_bytes())

if __name__=='__main__': unittest.main()