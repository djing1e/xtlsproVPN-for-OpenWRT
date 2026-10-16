import json,subprocess,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]/'package/xtlsprovpn/files'
class TLS(unittest.TestCase):
 def run_tls(self,options):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'test.uc';p.write_text('import {tls_outbound_settings,verified_tls_options} from '+json.dumps(str(ROOT/'usr/share/xray/common/tls.mjs'))+';let fs=require("fs");let input=json(ARGV[0]);let result=input.generated?tls_outbound_settings(input.generated,"vless"):input;verified_tls_options(result);printf("%J",result);')
   return subprocess.run(['ucode',str(p),json.dumps(options)],text=True,capture_output=True)
 def test_default_is_verified_and_omits_removed_field(self):
  r=self.run_tls({'generated':{}});self.assertEqual(r.returncode,0,r.stderr);self.assertNotIn('allowInsecure',json.loads(r.stdout))
 def test_false_removed_and_pins_preserved_in_nested_download(self):
  r=self.run_tls({'tlsSettings':{'allowInsecure':False,'pinnedPeerCertSha256':'abc'},'xhttpSettings':{'extra':{'downloadSettings':{'tlsSettings':{'allowInsecure':False,'verifyPeerCertByName':'example.test'}}}}})
  self.assertEqual(r.returncode,0,r.stderr);d=json.loads(r.stdout);self.assertNotIn('allowInsecure',r.stdout);self.assertEqual(d['tlsSettings']['pinnedPeerCertSha256'],'abc')
 def test_explicit_insecure_is_rejected_without_guessing_pin(self):
  for o in ({'generated':{'vless_tls_insecure':'1'}},{'tlsSettings':{'allowInsecure':True}}):
   r=self.run_tls(o);self.assertNotEqual(r.returncode,0);self.assertIn('allowInsecure=true',r.stderr)
if __name__=='__main__':unittest.main()
