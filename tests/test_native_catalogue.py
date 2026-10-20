#!/usr/bin/env python3
"""Native yichya generator with a five-node catalogue and UI selection persistence.
Only UCI storage is stubbed; prepare and the native generator are real ucode.
"""
import copy, hashlib, json, os, re, subprocess, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'package/xtlsprovpn'
XRAY=os.environ.get('XRAY_TEST_BIN','/tmp/fx-native-test/xray')
class CatalogueTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.enc=re.findall(r'"encryption": "([^"]+)"',subprocess.check_output([XRAY,'vlessenc'],text=True))[0]
  cls.pub=re.search(r'Password \(PublicKey\): (\S+)',subprocess.check_output([XRAY,'x25519'],text=True))[1]
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.d=Path(self.tmp.name)
  (self.d/'modules').mkdir();(self.d/'stage').mkdir()
  (self.d/'modules/uci.uc').write_text('''let fs=require('fs');
export function cursor(dir) { let data={}; return {
 load:function(p){data=json(fs.readfile(dir ? getenv('FX_NATIVE_UCI_JSON') : getenv('FX_PREVIOUS_UCI_JSON')) || '{}');return true;},
 get_all:function(p){return data;},
 set:function(p,s,k,v){if(v==null)data[s]={'.name':s,'.type':k};else data[s][k]=v;return true;},
 commit:function(p){fs.writefile(dir+'/'+p,sprintf('%J',data));return true;}
};};
''')
  (self.d/'lan.json').write_text(json.dumps({'up':True,'l3_device':'br-lan','ipv4-address':[{'address':'172.16.100.95','mask':23}]}))
  (self.d/'previous.json').write_text(json.dumps({'general':{'tcp_balancer_v4':['labnode01'],'udp_balancer_v4':['labnode01']},'labnode01':{'.type':'servers'}}))
  self.nodes=[]
  for name,host in [('🇫🇮 Финляндия','fi.example.test'),('🇩🇪 Германия','de.example.test'),('🇳🇱 Нидерланды','nl.example.test'),('🇨🇭 Швейцария','ch.example.test'),('🇪🇪 Эстония','ee.example.test')]:
   self.nodes.append({'id':hashlib.sha256(host.encode()).hexdigest(),'name':name,'outbound':{'protocol':'vless','settings':{'vnext':[{'address':host,'port':443,'users':[{'id':'00000000-0000-4000-8000-000000000001','encryption':self.enc,'flow':'xtls-rprx-vision'}]}]},'streamSettings':{'network':'raw','security':'reality','realitySettings':{'serverName':host,'fingerprint':'firefox','publicKey':self.pub,'shortId':'1234567890abcdef','spiderX':'/'}}}})
  self.env=dict(os.environ,XRAY_LAB_NETWORK_JSON=str(self.d/'lan.json'),FX_PREVIOUS_UCI_JSON=str(self.d/'previous.json'),FX_NATIVE_UCI_JSON=str(self.d/'stage/xray_core'),XRAY_UCI_CONFIG_DIR=str(self.d/'stage'))
 def prepare(self,success=True):
  (self.d/'cache.json').write_text(json.dumps({'nodes':self.nodes,'selected':self.nodes[0]['id'] if self.nodes else ''}))
  (self.d/'prepare.uc').write_text((BASE/'files/usr/share/xray/lab_prepare.uc').read_text().replace('/etc/forkop-xray/subscription.json',str(self.d/'cache.json')))
  r=subprocess.run(['ucode','-L',str(self.d/'modules'),str(self.d/'prepare.uc'),str(self.d/'stage')],env=self.env,capture_output=True,text=True)
  self.assertEqual(r.returncode==0,success,r.stderr)
  if success:return json.loads((self.d/'stage/xray_core').read_text())
 def generate(self):
  r=subprocess.run(['ucode','-L',str(self.d/'modules'),str(BASE/'files/usr/share/xray/gen_config.uc')],env=self.env,capture_output=True,text=True)
  self.assertEqual(r.returncode,0,r.stderr);c=json.loads(r.stdout)
  checked=copy.deepcopy(c)
  for field in ('access','error'):
   if checked.get('log',{}).get(field) not in (None,'','none'):
    checked['log'][field]=str(self.d/('xray-'+field+'.log'))
  p=self.d/'config.json';p.write_text(json.dumps(checked))
  check=subprocess.run([XRAY,'run','-test','-c',str(p)],capture_output=True,text=True)
  self.assertEqual(check.returncode,0,check.stdout+check.stderr);return c
 def test_five_named_nodes_and_only_selected_outbounds(self):
  u=self.prepare();catalog={k:v for k,v in u.items() if v.get('.type')=='servers'}
  self.assertEqual(len(catalog),5);self.assertEqual({v['alias'] for v in catalog.values()},{n['name'] for n in self.nodes})
  self.assertTrue(all(len(k)==9 for k in catalog))
  c=self.generate();active=[o for o in c['outbounds'] if o['protocol']=='vless']
  self.assertEqual(len(active),2);self.assertEqual({o['settings']['vnext'][0]['address'] for o in active},{'fi.example.test'})
  self.assertTrue(any(r.get('balancerTag')=='tcp_outbound_v4' and r.get('network')=='tcp' for r in c['routing']['rules']))
  self.assertTrue(any(r.get('balancerTag')=='udp_outbound_v4' and r.get('network')=='udp' for r in c['routing']['rules']))
 def test_ui_germany_selection_controls_tcp_udp_and_dns(self):
  u=self.prepare();key=next(k for k,v in u.items() if v.get('alias')=='🇩🇪 Германия')
  u['general']['tcp_balancer_v4']=[key];u['general']['udp_balancer_v4']=[key]
  (self.d/'previous.json').write_text(json.dumps(u));self.prepare();c=self.generate()
  self.assertEqual({o['settings']['vnext'][0]['address'] for o in c['outbounds'] if o['protocol']=='vless'},{'de.example.test'})
  self.assertEqual(c['dns']['servers'][0]['domains'],['full:de.example.test'])
 def test_rotated_identity_keeps_selected_country(self):
  u=self.prepare();key=next(k for k,v in u.items() if v.get('alias')=='🇩🇪 Германия')
  for f in ['tcp_balancer_v4','udp_balancer_v4']:u['general'][f]=[key]
  (self.d/'previous.json').write_text(json.dumps(u))
  self.nodes[1]['id']=hashlib.sha256(b'rotated-de').hexdigest()
  u=self.prepare();nextkey=u['general']['tcp_balancer_v4'][0]
  self.assertNotEqual(key,nextkey);self.assertEqual(u[nextkey]['alias'],'🇩🇪 Германия');self.generate()
 def test_identifier_prefix_collision_is_resolved(self):
  self.nodes[1]['id']=self.nodes[0]['id'][:6]+hashlib.sha256(b'collision').hexdigest()[6:]
  u=self.prepare();self.assertEqual(len([k for k,v in u.items() if v.get('.type')=='servers']),5);self.generate()
 def test_invalid_cache_does_not_commit_catalogue(self):
  before=self.prepare();self.nodes=[];self.prepare(False)
  self.assertEqual(json.loads((self.d/'stage/xray_core').read_text()),before)
if __name__=='__main__':unittest.main()
