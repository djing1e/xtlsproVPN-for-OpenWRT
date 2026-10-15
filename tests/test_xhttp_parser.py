import json,os,subprocess,tempfile,unittest,urllib.parse
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]/'package/xtlsprovpn/files'
class XHTTP(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup);self.p=Path(self.t.name)
  self.script=self.p/'test.uc';self.script.write_text("let fs=require('fs');let p=require('parser');print(sprintf('%J',p.parse(fs.readfile(ARGV[0]))));")
 def parse(self,body):
  path=self.p/'subscription';path.write_text(body)
  r=subprocess.run(['ucode','-L',str(ROOT/'usr/lib/forkop-xray'),str(self.script),str(path)],text=True,capture_output=True)
  self.assertEqual(r.returncode,0,r.stderr);return json.loads(r.stdout)
 def uri(self,**q):
  return 'vless://00000000-0000-4000-8000-000000000001@cdn.example.test:443?'+urllib.parse.urlencode({'type':'xhttp','security':'tls','sni':'origin.example.test',**q})+'#XHTTP'
 def test_uri_preserves_extra_alpn_path_and_zero_values(self):
  extra={'xmux':{'maxConnections':4,'cMaxReuseTimes':0},'sessionIDPlacement':'cookie','uplinkDataKey':'X-Amz-Content-Sha256','scMinPostsIntervalMs':14,'downloadSettings':{'address':'download.example.test','port':443,'network':'xhttp','security':'tls'}}
  r=self.parse(self.uri(path='/assets/api/',host='cdn.example.test',mode='packet-up',alpn='h2,http/1.1',extra=json.dumps(extra)))
  o=r['nodes'][0]['outbound'];x=o['streamSettings']['xhttpSettings']
  self.assertEqual(x['extra'],extra);self.assertEqual(x['path'],'/assets/api/');self.assertEqual(o['streamSettings']['tlsSettings']['alpn'],['h2','http/1.1']);self.assertEqual(r['skipped'],[])
 def test_json_preserves_advanced_fields_and_same_address_distinct_paths(self):
  o={'protocol':'vless','tag':'node','settings':{'vnext':[{'address':'cdn.example.test','port':443,'users':[{'id':'00000000-0000-4000-8000-000000000001','encryption':'none'}]}]},'streamSettings':{'network':'xhttp','security':'tls','tlsSettings':{'serverName':'origin.example.test','fingerprint':'chrome'},'xhttpSettings':{'path':'/first/','mode':'packet-up','extra':{'headers':{'X-Test':'value'},'uplinkChunkSize':2048}}}}
  r=self.parse(json.dumps(o));self.assertEqual(r['nodes'][0]['outbound']['streamSettings'],o['streamSettings'])
  r=self.parse(self.uri(path='/first/')+'\n'+self.uri(path='/second/'));self.assertEqual(len(r['nodes']),2)
 def test_rejected_extra_does_not_silently_drop_parameters(self):
  r=self.parse(self.uri()+'\n'+self.uri(extra='not-json')+'\n'+self.uri(unknown='value'))
  self.assertEqual(len(r['nodes']),1);self.assertEqual(len(r['skipped']),2);self.assertIn('extra',r['skipped'][0]['reason'])
 def test_legacy_raw_identity_unchanged_and_xhttp_can_share_endpoint(self):
  key='A'*43
  raw='vless://00000000-0000-4000-8000-000000000001@cdn.example.test:443?type=tcp&security=reality&sni=origin.example.test&pbk='+key
  r=self.parse(raw+'\n'+self.uri());self.assertEqual(len(r['nodes']),2)
  self.assertEqual(json.loads(r['nodes'][0]['identity']),['cdn.example.test',443,'00000000-0000-4000-8000-000000000001','origin.example.test'])
if __name__=='__main__':unittest.main()
