import base64,json,os,unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
from sources.approval import approved
class ProductionActivationTests(unittest.TestCase):
    def test_signed_scheduled_grant_only_on_trusted_context(self):
        k=Ed25519PrivateKey.generate();now=datetime.now(timezone.utc)
        grant=dict(channel='email',environment='production',repository='HarkunwarS/jobs-tracker',
                   scope='scheduled',issued_at=now.isoformat(),expires_at=(now+timedelta(days=14)).isoformat())
        sig=k.sign(json.dumps(grant,sort_keys=True,separators=(',',':')).encode()).hex()
        bundle=base64.b64encode(json.dumps(dict(grant=grant,signature=sig)).encode()).decode()
        pub=base64.b64encode(k.public_key().public_bytes(Encoding.PEM,PublicFormat.SubjectPublicKeyInfo)).decode()
        cfg={'runtime':{'mode':'production'},'notifications':{'email':{'enabled':True}}}
        env=dict(GITHUB_ACTIONS='true',GITHUB_REPOSITORY='HarkunwarS/jobs-tracker',
                 GITHUB_REF_NAME='main',GITHUB_EVENT_NAME='schedule',
                 EMAIL_APPROVAL_GRANT_B64=bundle,NOTIFICATION_APPROVAL_PUBLIC_KEY_B64=pub)
        with patch.dict(os.environ,env,clear=True):
            self.assertTrue(approved('email',cfg))
            self.assertFalse(approved('telegram',cfg))
            os.environ['GITHUB_REF_NAME']='another-branch'
            self.assertFalse(approved('email',cfg))
            os.environ['GITHUB_REF_NAME']='main'
            os.environ['EMAIL_APPROVAL_GRANT_B64']='tampered'
            self.assertFalse(approved('email',cfg))
    def test_expires_and_repo_binding(self):
        self.assertFalse(approved('events_email',{'runtime':{'mode':'production'},'notifications':{'events_email':{'enabled':False}}}))