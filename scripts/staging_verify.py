"""Fast fail-closed static CI guard: no schedules, secrets, sends or writes."""
from pathlib import Path
import sys
import yaml

ROOT = Path(__file__).resolve().parents[1]
cfg = yaml.safe_load((ROOT / 'config.yaml').read_text())
assert cfg['runtime']['mode'] == 'staging'
assert all(cfg['notifications'][x]['enabled'] is False for x in ('email', 'telegram', 'events_email'))
for file in (ROOT / '.github/workflows/tracker.yml', ROOT / '.github/workflows/events.yml'):
    text = file.read_text()
    wf = yaml.safe_load(text)
    triggers = wf.get('on', wf.get(True, {})) or {}
    assert 'schedule' not in triggers, file
    assert set(triggers) == {'workflow_dispatch'}, file
    assert wf['permissions'] == {'contents': 'read'}, file
    forbidden = ('secrets.', 'run.py --deliver', 'events_run.py', 'persist_state.py',
                 'run.py --prepare', 'TELEGRAM_BOT_TOKEN', 'EMAIL_PASSWORD', 'contents: write')
    assert not any(x in text for x in forbidden), file
print('PASS: offline-only staging workflows, notification flags OFF, no schedules/secrets/writes')