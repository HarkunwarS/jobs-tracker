"""Fail closed on unsafe production discovery configuration."""
from pathlib import Path
import yaml
ROOT=Path(__file__).resolve().parents[1]
cfg=yaml.safe_load((ROOT/'config.yaml').read_text())
assert cfg['runtime']['mode']=='production' and cfg['runtime'].get('dry_run') is False
assert cfg['notifications']['events_email']['enabled'] is False
wf=yaml.safe_load((ROOT/'.github/workflows/tracker.yml').read_text())
triggers=wf.get('on', wf.get(True, {})) or {}
assert 'schedule' in triggers and 'workflow_dispatch' in triggers
assert wf['permissions']=={'contents':'write'}
assert 'scripts/persist_state.py main' in (ROOT/'.github/workflows/tracker.yml').read_text()
events=yaml.safe_load((ROOT/'.github/workflows/events.yml').read_text())
assert 'schedule' not in (events.get('on',events.get(True,{})) or {})
assert 'events_run.py' not in (ROOT/'.github/workflows/events.yml').read_text()
print('PASS: production discovery and state persistence enabled; events delivery disabled; notifications fail closed')