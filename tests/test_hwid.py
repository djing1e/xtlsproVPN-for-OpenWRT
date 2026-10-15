import unittest,tempfile,subprocess,json,os,re
from pathlib import Path
BASE=Path(__file__).resolve().parent
class Hwid(unittest.TestCase):
 def test_identity_headers_and_persistence(self):
  source=(BASE.parent/'package/xtlsprovpn/files/usr/lib/forkop-xray/main.uc').read_text()
  function=source[source.index('function settings()'):source.index('function cache()')]
  function=function.replace("let uci = require('uci').cursor();","let uci={get_all:()=>json(fs.readfile(ARGV[0]))};")
  with tempfile.TemporaryDirectory() as d:
   d=Path(d);settings=d/'settings.json';script=d/'test.uc'
   script.write_text("let fs=require('fs');let state_dir=ARGV[1];function quote(v){return chr(39)+replace(v,/'/g,chr(39)+chr(92)+chr(39)+chr(39))+chr(39);}function command(a){return join(' ',map(a,quote));}\n"+function+"\nprintf('%J',settings());")
   env=dict(os.environ);env.pop('FX_SETTINGS',None)
   def run(s):
    settings.write_text(json.dumps(s));p=subprocess.run(['ucode',str(script),str(settings),str(d)],env=env,text=True,capture_output=True)
    self.assertEqual(p.returncode,0,p.stderr);return json.loads(p.stdout)
   self.assertEqual(run({'hwid':'old'})['hwid'],'old')
   self.assertEqual(run({'hwid':'old','hwid_enabled':'0'})['hwid'],'')
   self.assertFalse((d/'device-hwid').exists())
   a=run({'hwid_enabled':'1'});b=run({'hwid_enabled':'1'})
   self.assertRegex(a['hwid'],r'^xtlsproRouter\(id:[a-f0-9-]{36}\)$');self.assertEqual(a,b)
   self.assertEqual((d/'device-hwid').stat().st_mode&0o777,0o600)
   self.assertEqual(run({'hwid_enabled':'1','hwid':'manual-2'})['hwid'],'manual-2')
   self.assertEqual(run({'hwid_enabled':'1'})['hwid'],a['hwid'])
if __name__=='__main__':unittest.main()
