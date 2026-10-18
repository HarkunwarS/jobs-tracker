"""Decide which channels can deliver. Fail the run LOUDLY if none can, so GitHub emails you."""
from pathlib import Path
import os, sys, yaml
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sources.approval import approved
root = Path(__file__).resolve().parents[1]
cfg = yaml.safe_load((root / 'config.yaml').read_text())
need = {'email': ('EMAIL_SENDER', 'EMAIL_PASSWORD', 'EMAIL_RECIPIENT'),
        'telegram': ('TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID')}
channels = []
for name, keys in need.items():
    missing = [k for k in keys if not os.getenv(k)]
    if not approved(name, cfg):
        print(f'::warning::{name} disabled in config.yaml')
    elif missing:
        print(f'::warning::{name} enabled but secrets missing: {", ".join(missing)}')
    else:
        channels.append(name)
if os.getenv('GITHUB_OUTPUT'):
    with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as f:
        f.write('enabled=' + ('true' if channels else 'false') + '\n')
print('Delivery channels: ' + (', '.join(channels) if channels else 'NONE'))
if not channels:
    print('::error::No notification channel can send. Alerts are NOT being delivered.')
    sys.exit(1)
