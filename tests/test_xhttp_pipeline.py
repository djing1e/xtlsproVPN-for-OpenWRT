import json,subprocess,unittest
import test_native_catalogue as native
class Pipeline(unittest.TestCase):
 def setUp(self):
  self.enc='none';self.pub='A'*43
  native.CatalogueTests.setUp(self)
 def prepare(self):return native.CatalogueTests.prepare(self)
 def test_xhttp_extra_survives_prepare_and_native_generator(self):
  o=self.nodes[0]['outbound'];o['settings']['vnext'][0]['users'][0]['flow']=''
  stream={'network':'xhttp','security':'tls','tlsSettings':{'serverName':'origin.example.test','fingerprint':'chrome','alpn':['h2']},'xhttpSettings':{'host':'cdn.example.test','path':'/assets/api/','mode':'packet-up','extra':{'scMinPostsIntervalMs':14,'xmux':{'maxConnections':4,'cMaxReuseTimes':0},'uplinkDataKey':'X-Amz-Content-Sha256','sessionIDPlacement':'cookie'}}}
  o['streamSettings']=stream;self.nodes=self.nodes[:1]
  self.prepare()
  r=subprocess.run(['ucode','-L',str(self.d/'modules'),str(native.BASE/'files/usr/share/xray/gen_config.uc')],env=self.env,capture_output=True,text=True)
  self.assertEqual(r.returncode,0,r.stderr);c=json.loads(r.stdout)
  active=[o for o in c['outbounds'] if o['protocol']=='vless'];self.assertTrue(active)
  for outbound in active:
   s=outbound['streamSettings'];self.assertNotIn('allowInsecure',s['tlsSettings']);self.assertEqual(s['network'],'xhttp');self.assertEqual(s['security'],'tls');self.assertEqual(s['xhttpSettings'],stream['xhttpSettings']);self.assertEqual(s['tlsSettings']['serverName'],'origin.example.test');self.assertEqual(s['sockopt']['mark'],253)
if __name__=='__main__':unittest.main()
