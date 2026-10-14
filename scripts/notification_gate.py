"""Release delivery only with valid signed standing grants and configured secrets."""
from pathlib import Path
import os, yaml
from sources.approval import approved
root=Path(__file__).resolve().parents[1]
cfg=yaml.safe_load((root/'config.yaml').read_text())
channels=[]
if approved('email',cfg) and all(os.getenv(k) for k in ('EMAIL_SENDER','EMAIL_PASSWORD','EMAIL_RECIPIENT')):
    channels.append('email')
if approved('telegram',cfg) and all(os.getenv(k) for k in ('TELEGRAM_BOT_TOKEN','TELEGRAM_CHAT_ID')):
    channels.append('telegram')
if os.getenv('GITHUB_OUTPUT'):
    with open(os.environ['GITHUB_OUTPUT'],'a',encoding='utf-8') as f:
        f.write('enabled='+('true' if channels else 'false')+'\n')
print('Approved delivery transports: '+(', '.join(channels) if channels else 'none; no send'))