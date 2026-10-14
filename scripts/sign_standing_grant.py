"""Run ONLY on your own computer. Never commit the private key or grants."""
import argparse, base64, json
from datetime import datetime,timedelta,timezone
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding,PrivateFormat,NoEncryption,PublicFormat
p=argparse.ArgumentParser()
p.add_argument('--channel',required=True,choices=['email','telegram'])
p.add_argument('--private-key',required=True,type=Path)
p.add_argument('--days',type=int,default=14)
a=p.parse_args()
if not 1 <= a.days <= 30: raise SystemExit('Days must be 1-30')
if a.private_key.exists():
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    key=load_pem_private_key(a.private_key.read_bytes(),password=None)
else:
    key=Ed25519PrivateKey.generate()
    a.private_key.write_bytes(key.private_bytes(Encoding.PEM,PrivateFormat.PKCS8,NoEncryption()))
    a.private_key.chmod(0o600)
now=datetime.now(timezone.utc)
grant={'channel':a.channel,'environment':'production','repository':'HarkunwarS/jobs-tracker',
       'scope':'scheduled','issued_at':now.isoformat(),'expires_at':(now+timedelta(days=a.days)).isoformat()}
signature=key.sign(json.dumps(grant,sort_keys=True,separators=(',',':')).encode()).hex()
bundle=base64.b64encode(json.dumps({'grant':grant,'signature':signature}).encode()).decode()
public=base64.b64encode(key.public_key().public_bytes(Encoding.PEM,PublicFormat.SubjectPublicKeyInfo)).decode()
print('Set repository Actions secret NOTIFICATION_APPROVAL_PUBLIC_KEY_B64 to:', public)
print('Set Actions secret '+a.channel.upper()+'_APPROVAL_GRANT_B64 to:',bundle)
print('Do not share or commit the private key:',a.private_key)