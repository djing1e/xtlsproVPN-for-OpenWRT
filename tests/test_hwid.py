import unittest,tempfile,subprocess,json,os,re,hashlib
from pathlib import Path
BASE=Path(__file__).resolve().parent
class Hwid(unittest.TestCase):
 def test_identity_headers_and_persistence(self):
  source=(BASE.parent/'package/xtlsprovpn/files/usr/lib/forkop-xray/main.uc').read_text()
  function=source[source.index('function settings()'):source.index('function cache()')]
  function=function.replace("let uci = require('uci').cursor();","let uci={get_all:()=>json(fs.readfile(ARGV[0]))};")
  with tempfile.TemporaryDirectory() as d:
   d=Path(d);settings=d/'settings.json';script=d/'test.uc'
   (d/'mac').write_text('aa:bb:cc:dd:ee:ff\n');(d/'model').write_text('Test Router\n')
   core=d/'xray';core.write_text('#!/bin/sh\necho "Xray 26.7.28 test"\n');core.chmod(0o755)
   function=function.replace('/sys/class/net/eth0/address',str(d/'mac')).replace('/tmp/sysinfo/model',str(d/'model')).replace('/usr/libexec/forkop-xray/xray',str(core))
   script.write_text("let fs=require('fs');let state_dir=ARGV[1];function quote(v){return chr(39)+replace(v,/'/g,chr(39)+chr(92)+chr(39)+chr(39))+chr(39);}function command(a){return join(' ',map(a,quote));}\n"+function+"\nprintf('%J',settings());")
   env=dict(os.environ);env.pop('FX_SETTINGS',None)
   def run(s):
    settings.write_text(json.dumps(s));p=subprocess.run(['ucode',str(script),str(settings),str(d)],env=env,text=True,capture_output=True)
    self.assertEqual(p.returncode,0,p.stderr);return json.loads(p.stdout)
   self.assertEqual(run({'hwid':'old'})['hwid'],'old')
   self.assertEqual(run({'hwid':'old','hwid_enabled':'0'})['hwid'],'')
   self.assertFalse((d/'device-hwid-short').exists())
   a=run({'hwid_enabled':'1'});b=run({'hwid_enabled':'1'})
   self.assertRegex(a['hwid'],r'^[a-f0-9]{4}(-[a-f0-9]{4}){3}$');self.assertRegex(a['hwid'],r'^[a-zA-Z0-9=-]{10,64}$');self.assertEqual(a,b)
   h=hashlib.md5(b'aa:bb:cc:dd:ee:ff-Test Router').hexdigest()[:16]
   self.assertEqual(a['hwid'],'-'.join(h[i:i+4] for i in range(0,16,4)))
   self.assertEqual(a['user_agent'],'Xray/26.7.28')
   self.assertEqual((d/'device-hwid-short').stat().st_mode&0o777,0o600)
   self.assertEqual(run({'hwid_enabled':'1','hwid':'manual-2'})['hwid'],'manual-2')
   self.assertEqual(run({'hwid_enabled':'1'})['hwid'],a['hwid'])

class HwidTransport(unittest.TestCase):
 def test_headers_reach_curl_and_invalid_hwid_is_rejected(self):
  source=(BASE.parent/'package/xtlsprovpn/files/usr/lib/forkop-xray/main.uc').read_text()
  function=source[source.index('function fetch(s)'):source.index('function summary()')]
  prelude="let fs=require('fs');let run_dir=ARGV[1];function quote(s){return chr(39)+replace(''+s,/'/g,chr(39)+chr(92)+chr(39)+chr(39))+chr(39);}function command(a){return join(' ',map(a,quote));}function accept(){}\n"
  with tempfile.TemporaryDirectory() as directory:
   p=Path(directory);script=p/'fetch.uc';script.write_text(prelude+function+"\nfetch(json(fs.readfile(ARGV[0])));")
   curl=p/'curl';curl.write_text('#!/usr/bin/env python3\nimport os,sys,pathlib\na=sys.argv[1:]\nc=pathlib.Path(a[a.index("--config")+1]).read_text()\npathlib.Path(os.environ["HEADER_CAPTURE"]).write_text(c)\nprint("200",end="")\n');curl.chmod(0o755)
   env={**os.environ,'PATH':str(p)+':'+os.environ['PATH'],'HEADER_CAPTURE':str(p/'captured')}
   settings=p/'settings.json'
   def run(hwid):
    settings.write_text(json.dumps({'subscription_url':'https://subscription.invalid/test','hwid':hwid,'user_agent':'xtlsproVPN/1.0.0'}))
    return subprocess.run(['ucode',str(script),str(settings),str(p)],env=env,text=True,capture_output=True)
   r=run('xtlsproRouter-4b20c39d-5a76-49fb-b172-30d8d7b26791');self.assertEqual(r.returncode,0,r.stderr)
   headers=(p/'captured').read_text()
   for expected in ['X-HWID: xtlsproRouter-','X-Device-OS: OpenWrt Linux','X-Ver-OS:','X-Device-Model:','user-agent = "xtlsproVPN/1.0.0"']:self.assertIn(expected,headers)
   (p/'captured').unlink();r=run('xtlsproRouter(id:4b20c39d-5a76-49fb-b172-30d8d7b26791)');self.assertNotEqual(r.returncode,0);self.assertFalse((p/'captured').exists())
   r=run('');self.assertEqual(r.returncode,0,r.stderr);self.assertNotIn('X-HWID:',(p/'captured').read_text());self.assertNotIn('X-Device-',(p/'captured').read_text())

if __name__=='__main__':unittest.main()
