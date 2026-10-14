"""Real local Git integration tests; no remote network or user checkout touched."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/persist_state.py"


def cmd(*args, cwd=None, check=True):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=check)


@unittest.skipUnless(shutil.which("git"), "git executable required")
class GitStateRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.remote = root / "remote.git"
        self.local = root / "local"
        self.other = root / "other"
        cmd("git", "init", "--bare", "--initial-branch=main", str(self.remote))
        cmd("git", "clone", str(self.remote), str(self.local))
        self.config(self.local)
        (self.local / "data").mkdir()
        (self.local / "data/seen_jobs.json").write_text('{"initial":"2026-07-21"}')
        (self.local / "data/notification_outbox.json").write_text('{"schema_version":1,"jobs":{}}')
        (self.local / "data/discovery_state.json").write_text('{"linkedin_last_sweep_at":""}')
        cmd("git", "add", "data", cwd=self.local)
        cmd("git", "commit", "-m", "initial", cwd=self.local)
        (self.local / "config.yaml").write_text("runtime:\n  mode: production\n")
        cmd("git", "add", "config.yaml", cwd=self.local)
        cmd("git", "commit", "-m", "disposable fixture runtime", cwd=self.local)
        cmd("git", "push", "origin", "main", cwd=self.local)
        cmd("git", "checkout", "-b", "staging/rehearsal", cwd=self.local)
        cmd("git", "push", "origin", "staging/rehearsal", cwd=self.local)
        cmd("git", "clone", str(self.remote), str(self.other))
        self.config(self.other)
        cmd("git", "checkout", "staging/rehearsal", cwd=self.other)

    def config(self, path):
        cmd("git", "config", "user.name", "Tester", cwd=path)
        cmd("git", "config", "user.email", "test@example.invalid", cwd=path)

    def test_conflicting_state_commit_merges_all_ids(self):
        (self.other / "data/seen_jobs.json").write_text('{"initial":"2026-07-21","remote_job":"2026-10-14"}')
        cmd("git", "add", "data", cwd=self.other)
        cmd("git", "commit", "-m", "remote update", cwd=self.other)
        cmd("git", "push", "origin", "staging/rehearsal", cwd=self.other)
        (self.local / "data/seen_jobs.json").write_text('{"initial":"2026-07-21","local_job":"2026-10-14"}')
        p = cmd(sys.executable, str(SCRIPT), "staging/rehearsal", cwd=self.local, check=False)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        cmd("git", "pull", "--ff-only", cwd=self.other)
        result = json.loads((self.other / "data/seen_jobs.json").read_text())
        self.assertEqual(set(result), {"initial", "remote_job", "local_job"})

    def test_failed_push_keeps_state_locally_and_exits_failure(self):
        (self.local / "data/seen_jobs.json").write_text('{"initial":"2026-07-21","failed_job":"2026-10-14"}')
        cmd("git", "remote", "set-url", "origin", str(self.remote) + "-does-not-exist", cwd=self.local)
        p = cmd(sys.executable, str(SCRIPT), "staging/rehearsal", cwd=self.local, check=False)
        self.assertNotEqual(p.returncode, 0)
        result = json.loads((self.local / "data/seen_jobs.json").read_text())
        self.assertIn("failed_job", result)


class WorkflowConfigurationTests(unittest.TestCase):
    def test_notifications_follow_first_persist_step(self):
        # Phase 4 supersedes the P0 send/persist order by removing BOTH stages.
        content = (SCRIPT.parent.parent / ".github/workflows/tracker.yml").read_text()
        self.assertNotIn("id: deliver", content)
        self.assertNotIn("id: persist_prepare", content)
        self.assertNotIn("persist_state.py", content)
        self.assertIn("run.py --dry-run", content)
        self.assertNotIn("secrets.", content)


if __name__ == "__main__":
    unittest.main()