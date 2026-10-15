import json, os, subprocess, tempfile, unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/'package/xtlsprovpn/files/usr/bin/xray-lab-local-policy'
MOCK='''#!/usr/bin/env python3
import os,json,sys
from pathlib import Path
p=Path(os.environ['MOCK_STATE']);s=json.loads(p.read_text());a=sys.argv[1:]
if Path(sys.argv[0]).name=='uci':
 k=a[-1];d={'xray_core.general.transparent_proxy_enable':'1','xray_lab_dns.main.enabled':'1','xray_lab_dns.main.sources':'br-lan br-guest'}
 print(d[k]);sys.exit(0)
if a==['-4','-o','rule','show','protocol','242']:
 for v in s['owned']:print('103: from all to '+v+' fwmark 0xfb lookup main proto 242')
elif a==['-4','-o','rule','show']:
 for v in s['owned']+s.get('foreign',[]):print('103: from all to '+v+' fwmark 0xfb lookup main')
 print('110: not from all fwmark 0x1bd00 lookup netbird')
elif a[:4]==['-4','route','show','table']:
 for v in s['routes'].get(a[a.index('dev')+1],[]):print(v+' proto kernel scope link src 192.168.5.1')
elif a[:3] in (['-4','rule','add'],['-4','rule','del']):
 assert a[3:7]==['pref','103','fwmark','0xfb/0xffffffff'] and a[-4:]==['lookup','main','protocol','242']
 v=a[a.index('to')+1]
 if a[2]=='add':
  assert v not in s['owned']+s.get('foreign',[]);s['owned'].append(v)
 else:s['owned'].remove(v)
 s['changes']+=1;p.write_text(json.dumps(s))
else:raise Exception(a)
'''
class LocalPolicy(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.p=Path(self.tmp.name)
  for name in ['ip','uci']:
   f=self.p/name;f.write_text(MOCK);f.chmod(0o755)
  self.state=self.p/'state.json'
  self.put({'owned':[], 'routes':{'br-lan':['192.168.5.0/24'],'br-guest':['192.168.7.0/24']},'changes':0})
  self.env={**os.environ,'PATH':str(self.p)+':'+os.environ['PATH'],'MOCK_STATE':str(self.state),'FX_POLICY_RUN':str(self.p/'run')}
 def tearDown(self):self.tmp.cleanup()
 def put(self,s):self.state.write_text(json.dumps(s))
 def get(self):return json.loads(self.state.read_text())
 def run_policy(self,action='up',success=True):
  p=subprocess.run(['sh',str(SCRIPT),action],env=self.env,capture_output=True,text=True)
  self.assertEqual(p.returncode==0,success,p.stderr)
 def test_multilan_idempotence_refresh_cleanup(self):
  self.run_policy();self.assertEqual(set(self.get()['owned']),{'192.168.5.0/24','192.168.7.0/24'})
  self.run_policy();self.assertEqual(self.get()['changes'],2)
  s=self.get();s['routes']['br-guest']=['192.168.8.0/24'];self.put(s)
  self.run_policy();self.assertEqual(set(self.get()['owned']),{'192.168.5.0/24','192.168.8.0/24'})
  self.run_policy('down');self.assertEqual(self.get()['owned'],[])
 def test_existing_manual_rule_is_preserved(self):
  s=self.get();s['foreign']=['192.168.5.0/24'];self.put(s)
  self.run_policy();self.assertEqual(self.get()['owned'],['192.168.7.0/24'])
  self.run_policy('down');self.assertEqual(self.get()['foreign'],['192.168.5.0/24'])
  s=self.get();s['foreign']=[];self.put(s)
  self.run_policy();self.assertIn('192.168.5.0/24',self.get()['owned'])
 def test_bad_or_default_route_changes_nothing(self):
  for bad in ['default','0.0.0.0/0','999.168.1.0/24','192.168.1.0/33']:
   s=self.get();s['routes']['br-lan']=[bad];self.put(s)
   self.run_policy(success=False);self.assertEqual(self.get()['changes'],0)
if __name__=='__main__':unittest.main()
