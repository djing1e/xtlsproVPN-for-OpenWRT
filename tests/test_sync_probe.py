import json,subprocess,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]/'package/xtlsprovpn/files'
class Probe(unittest.TestCase):
 def test_only_loopback_listeners_and_changed_outbounds(self):
  base={'inbounds':[{'tag':'socks_inbound','port':1080},{'tag':'dns_server_inbound:5300','port':5300},{'tag':'api','port':8080}], 'outbounds':[{'tag':'fx_node:cfg000001','protocol':'vless','settings':{}},{'tag':'fx_node:cfg000002','protocol':'vless','settings':{}}], 'routing':{'rules':[{'outboundTag':'api'}],'balancers':[{'tag':'fx_main'}]},'api':{},'metrics':{}}
  for changed in (True,False):
   with self.subTest(changed=changed),tempfile.TemporaryDirectory() as t:
    p=Path(t);old=json.loads(json.dumps(base))
    if changed:old['outbounds']=old['outbounds'][:1]
    (p/'candidate').write_text(json.dumps(base));(p/'old').write_text(json.dumps(old))
    r=subprocess.run(['ucode',str(ROOT/'usr/share/xray/lab/sync_probe.uc'),str(p/'candidate'),str(p/'old'),str(p/'probe'),str(p/'ports'),str(p/'error')],capture_output=True,text=True)
    self.assertEqual(r.returncode,0,r.stderr);c=json.loads((p/'probe').read_text());self.assertTrue(all(i['listen']=='127.0.0.1' for i in c['inbounds']));self.assertNotIn('api',c);self.assertNotIn('metrics',c);self.assertEqual(c['routing']['rules'][len(c['routing']['rules'])-1],{'type':'field','inboundTag':['fx_sync_main'],'balancerTag':'fx_main'});self.assertEqual((p/'ports').read_text(),'12001\n' if changed else '')
if __name__=='__main__':unittest.main()
