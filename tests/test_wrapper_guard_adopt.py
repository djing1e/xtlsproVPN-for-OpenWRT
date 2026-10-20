import json,os,subprocess,tempfile,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'integrations/router-bot/router/enable-wrapper-guard.sh'
MOCK='''#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
r=Path(os.environ['ADOPT_ROOT']);name=Path(sys.argv[0]).name;a=[v for v in sys.argv[1:] if v!='-q']
with (r/'calls').open('a') as f:f.write(json.dumps([name,*a])+'\\n')
if name=='id':print(0)
elif name=='pidof':print(123)
elif name=='ucode':sys.exit(0)
elif name=='netbird':print(json.dumps({'management':{'connected':True,'url':'https://nb.example:443'},'signal':{'connected':True}}))
elif name=='jsonfilter':
 d=json.loads(Path(a[1]).read_text())
 for key in a[3][2:].split('.'):d=d[key]
 print(json.dumps(d) if type(d)==bool else d)
elif name=='wrapper':sys.exit(0 if a==['enabled'] else 1)
elif name=='guard':
 if a==['enabled']:sys.exit(0 if (r/'guard-enabled').exists() else 1)
 if a==['running']:sys.exit(0 if (r/'guard-running').exists() else 1)
 if a==['enable']:(r/'guard-enabled').touch()
 if a==['start']:
  if os.environ.get('FAIL_GUARD'):sys.exit(1)
  (r/'guard-running').touch()
 if a==['disable']:(r/'guard-enabled').unlink(missing_ok=True)
 if a==['stop']:(r/'guard-running').unlink(missing_ok=True)
elif name=='uci':
 file=r/'config';d=json.loads(file.read_text())
 if a[0]=='changes':print('pending' if os.environ.get('PENDING_UCI') else '')
 if a[0]=='set':
  key,value=a[1].split('=',1);d[key.split('.')[-1]]=value;file.write_text(json.dumps(d))
 if a[0]=='get':
  value=d.get(a[1].split('.')[-1])
  if value is None:sys.exit(1)
  print(value)
'''

class WrapperGuardAdoption(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.bin=self.root/'bin';self.bin.mkdir();self.lib=self.root/'lib';self.lib.mkdir()
        for name in ['id','pidof','ucode','netbird','jsonfilter','wrapper','guard','uci']:
            path=self.bin/name;path.write_text(MOCK);path.chmod(0o755)
        self.config=self.root/'config';self.config.write_text(json.dumps({'enabled':'0','management_url':''}))
        for name in ['netbird.uc','netbird_guard.uc']:
            (self.lib/name).write_text("const SERVICE='/etc/init.d/netbird';\n// FX_NETBIRD_EXPECTED_VERSION guard is retained\nreturn {installed:true};\n")
        self.before={p:p.read_bytes() for p in [self.config,*self.lib.iterdir()]}
        self.script=self.root/'adopt.sh'
        source=SOURCE.read_text().replace('/etc/init.d/netbird-wrapper',str(self.bin/'wrapper')).replace('/etc/init.d/xray_netbird_guard',str(self.bin/'guard')).replace('/etc/config/xray_lab_netbird',str(self.config)).replace('/usr/share/xray/lab',str(self.lib)).replace('/root/xtls-before-wrapper-guard.',str(self.root/'backup.'))
        for name in ['xtlspro-bot-admin','xtlspro-netbird','xray-lab-control']:source=source.replace('/var/run/'+name,str(self.root/name))
        self.script.write_text(source)
        self.env=dict(os.environ,PATH=str(self.bin)+':'+os.environ['PATH'],ADOPT_ROOT=str(self.root))
    def run_script(self,**env):return subprocess.run(['sh',str(self.script)],env={**self.env,**env},capture_output=True,text=True,timeout=20)
    def test_adopt_only_enables_guard_and_preserves_existing_native_patches(self):
        result=self.run_script();self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        data=json.loads(self.config.read_text());self.assertEqual(data['enabled'],'1');self.assertEqual(data['service'],'netbird-wrapper')
        self.assertEqual(data['management_url'],'https://nb.example:443')
        for name in ['netbird.uc','netbird_guard.uc']:
            self.assertIn("?.service=='netbird-wrapper'",(self.lib/name).read_text())
            self.assertIn('FX_NETBIRD_EXPECTED_VERSION',(self.lib/name).read_text())
        calls=[json.loads(row) for row in (self.root/'calls').read_text().splitlines()]
        self.assertEqual([a for a in calls if a[0]=='netbird'],[['netbird','status','--json']])
        self.assertEqual([a for a in calls if a[0]=='wrapper'],[['wrapper','enabled']])
        self.assertTrue((self.root/'guard-running').exists())
    def test_guard_start_failure_restores_config_helpers_and_autostart(self):
        self.assertNotEqual(self.run_script(FAIL_GUARD='1').returncode,0)
        for path,body in self.before.items():self.assertEqual(path.read_bytes(),body)
        self.assertFalse((self.root/'guard-enabled').exists())
    def test_pending_uci_is_not_overwritten(self):
        self.assertNotEqual(self.run_script(PENDING_UCI='1').returncode,0)
        for path,body in self.before.items():self.assertEqual(path.read_bytes(),body)
    def test_unknown_helper_version_refused_before_config_changes(self):
        (self.lib/'netbird.uc').write_text('unknown version')
        self.assertNotEqual(self.run_script().returncode,0)
        self.assertEqual(self.config.read_bytes(),self.before[self.config])
