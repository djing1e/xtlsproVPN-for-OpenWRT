import json,os,shutil,subprocess,tempfile,unittest
from pathlib import Path
import test_netbird as fixture
ROOT=Path(__file__).resolve().parents[1]
FILES=ROOT/'package/xtlsprovpn/files'
@unittest.skipUnless(shutil.which('ucode'),'ucode runtime required')
class SubscriptionPrivate(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.r=Path(self.tmp.name)
  (self.r/'uci.uc').write_text(fixture.UCI)
  self.config=self.r/'uci.json';self.secret='https://private.example/sub/DO-NOT-EXPORT'
  self.config.write_text(json.dumps({'forkop_xray':{'main':{'subscription_url':self.secret,'hwid_enabled':'1','user_agent':'Xray/test'}}}))
  self.env=dict(os.environ,TEST_UCI_JSON=str(self.config))
  source=(FILES/'usr/libexec/rpcd/xray_lab_subscription').read_text().replace('/var/run/xray-lab-control/action.lock',str(self.r/'lock')).replace('/etc/config/forkop_xray',str(self.config))
  self.script=self.r/'rpc.uc';self.script.write_text(source)
 def call(self,method,p=None):
  return subprocess.run(['ucode','-L',str(self.r),str(self.script),'call',method],input=json.dumps(p or {}),capture_output=True,text=True,env=self.env)
 def test_status_never_returns_saved_url(self):
  r=self.call('status');self.assertEqual(r.returncode,0,r.stderr);d=json.loads(r.stdout)
  self.assertTrue(d['configured']);self.assertNotIn('subscription_url',d);self.assertNotIn(self.secret,r.stdout)
 def test_blank_preserves_url_and_replacement_is_not_echoed(self):
  p={'subscription_url':'','user_agent':'Xray/new','hwid_enabled':'1','hwid':''}
  self.assertTrue(json.loads(self.call('save',p).stdout)['ok'])
  self.assertEqual(json.loads(self.config.read_text())['forkop_xray']['main']['subscription_url'],self.secret)
  p['subscription_url']='https://new.example/sub/NEW-SECRET';r=self.call('save',p)
  self.assertTrue(json.loads(r.stdout)['ok']);self.assertNotIn('NEW-SECRET',r.stdout+r.stderr)
 def test_invalid_url_and_busy_lock_preserve_secret(self):
  import fcntl
  original=self.config.read_text();p={'subscription_url':'http://invalid/secret','hwid_enabled':'1'}
  self.assertIn('error',json.loads(self.call('save',p).stdout));self.assertEqual(original,self.config.read_text())
  with (self.r/'lock').open('w') as lock:
   fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);p['subscription_url']='https://valid.test/new'
   self.assertIn('error',json.loads(self.call('save',p).stdout));self.assertEqual(original,self.config.read_text())
 def test_application_acl_does_not_grant_raw_subscription_uci(self):
  a=json.loads((FILES/'usr/share/rpcd/acl.d/luci-app-forkop-xray.json').read_text())['luci-app-forkop-xray']
  for mode in ['read','write']:self.assertNotIn('forkop_xray',a[mode]['uci'])
if __name__=='__main__':unittest.main()
